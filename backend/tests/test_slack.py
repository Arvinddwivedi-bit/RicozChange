"""Phase-2 week-2 tests: real Slack integration.

Covers signature verification, OAuth exchange, Block Kit conversion, DM
delivery (mocked HTTP), interaction handling (approve/reject, idempotency,
wrong-approver, autolink), and outage resilience.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import pytest
from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["AUTO_SEED"] = "1"
os.environ.pop("ANTHROPIC_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

from ricozchange import db as dbmod  # noqa: E402
from ricozchange import slack_app  # noqa: E402
from ricozchange.auth import require_actor  # noqa: E402
from ricozchange.main import app  # noqa: E402
from ricozchange.models import Approval, Notification, Setting, User  # noqa: E402

SECRET = "test-signing-secret"


@pytest.fixture()
def client():
    dbmod.init_db()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(require_actor, None)


@pytest.fixture()
def slack_db():
    """A DB session with Slack 'installed' (test credentials in settings)."""
    db = dbmod.SessionLocal()
    slack_app.save_settings(
        db, bot_token="xoxb-test-token", signing_secret=SECRET, team_id="T123", team_name="Test WS"
    )
    db.commit()
    yield db
    row = db.get(Setting, slack_app.SETTINGS_KEY)
    if row:
        db.delete(row)
        db.commit()
    db.close()


def _sign(secret: str, body: bytes, ts: str) -> str:
    basestring = f"v0:{ts}:{body.decode()}"
    return "v0=" + hmac.new(secret.encode(), basestring.encode(), hashlib.sha256).hexdigest()


def _submit_risky_change(client) -> dict:
    resp = client.post(
        "/api/changes",
        json={
            "title": "Slack flow test change",
            "risk_type": "major",
            "system_keys": ["payments-db", "payments-api"],
            "window_start": "2026-12-10T10:00",
            "window_end": "2026-12-10T13:00",
        },
    )
    assert resp.status_code == 201, resp.text
    change = resp.json()
    submitted = client.post(f"/api/changes/{change['id']}/submit").json()
    assert submitted["fast_tracked"] is False
    return change


def _link_approvers_slack(db: Session) -> None:
    """Link every seeded approver (Sara, Arjun, and Priya the admin) — submit
    queues an outbox row per eligible approver, so all three need slack_ids."""
    for email, sid in (
        ("sara@Ricozchange.dev", "U-SARA"),
        ("arjun@Ricozchange.dev", "U-ARJUN"),
        ("priya@Ricozchange.dev", "U-PRIYA"),
    ):
        u = db.execute(select(User).where(User.email == email)).scalars().one()
        u.slack_id = sid
    db.commit()


def _as_user(email: str) -> None:
    def dep(db: Session = Depends(dbmod.get_db)):
        return db.execute(select(User).where(User.email == email)).scalars().one()

    app.dependency_overrides[require_actor] = dep


def _fake_api_calls(calls: list):
    EMAILS = {"U-SARA": "sara@Ricozchange.dev", "U-ARJUN": "arjun@Ricozchange.dev", "U-NEW-SARA": "sara@Ricozchange.dev"}

    def fake_api_call(db, method, fields):
        calls.append((method, fields))
        if method == "chat.postMessage":
            return {"ok": True, "channel": fields["channel"], "ts": "1700000000.000100"}
        if method == "users.info":
            return {"ok": True, "user": {"profile": {"email": EMAILS.get(fields.get("user", ""), "")}}}
        return {"ok": True}

    return fake_api_call


# ---------- unit: signature verification ----------

def test_verify_signature_accepts_valid():
    body = b"payload=%7B%22ok%22%3Atrue%7D"
    ts = str(int(time.time()))
    assert slack_app.verify_signature(SECRET, ts, body, _sign(SECRET, body, ts)) is True


def test_verify_signature_rejects_bad_secret():
    body = b"payload=%7B%22ok%22%3Atrue%7D"
    ts = str(int(time.time()))
    assert slack_app.verify_signature(SECRET, ts, body, _sign("wrong-secret", body, ts)) is False


def test_verify_signature_rejects_stale_timestamp():
    body = b"payload=x"
    ts = str(int(time.time()) - 4000)  # outside the ±5-minute replay window
    assert slack_app.verify_signature(SECRET, ts, body, _sign(SECRET, body, ts)) is False


def test_verify_signature_rejects_missing_parts():
    body = b"payload=x"
    ts = str(int(time.time()))
    assert slack_app.verify_signature("", ts, body, "v0=abc") is False
    assert slack_app.verify_signature(SECRET, "not-a-number", body, "v0=abc") is False


# ---------- unit: Block Kit conversion ----------

def test_to_block_kit_includes_why_and_buttons():
    demo_message = {
        "text": "Approval needed: change #1",
        "blocks": [
            {"type": "section", "text": "🔔 *Approval needed — change #1:* “X”"},
            {"type": "context", "fields": {"Risk": 100, "Class": "major"}},
            {"type": "risk_why", "items": [{"label": "major base", "points": 70}]},
            {"type": "actions", "actions": [
                {"action": "approve", "label": "✅ Approve", "style": "primary", "approval_id": 11},
                {"action": "reject", "label": "❌ Reject", "style": "danger", "approval_id": 11},
            ]},
        ],
    }
    blocks = slack_app.to_block_kit(demo_message)
    assert any(b["type"] == "actions" for b in blocks)
    why = next(b for b in blocks if "Why this score" in json.dumps(b))
    assert "major base (+70)" in json.dumps(why)
    buttons = next(b for b in blocks if b["type"] == "actions")
    assert [e["action_id"] for e in buttons["elements"]] == ["rc_approve", "rc_reject"]
    assert all(e["value"] == "11" for e in buttons["elements"])


def test_to_block_kit_omits_buttons_when_already_acted():
    demo_message = {
        "text": "x",
        "acted": True,
        "blocks": [
            {"type": "section", "text": "done"},
            {"type": "actions", "actions": [{"action": "approve", "label": "✅ Approve", "approval_id": 1}]},
        ],
    }
    blocks = slack_app.to_block_kit(demo_message)
    assert not any(b["type"] == "actions" for b in blocks)


# ---------- OAuth exchange (mocked HTTP) ----------

def test_exchange_oauth_code_success(monkeypatch):
    captured = {}

    def fake_post(url, token, fields):
        captured.update(url=url, fields=fields)
        return {"ok": True, "access_token": "xoxb-new", "team": {"id": "T1", "name": "WS"}}

    monkeypatch.setattr(slack_app, "_slack_form_post", fake_post)
    data = slack_app.exchange_oauth_code("the-code", "https://x/callback")
    assert data["access_token"] == "xoxb-new"
    assert captured["url"] == "https://slack.com/api/oauth.v2.access"
    assert captured["fields"]["code"] == "the-code"


def test_exchange_oauth_code_failure(monkeypatch):
    monkeypatch.setattr(slack_app, "_slack_form_post", lambda url, token, fields: {"ok": False, "error": "invalid_code"})
    with pytest.raises(RuntimeError):
        slack_app.exchange_oauth_code("bad", "https://x/callback")


# ---------- delivery (mocked HTTP) ----------

def test_deliver_pending_sends_dms_and_records_ts(client, slack_db, monkeypatch):
    db = slack_db
    _link_approvers_slack(db)
    calls: list = []
    monkeypatch.setattr(slack_app, "api_call", _fake_api_calls(calls))

    change = _submit_risky_change(client)
    notes = db.execute(select(Notification).where(Notification.change_id == change["id"])).scalars().all()
    assert notes, "outbox rows must exist"
    assert all(n.sent_at is not None for n in notes), "DMs must be delivered"
    assert all(n.slack_ts == "1700000000.000100" for n in notes)
    post_calls = [c for c in calls if c[0] == "chat.postMessage"]
    # deliver_pending drains every undelivered row — including the seeded
    # change #7's notes (retro-delivery) — so at least this change's DMs went out.
    assert len(post_calls) >= len(notes)
    blocks = json.loads(post_calls[0][1]["blocks"])
    assert any("Why this score" in json.dumps(b) for b in blocks)
    assert any(b["type"] == "actions" for b in blocks)


def test_deliver_pending_marks_error_without_slack_id(client, slack_db, monkeypatch):
    db = slack_db
    # Explicitly unmap: earlier tests in this module may have linked them.
    for u in db.execute(select(User).where(User.email.in_(["sara@Ricozchange.dev", "arjun@Ricozchange.dev", "priya@Ricozchange.dev"]))).scalars().all():
        u.slack_id = None
    db.commit()
    calls: list = []
    monkeypatch.setattr(slack_app, "api_call", _fake_api_calls(calls))

    change = _submit_risky_change(client)
    notes = db.execute(select(Notification).where(Notification.change_id == change["id"])).scalars().all()
    assert notes
    assert all(n.sent_at is None for n in notes)
    assert all("no linked slack_id" in (n.delivery_error or "") for n in notes)
    assert not [c for c in calls if c[0] == "chat.postMessage"]


def test_delivery_skipped_entirely_in_demo_mode(client, monkeypatch):
    """No bot token (not installed) → no Slack calls at all; outbox behaves as before."""
    calls: list = []
    monkeypatch.setattr(slack_app, "api_call", _fake_api_calls(calls))
    _submit_risky_change(client)
    assert calls == []


# ---------- outage resilience ----------

def test_submission_survives_slack_outage(client, slack_db, monkeypatch):
    db = slack_db
    _link_approvers_slack(db)

    def network_down(db, method, fields):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(slack_app, "api_call", network_down)
    change = _submit_risky_change(client)
    detail = client.get(f"/api/changes/{change['id']}").json()
    assert detail["status"] == "submitted"  # workflow unaffected


def test_outage_marks_delivery_failed_web_approval_still_works(client, slack_db, monkeypatch):
    db = slack_db
    _link_approvers_slack(db)

    def fail_post(db, method, fields):
        return {"ok": False, "error": "network: connection refused"}

    monkeypatch.setattr(slack_app, "api_call", fail_post)
    change = _submit_risky_change(client)
    notes = db.execute(select(Notification).where(Notification.change_id == change["id"])).scalars().all()
    assert notes and all("network" in (n.delivery_error or "") for n in notes)

    # Web fallback as a *non-owner* approver (the demo actor owns the change,
    # and the owner cannot approve their own change — by design).
    note = _note_for(db, change["id"])
    approval = db.get(Approval, note.approval_id)
    approver_email = db.get(User, approval.approver_id).email
    _as_user(approver_email)
    acted = client.post(
        f"/api/notifications/{note.id}/act", json={"action": "approve", "comment": "web fallback"}
    )
    assert acted.status_code == 200
    detail = client.get(f"/api/changes/{change['id']}").json()
    assert detail["status"] == "approved"


# ---------- interactions (service level) ----------

def _note_for(db: Session, change_id: int, approver_email: str = "sara@Ricozchange.dev") -> Notification | None:
    """The unacted outbox row for one specific approver's approval."""
    rows = db.execute(
        select(Notification).where(Notification.change_id == change_id)
    ).scalars().all()
    for n in rows:
        approval = db.get(Approval, n.approval_id) if n.approval_id else None
        if approval is not None and approval.approver and approval.approver.email == approver_email:
            if not n.acted:
                return n
    return None


def test_interaction_approve_resolves_change_any_of(client, slack_db, monkeypatch):
    db = slack_db
    _link_approvers_slack(db)
    monkeypatch.setattr(slack_app, "api_call", _fake_api_calls([]))

    change = _submit_risky_change(client)
    with dbmod.SessionLocal() as db2:  # see rows committed by the request
        note = _note_for(db2, change["id"])
        note.slack_channel = "D-SARA"
        note.slack_ts = "1700000000.000100"
        db2.commit()
        approval_id = note.approval_id

    # Sara acts as the assigned approver on her message.
    payload = {
        "actions": [{"action_id": "rc_approve", "value": str(approval_id)}],
        "user": {"id": "U-SARA", "username": "sara"},
        "message": {"channel": "D-SARA", "ts": "1700000000.000100"},
    }
    with dbmod.SessionLocal() as db3:
        monkeypatch.setattr(slack_app, "api_call", _fake_api_calls([]))
        result = slack_app.handle_interaction(db3, payload)
        db3.commit()
    assert "approved" in result["text"]

    detail = client.get(f"/api/changes/{change['id']}").json()
    assert detail["status"] == "approved"  # any-of: one decision resolves
    assert all(a["decision"] != "pending" for a in detail["approvals"])


def test_interaction_is_idempotent_on_replay(client, slack_db, monkeypatch):
    db = slack_db
    _link_approvers_slack(db)
    monkeypatch.setattr(slack_app, "api_call", _fake_api_calls([]))

    change = _submit_risky_change(client)
    with dbmod.SessionLocal() as db2:
        note = _note_for(db2, change["id"])
        note.slack_channel, note.slack_ts = "D-SARA", "1700000000.000100"
        db2.commit()

    payload = {
        "actions": [{"action_id": "rc_approve", "value": ""}],
        "user": {"id": "U-SARA"},
        "message": {"channel": "D-SARA", "ts": "1700000000.000100"},
    }
    with dbmod.SessionLocal() as db3:
        monkeypatch.setattr(slack_app, "api_call", _fake_api_calls([]))
        first = slack_app.handle_interaction(db3, payload)
        db3.commit()
    assert "approved" in first["text"]

    with dbmod.SessionLocal() as db4:
        second = slack_app.handle_interaction(db4, payload)  # replayed click
        db4.commit()
    assert second.get("response_type") == "ephemeral"
    assert "already resolved" in second["text"]


def test_interaction_wrong_approver_gets_ephemeral(client, slack_db, monkeypatch):
    db = slack_db
    _link_approvers_slack(db)
    monkeypatch.setattr(slack_app, "api_call", _fake_api_calls([]))

    change = _submit_risky_change(client)
    with dbmod.SessionLocal() as db2:
        note = _note_for(db2, change["id"])
        note.slack_channel, note.slack_ts = "D-SARA", "1700000000.000100"
        db2.commit()

    payload = {
        "actions": [{"action_id": "rc_approve", "value": ""}],
        "user": {"id": "U-DEV"},  # an engineer, not an assigned approver
        "message": {"channel": "D-SARA", "ts": "1700000000.000100"},
    }
    with dbmod.SessionLocal() as db3:
        result = slack_app.handle_interaction(db3, payload)
        db3.commit()
    assert result.get("response_type") == "ephemeral"
    assert "isn't linked" in result["text"]


def test_interaction_autolinks_by_email(client, slack_db, monkeypatch):
    """Unmapped Slack user whose workspace email matches gets auto-linked."""
    db = slack_db
    calls: list = []
    monkeypatch.setattr(slack_app, "api_call", _fake_api_calls(calls))

    change = _submit_risky_change(client)
    with dbmod.SessionLocal() as db2:
        note = _note_for(db2, change["id"])
        approval_id = note.approval_id
        approver = db2.get(User, db2.get(Approval, approval_id).approver_id)
        approver.slack_id = None  # unmap — force the autolink path
        note.slack_channel, note.slack_ts = "D-SARA", "1700000000.000100"
        db2.commit()

    payload = {
        "actions": [{"action_id": "rc_approve", "value": str(approval_id)}],
        "user": {"id": "U-NEW-SARA"},
        "message": {"channel": "D-SARA", "ts": "1700000000.000100"},
    }
    with dbmod.SessionLocal() as db3:
        monkeypatch.setattr(slack_app, "api_call", _fake_api_calls(calls))
        result = slack_app.handle_interaction(db3, payload)
        db3.commit()
    assert "approved" in result["text"]
    assert any(c[0] == "users.info" for c in calls), "autolink must look up the workspace email"
    with dbmod.SessionLocal() as db4:
        sara = db4.execute(select(User).where(User.email == "sara@Ricozchange.dev")).scalars().one()
        assert sara.slack_id == "U-NEW-SARA"


# ---------- interactions (HTTP level: signature + status) ----------

def test_interactions_endpoint_rejects_bad_signature(client, slack_db):
    body = urlencode({"payload": json.dumps({"type": "block_actions"})}).encode()
    ts = str(int(time.time()))
    resp = client.post(
        "/api/slack/interactions",
        content=body,
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "X-Slack-Signature-Timestamp": ts,
                 "X-Slack-Signature": _sign("wrong", body, ts)},
    )
    assert resp.status_code == 401


def test_interactions_endpoint_accepts_valid_signature(client, slack_db):
    body = urlencode({"payload": json.dumps({"type": "block_actions", "actions": []})}).encode()
    ts = str(int(time.time()))
    resp = client.post(
        "/api/slack/interactions",
        content=body,
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "X-Slack-Signature-Timestamp": ts,
                 "X-Slack-Signature": _sign(SECRET, body, ts)},
    )
    assert resp.status_code == 200  # unknown/empty action answered, not an auth failure


def test_slack_status_reports_demo_mode(client):
    data = client.get("/api/integrations/slack/status").json()
    assert data["connected"] is False


def test_admin_can_link_and_unlink_slack_id(client):
    resp = client.post("/api/users/4/slack-link", json={"slack_id": "U-DEV-LINK"})
    assert resp.status_code == 200
    assert resp.json()["slack_id"] == "U-DEV-LINK"
    clash = client.post("/api/users/5/slack-link", json={"slack_id": "U-DEV-LINK"})
    assert clash.status_code == 409
    unlink = client.post("/api/users/4/slack-link", json={"slack_id": ""})
    assert unlink.status_code == 200 and unlink.json()["slack_id"] is None
