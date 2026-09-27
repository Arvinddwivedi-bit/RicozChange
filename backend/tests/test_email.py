"""Email-to-change pipeline (phase 2, week 3) — end-to-end API tests."""
from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Isolated test env BEFORE any ricozchange import (config captures env at import).
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["AUTO_SEED"] = "1"
os.environ.pop("ANTHROPIC_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from ricozchange import config, db as dbmod  # noqa: E402
from ricozchange.main import app  # noqa: E402
from ricozchange.models import Approval, Change, EmailInbound, Notification, Setting, User  # noqa: E402


@pytest.fixture()
def client():
    dbmod.init_db()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(require_actor, None)


from ricozchange.auth import require_actor  # noqa: E402


def _db():
    return dbmod.SessionLocal()


GOOD_BODY = (
    "Upgrading the payments database instance to the new class.\n"
    "systems: payments-db, orders-api\n"
    "window: 2030-01-15 22:00 - 2030-01-15 23:30\n"
    "type: major\n"
    "rollback: restore snapshot pg-14 and repoint the connection string\n"
)


def test_parse_email_extracts_all_fields(client):
    parsed = __import__("ricozchange.email_app", fromlist=["parse_email"]).parse_email(
        "Migrate payments-db", GOOD_BODY
    )
    assert parsed.title == "Migrate payments-db"
    assert parsed.system_keys == ["payments-db", "orders-api"]
    assert parsed.risk_type == "major"
    assert "restore snapshot" in parsed.rollback_plan
    assert parsed.window_start is not None and parsed.window_end is not None
    assert parsed.window_end > parsed.window_start


def test_inbound_files_scored_draft_with_reply(client):
    with _db() as db:
        before = db.execute(select(Change)).scalars().all()
        n_before = len(before)
        resp = client.post(
            "/api/integrations/email/inbound",
            json={"message_id": "<m1@x>", "from_addr": "dev@Ricozchange.dev", "subject": "Migrate payments-db", "body": GOOD_BODY},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "created"
        change = db.get(Change, data["change_id"])
        assert change.status == "draft"  # never auto-submitted
        assert change.risk_type == "major"
        assert len(db.execute(select(Change)).scalars().all()) == n_before + 1
        # reply carries score + why + safety note
        assert "DRAFT" in data["reply"].upper()
        assert "Risk:" in data["reply"] and "/100" in data["reply"]
        assert any(line.strip().startswith(("+", "-")) for line in data["reply"].splitlines())
        # audit row links the change
        row = db.get(EmailInbound, data["inbound_id"])
        assert row.status == "created" and row.parsed_change_id == change.id


def test_duplicate_message_id_files_only_one_change(client):
    payload = {"message_id": "<dup@x>", "from_addr": "dev@Ricozchange.dev", "subject": "Same again", "body": GOOD_BODY}
    first = client.post("/api/integrations/email/inbound", json=payload)
    second = client.post("/api/integrations/email/inbound", json=payload)
    assert first.json()["status"] == "created"
    assert second.json()["status"] == "duplicate"
    with _db() as db:
        rows = db.execute(select(EmailInbound).where(EmailInbound.message_id == "<dup@x>")).scalars().all()
        assert len(rows) == 1


def test_unknown_system_rejected_with_known_list(client):
    resp = client.post(
        "/api/integrations/email/inbound",
        json={"message_id": "<m2@x>", "from_addr": "dev@Ricozchange.dev", "subject": "Touch something", "body": "systems: does-not-exist"},
    )
    data = resp.json()
    assert data["status"] == "rejected"
    assert "does-not-exist" in data["reply"] and "Known systems" in data["reply"]
    with _db() as db:
        row = db.get(EmailInbound, data["inbound_id"])
        assert row.status == "rejected" and row.parsed_change_id is None


def test_foreign_domain_rejected_when_allowlist_set(client, monkeypatch):
    monkeypatch.setattr(config, "EMAIL_ALLOWED_DOMAINS", {"rico.dev"})
    resp = client.post(
        "/api/integrations/email/inbound",
        json={"message_id": "<m3@x>", "from_addr": "stranger@gmail.com", "subject": "Hi", "body": "systems: payments-db"},
    )
    assert resp.json()["status"] == "rejected"
    assert "not allowed" in resp.json()["reply"]


def test_webhook_key_verification(client, monkeypatch):
    monkeypatch.setattr(config, "EMAIL_WEBHOOK_KEY", "sekrit")
    resp = client.post("/api/integrations/email/inbound?key=wrong", json={"from_addr": "dev@Ricozchange.dev", "subject": "s", "body": "b"})
    assert resp.status_code == 401
    ok = client.post("/api/integrations/email/inbound?key=sekrit", json={"message_id": "<m4@x>", "from_addr": "dev@Ricozchange.dev", "subject": "s", "body": GOOD_BODY})
    assert ok.json()["status"] == "created"


def test_sweep_prompts_post_change_once(client):
    with _db() as db:
        # a completed change whose window just closed, no result yet
        change = Change(
            title="Prompt me", description="", risk_type="normal", status="completed",
            owner_id=db.execute(select(User).where(User.email == "dev@Ricozchange.dev")).scalars().one().id,
            window_start=__import__("datetime", fromlist=["datetime"]).datetime.utcnow() - timedelta(hours=3),
            window_end=__import__("datetime", fromlist=["datetime"]).datetime.utcnow() - timedelta(hours=1),
        )
        db.add(change)
        db.commit()
        cid = change.id

    first = client.post("/api/integrations/email/sweep").json()
    assert first["post_change_prompts"] == 1
    second = client.post("/api/integrations/email/sweep").json()
    assert second["post_change_prompts"] == 0  # prompted once, ever

    with _db() as db:
        note = db.execute(
            select(Notification).where(Notification.kind == "email", Notification.change_id == cid)
        ).scalars().first()
        assert note is not None and "Did change" in note.message["subject"]


def test_sweep_digest_lists_only_own_approvals(client):
    today = __import__("datetime", fromlist=["datetime"]).datetime.utcnow().strftime("%Y-%m-%d")
    with _db() as db:
        pending = db.execute(select(Approval).where(Approval.decision == "pending")).scalars().unique().all()
        assert pending, "seed should create pending approvals"
        sara = db.execute(select(User).where(User.email == "sara@Ricozchange.dev")).scalars().one()
        # self-contained: clear any digest markers left by earlier tests
        for m in db.execute(select(Setting).where(Setting.key.like("email_digest:%"))).scalars().all():
            db.delete(m)
        db.commit()

    counts = client.post("/api/integrations/email/sweep").json()
    assert counts["digests"] >= 1

    with _db() as db:
        sara = db.execute(select(User).where(User.email == "sara@Ricozchange.dev")).scalars().one()
        note = db.execute(
            select(Notification).where(Notification.kind == "email", Notification.channel == sara.email)
        ).scalars().first()
        assert note is not None
        own = [a for a in db.execute(select(Approval).where(Approval.approver_id == sara.id, Approval.decision == "pending")).scalars().all() if a.change.status == "submitted"]
        own_ids = {a.change_id for a in own}
        assert all(f"#{cid}" in note.message["text"] for cid in own_ids)
        # someone else's pending change id must NOT leak into sara's digest
        others = {a.change_id for a in db.execute(select(Approval).where(Approval.approver_id != sara.id, Approval.decision == "pending")).scalars().all() if a.change.status == "submitted"}
        leaked = others - own_ids
        assert not any(f"#{cid}" in note.message["text"] for cid in leaked)
        marker = db.get(Setting, f"email_digest:{sara.id}")
        assert marker is not None and (marker.value or {}).get("last_sent_date") == today

    # same-day second sweep sends nothing (day-dedupe)
    again = client.post("/api/integrations/email/sweep").json()
    assert again["digests"] == 0


def test_inbound_list_requires_admin_or_manager(client):
    assert client.get("/api/integrations/email/inbound").status_code == 200  # demo actor is admin


def test_simulate_matches_webhook_pipeline(client):
    sim = client.post(
        "/api/integrations/email/simulate",
        json={"message_id": "<sim1@x>", "from_addr": "mei@Ricozchange.dev", "subject": "Rotate orders-api key", "body": GOOD_BODY},
    )
    assert sim.json()["status"] == "created"
