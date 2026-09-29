"""v0.3 week-3 tests: Microsoft Teams approval cards on the Bot Framework.

Mirrors test_slack.py: JWT verification (RS256 with a real test key), Adaptive
Card conversion, proactive delivery (mocked HTTP), interaction handling
(approve/reject, idempotency, wrong-approver, Graph autolink),
conversationUpdate install, and outage resilience. The outbox stays the source
of truth; kind="teams" mirror rows carry the Teams transport state.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key
from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["AUTO_SEED"] = "1"
os.environ.pop("ANTHROPIC_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

from ricozchange import config  # noqa: E402
from ricozchange import db as dbmod  # noqa: E402
from ricozchange import teams_app  # noqa: E402
from ricozchange.auth import require_actor  # noqa: E402
from ricozchange.main import app  # noqa: E402
from ricozchange.models import Approval, Notification, Setting, User  # noqa: E402

APP_ID = "00000000-0000-0000-0000-000000000001"
SERVICE_URL = "https://smba.trafficmanager.net/amer/"
KEY_ID = "test-kid"

# One RSA key for the whole module; the JWKS served by the fake metadata.
_RSA = generate_private_key(public_exponent=65537, key_size=2048)
_JWK = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(_RSA.public_key()))
_JWK["kid"] = KEY_ID
_JWK["use"] = "sig"


def _mint_token(audience: str = APP_ID, issuer: str = teams_app.BOT_ISSUER, **claims) -> str:
    now = int(time.time())
    payload = {"aud": audience, "iss": issuer, "iat": now - 5, "nbf": now - 5, "exp": now + 300, **claims}
    return jwt.encode(payload, _RSA, algorithm="RS256", headers={"kid": KEY_ID})


@pytest.fixture()
def client():
    dbmod.init_db()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(require_actor, None)


@pytest.fixture()
def teams_db():
    """A DB session with the Teams bot 'installed' (test credentials)."""
    db = dbmod.SessionLocal()
    teams_app.save_settings(
        db,
        app_id=APP_ID,
        app_password="test-secret",
        service_url=SERVICE_URL,
        bot_id="bot-1",
        tenant_id="tenant-1",
        installed_at="2026-09-29T00:00:00",
        openid_config={"issuer": teams_app.BOT_ISSUER, "jwks": [_JWK]},
    )
    db.commit()
    yield db
    row = db.get(Setting, teams_app.SETTINGS_KEY)
    if row:
        db.delete(row)
        db.commit()
    db.close()


@pytest.fixture()
def bot_creds(monkeypatch):
    monkeypatch.setattr(config, "TEAMS_APP_ID", APP_ID)
    monkeypatch.setattr(config, "TEAMS_APP_PASSWORD", "test-secret")


def _link_approvers_teams(db: Session) -> None:
    for email, tid in (
        ("sara@Ricozchange.dev", "aad-sara"),
        ("arjun@Ricozchange.dev", "aad-arjun"),
        ("priya@Ricozchange.dev", "aad-priya"),
    ):
        u = db.execute(select(User).where(User.email == email)).scalars().one()
        u.teams_id = tid
    db.commit()


def _submit_risky_change(client) -> dict:
    resp = client.post(
        "/api/changes",
        json={
            "title": "Teams flow test change",
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


def _fake_transport(calls: list):
    """Replaces _post_json: token + proactive conversation + send + Graph."""

    def fake(url, token, payload=None, form=None, method=None):
        calls.append({"url": url.split("?")[0], "payload": payload, "form": form})
        if url == teams_app.TOKEN_URL:
            return {"access_token": "bf-token", "expires_in": 3600}
        if url == teams_app.GRAPH_TOKEN_URL:
            return {"access_token": "graph-token"}
        if "/v3/conversations" in url and url.endswith("/activities"):
            return {"id": "act-100"}
        if "/v3/conversations" in url:
            return {"id": f"conv-{payload['members'][0]['id']}"}
        if url == teams_app.GRAPH_ME_URL.format(aad_id="aad-new-sara"):
            return {"mail": "sara@Ricozchange.dev"}
        return {}

    return fake


def _as_user(email: str) -> None:
    def dep(db: Session = Depends(dbmod.get_db)):
        return db.execute(select(User).where(User.email == email)).scalars().one()

    app.dependency_overrides[require_actor] = dep


# ---------- JWT verification ----------

def test_verify_accepts_valid_bot_token(client, teams_db, bot_creds):
    aud = teams_app.verify_bot_token(f"Bearer {_mint_token()}", teams_db)
    assert aud == APP_ID


def test_verify_rejects_wrong_audience(client, teams_db, bot_creds):

    with pytest.raises(ValueError):
        teams_app.verify_bot_token(f"Bearer {_mint_token(audience='not-our-app')}", teams_db)


def test_verify_rejects_wrong_signing_key(client, teams_db, bot_creds):

    other = generate_private_key(public_exponent=65537, key_size=2048)
    now = int(time.time())
    token = jwt.encode(
        {"aud": APP_ID, "iss": teams_app.BOT_ISSUER, "exp": now + 300},
        other, algorithm="RS256", headers={"kid": KEY_ID},
    )
    with pytest.raises(ValueError):
        teams_app.verify_bot_token(f"Bearer {token}", teams_db)


def test_verify_rejects_expired_token(client, teams_db, bot_creds):

    token = _mint_token(exp=int(time.time()) - 3600)
    with pytest.raises(ValueError):
        teams_app.verify_bot_token(f"Bearer {token}", teams_db)


def test_verify_rejects_missing_header(client, teams_db, bot_creds):

    with pytest.raises(ValueError):
        teams_app.verify_bot_token("", teams_db)


def test_verify_requires_configured_app_id(client, teams_db, monkeypatch):
    monkeypatch.setattr(config, "TEAMS_APP_ID", "")
    s = teams_app.get_settings(teams_db)
    s.pop("app_id", None)
    monkeypatch.setattr(teams_app, "get_settings", lambda db: s)

    with pytest.raises(ValueError):
        teams_app.verify_bot_token(f"Bearer {_mint_token()}", teams_db)


# ---------- card conversion ----------

def test_to_adaptive_card_includes_why_and_buttons():
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
    card = teams_app.to_adaptive_card(demo_message)
    assert card["type"] == "AdaptiveCard"
    assert any("Why this score" in b.get("text", "") for b in card["body"])
    assert [a["data"]["action"] for a in card["actions"]] == ["rc_approve", "rc_reject"]
    assert all(a["data"]["approval_id"] == "11" for a in card["actions"])


def test_to_adaptive_card_omits_buttons_when_already_acted():
    card = teams_app.to_adaptive_card({
        "text": "x", "acted": True,
        "blocks": [
            {"type": "section", "text": "done"},
            {"type": "actions", "actions": [{"action": "approve", "label": "✅", "approval_id": 1}]},
        ],
    })
    assert card["actions"] == []


# ---------- delivery ----------

def test_deliver_pending_sends_cards_and_records_ids(client, teams_db, monkeypatch):
    db = teams_db
    _link_approvers_teams(db)
    calls: list = []
    monkeypatch.setattr(teams_app, "_post_json", _fake_transport(calls))

    change = _submit_risky_change(client)
    notes = db.execute(
        select(Notification).where(Notification.change_id == change["id"], Notification.kind == "teams")
    ).scalars().all()
    assert notes, "teams mirror rows must exist"
    assert all(n.sent_at is not None for n in notes)
    assert all(n.teams_conversation_id and n.teams_activity_id == "act-100" for n in notes)
    sends = [c for c in calls if c["url"].endswith("/activities")]
    assert len(sends) >= len(notes)
    card = sends[0]["payload"]["attachments"][0]["content"]
    assert card["type"] == "AdaptiveCard"
    assert any("Why this score" in b.get("text", "") for b in card["body"])


def test_deliver_pending_marks_error_without_teams_id(client, teams_db, monkeypatch):
    db = teams_db
    for u in db.execute(select(User).where(User.email.in_(
        ["sara@Ricozchange.dev", "arjun@Ricozchange.dev", "priya@Ricozchange.dev"]
    ))).scalars().all():
        u.teams_id = None
    db.commit()
    calls: list = []
    monkeypatch.setattr(teams_app, "_post_json", _fake_transport(calls))

    change = _submit_risky_change(client)
    notes = db.execute(
        select(Notification).where(Notification.change_id == change["id"], Notification.kind == "teams")
    ).scalars().all()
    assert notes
    assert all(n.sent_at is None for n in notes)
    assert all("no linked teams_id" in (n.delivery_error or "") for n in notes)
    assert not [c for c in calls if c["url"].endswith("/activities")]


def test_delivery_skipped_entirely_in_demo_mode(client, monkeypatch):
    calls: list = []
    monkeypatch.setattr(teams_app, "_post_json", _fake_transport(calls))
    _submit_risky_change(client)
    assert not [c for c in calls if c["url"].startswith(SERVICE_URL)]


# ---------- outage resilience ----------

def test_submission_survives_teams_outage(client, teams_db, monkeypatch):
    def network_down(url, token, payload=None, form=None, method=None):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(teams_app, "_post_json", network_down)
    change = _submit_risky_change(client)
    detail = client.get(f"/api/changes/{change['id']}").json()
    assert detail["status"] == "submitted"  # workflow unaffected


def test_outage_marks_delivery_failed_web_approval_still_works(client, teams_db, monkeypatch):
    db = teams_db
    _link_approvers_teams(db)

    def fail(url, token, payload=None, form=None, method=None):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(teams_app, "_post_json", fail)
    change = _submit_risky_change(client)
    notes = db.execute(
        select(Notification).where(Notification.change_id == change["id"], Notification.kind == "teams")
    ).scalars().all()
    assert notes and all("network" in (n.delivery_error or "") for n in notes)

    # Web fallback as a non-owner approver.
    note = _note_for(db, change["id"])
    approval = db.get(Approval, note.approval_id)
    _as_user(db.get(User, approval.approver_id).email)
    acted = client.post(
        f"/api/notifications/{note.id}/act", json={"action": "approve", "comment": "web fallback"}
    )
    assert acted.status_code == 200
    detail = client.get(f"/api/changes/{change['id']}").json()
    assert detail["status"] == "approved"


def test_teams_sweep_retries_then_emails_fallback(client, teams_db, monkeypatch):
    db = teams_db
    _link_approvers_teams(db)

    def fail(url, token, payload=None, form=None, method=None):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(teams_app, "_post_json", fail)
    change = _submit_risky_change(client)
    db.expire_all()
    notes = db.execute(
        select(Notification).where(Notification.change_id == change["id"], Notification.kind == "teams")
    ).scalars().all()
    assert notes and all(n.delivery_error for n in notes)

    # Teams recovers: the sweep retries delivery and wins. The sweep also
    # drains older undelivered rows from earlier tests (shared seeded DB), so
    # assert on this change's notes, like test_slack.py does.
    monkeypatch.setattr(teams_app, "_post_json", _fake_transport([]))
    counts = teams_app.run_teams_sweep(db)
    assert counts["teams_delivered"] >= len(notes)
    assert all(n.sent_at is not None for n in notes)


def test_teams_sweep_email_fallback_when_mapped_user_missing(client, teams_db, monkeypatch):
    """Cards that can never go out (approver unmapped) fall back to email once."""
    db = teams_db
    for u in db.execute(select(User).where(User.email == "sara@Ricozchange.dev")).scalars().all():
        u.teams_id = None
    db.commit()
    monkeypatch.setattr(teams_app, "_post_json", _fake_transport([]))
    change = _submit_risky_change(client)
    teams_app.run_teams_sweep(db)
    db.expire_all()
    sara = db.execute(select(User).where(User.email == "sara@Ricozchange.dev")).scalars().one()
    fallbacks = db.execute(
        select(Notification).where(Notification.kind == "email", Notification.channel == sara.email)
    ).scalars().all()
    assert len(fallbacks) >= 1, "unmapped approver must get an email fallback"
    # Running the sweep again must not duplicate the fallback email
    # (each failed note gets exactly one covered fallback, ever).
    before = len(fallbacks)
    teams_app.run_teams_sweep(db)
    db.expire_all()
    after = db.execute(
        select(Notification).where(Notification.kind == "email", Notification.channel == sara.email)
    ).scalars().all()
    assert len(after) == before


# ---------- interactions (service level) ----------

def _note_for(db: Session, change_id: int, approver_email: str = "sara@Ricozchange.dev") -> Notification | None:
    rows = db.execute(
        select(Notification).where(Notification.change_id == change_id, Notification.kind == "teams")
    ).scalars().all()
    for n in rows:
        approval = db.get(Approval, n.approval_id) if n.approval_id else None
        if approval is not None and approval.approver and approval.approver.email == approver_email:
            if not n.acted:
                return n
    return None


def test_interaction_approve_resolves_change_any_of(client, teams_db, monkeypatch):
    db = teams_db
    _link_approvers_teams(db)
    monkeypatch.setattr(teams_app, "_post_json", _fake_transport([]))

    change = _submit_risky_change(client)
    with dbmod.SessionLocal() as db2:
        note = _note_for(db2, change["id"])
        note.teams_conversation_id = "conv-aad-sara"
        note.teams_activity_id = "act-100"
        db2.commit()
        approval_id = note.approval_id

    with dbmod.SessionLocal() as db3:
        monkeypatch.setattr(teams_app, "_post_json", _fake_transport([]))
        result = teams_app.handle_interaction(
            db3, value={"action": "rc_approve", "approval_id": str(approval_id)},
            from_id="aad-sara", conversation_id="conv-aad-sara", activity_id="act-200",
        )
        db3.commit()
    assert "approved" in result["text"]

    detail = client.get(f"/api/changes/{change['id']}").json()
    assert detail["status"] == "approved"  # any-of: one decision resolves
    assert all(a["decision"] != "pending" for a in detail["approvals"])


def test_interaction_is_idempotent_on_replay(client, teams_db, monkeypatch):
    db = teams_db
    _link_approvers_teams(db)
    monkeypatch.setattr(teams_app, "_post_json", _fake_transport([]))

    change = _submit_risky_change(client)
    with dbmod.SessionLocal() as db2:
        note = _note_for(db2, change["id"])
        note.teams_conversation_id, note.teams_activity_id = "conv-aad-sara", "act-100"
        db2.commit()

    payload = {"action": "rc_approve", "approval_id": ""}  # replay lost the value; route falls back to the conversation id
    with dbmod.SessionLocal() as db3:
        first = teams_app.handle_interaction(db3, value=payload, from_id="aad-sara",
                                             conversation_id="conv-aad-sara", activity_id="act-200")
        db3.commit()
    assert "approved" in first["text"]

    with dbmod.SessionLocal() as db4:
        second = teams_app.handle_interaction(db4, value=payload, from_id="aad-sara",
                                              conversation_id="conv-aad-sara", activity_id="act-201")
        db4.commit()
    assert "already resolved" in second["text"]


def test_interaction_wrong_approver_gets_fallback(client, teams_db, monkeypatch):
    db = teams_db
    _link_approvers_teams(db)
    monkeypatch.setattr(teams_app, "_post_json", _fake_transport([]))

    change = _submit_risky_change(client)
    with dbmod.SessionLocal() as db2:
        note = _note_for(db2, change["id"])
        note.teams_conversation_id = "conv-aad-sara"
        db2.commit()

    with dbmod.SessionLocal() as db3:
        result = teams_app.handle_interaction(db3, value={"action": "rc_approve"}, from_id="aad-dev",
                                              conversation_id="conv-aad-sara")
        db3.commit()
    assert "isn't linked" in result["text"]


def test_interaction_autolinks_by_graph(client, teams_db, monkeypatch):
    db = teams_db
    calls: list = []
    monkeypatch.setattr(teams_app, "_post_json", _fake_transport(calls))

    change = _submit_risky_change(client)
    with dbmod.SessionLocal() as db2:
        note = _note_for(db2, change["id"])
        approval_id = note.approval_id
        approver = db2.get(User, db2.get(Approval, approval_id).approver_id)
        approver.teams_id = None  # unmap — force the autolink path
        note.teams_conversation_id = "conv-aad-sara"
        db2.commit()

    with dbmod.SessionLocal() as db3:
        monkeypatch.setattr(teams_app, "_post_json", _fake_transport(calls))
        result = teams_app.handle_interaction(db3, value={"action": "rc_approve", "approval_id": str(approval_id)},
                                              from_id="aad-new-sara", conversation_id="conv-aad-sara")
        db3.commit()
    assert "approved" in result["text"]
    assert any(c["url"] == teams_app.GRAPH_ME_URL.format(aad_id="aad-new-sara") for c in calls), \
        "autolink must look up the directory email"
    with dbmod.SessionLocal() as db4:
        sara = db4.execute(select(User).where(User.email == "sara@Ricozchange.dev")).scalars().one()
        assert sara.teams_id == "aad-new-sara"


# ---------- HTTP level ----------

def test_interactions_endpoint_rejects_bad_token(client, teams_db, bot_creds):
    resp = client.post(
        "/api/teams/interactions",
        content=json.dumps({"type": "message"}).encode(),
        headers={"Authorization": "Bearer not-a-jwt", "Content-Type": "application/json"},
    )
    assert resp.status_code == 401


def test_interactions_endpoint_accepts_valid_token_and_install(client, teams_db, bot_creds):
    # conversationUpdate completes the install (serviceUrl remembered).
    token = _mint_token()
    update = {
        "type": "conversationUpdate",
        "serviceUrl": "https://smba.trafficmanager.net/emea/",
        "membersAdded": [{"id": "aad-sara"}],
        "recipient": {"id": "bot-9"},
        "channelData": {"tenant": {"id": "tenant-9"}},
    }
    ok = client.post(
        "/api/teams/interactions", content=json.dumps(update).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    assert ok.status_code == 200
    with dbmod.SessionLocal() as db:
        s = teams_app.get_settings(db)
        assert s.get("service_url") == "https://smba.trafficmanager.net/emea"
        assert s.get("bot_id") == "bot-9"
        assert s.get("tenant_id") == "tenant-9"


def test_interactions_endpoint_rejects_garbage_body(client, teams_db, bot_creds):
    token = _mint_token()
    resp = client.post(
        "/api/teams/interactions", content=b"not json{",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    assert resp.status_code == 400


def test_teams_status_shape(client, teams_db, bot_creds):
    data = client.get("/api/integrations/teams/status").json()
    assert data["connected"] is True
    assert data["client_configured"] is True


def test_teams_status_demo_mode(client):
    data = client.get("/api/integrations/teams/status").json()
    assert data["connected"] is False
    assert data["client_configured"] is False
    assert "TEAMS_APP_ID" in data["setup"]


def test_admin_can_link_and_unlink_teams_id(client):
    resp = client.post("/api/users/4/teams-link", json={"teams_id": "aad-link-1"})
    assert resp.status_code == 200
    assert resp.json()["teams_id"] == "aad-link-1"
    clash = client.post("/api/users/5/teams-link", json={"teams_id": "aad-link-1"})
    assert clash.status_code == 409
    unlink = client.post("/api/users/4/teams-link", json={"teams_id": ""})
    assert unlink.status_code == 200 and unlink.json()["teams_id"] is None


# ---------- the PRD's demo chain: push -> auto-change -> Teams approval ----------

def test_any_of_second_card_superseded_message(client, teams_db, monkeypatch):
    """Both approvers have cards; one approves; the other's click is a no-op."""
    db = teams_db
    _link_approvers_teams(db)
    monkeypatch.setattr(teams_app, "_post_json", _fake_transport([]))

    change = _submit_risky_change(client)
    with dbmod.SessionLocal() as db2:
        sara_note = _note_for(db2, change["id"], "sara@Ricozchange.dev")
        arjun_note = _note_for(db2, change["id"], "arjun@Ricozchange.dev")
        assert sara_note and arjun_note
        sara_id, arjun_id = sara_note.approval_id, arjun_note.approval_id

    with dbmod.SessionLocal() as db3:
        teams_app.handle_interaction(db3, value={"action": "rc_approve", "approval_id": str(sara_id)},
                                     from_id="aad-sara", conversation_id="conv-aad-sara")
        db3.commit()
    with dbmod.SessionLocal() as db4:
        late = teams_app.handle_interaction(db4, value={"action": "rc_reject", "approval_id": str(arjun_id)},
                                            from_id="aad-arjun", conversation_id="conv-aad-arjun")
        db4.commit()
    assert "already resolved" in late["text"]
    detail = client.get(f"/api/changes/{change['id']}").json()
    assert detail["status"] == "approved"
