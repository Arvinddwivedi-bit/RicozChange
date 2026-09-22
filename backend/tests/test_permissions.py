"""Phase-2 permission enforcement: role matrix, ownership rules, denial audit."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import Depends  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from ricozchange import config, db as dbmod  # noqa: E402
from ricozchange.auth import require_actor  # noqa: E402
from ricozchange.main import app  # noqa: E402
from ricozchange.models import User  # noqa: E402


@pytest.fixture()
def client():
    dbmod.init_db()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(require_actor, None)


def _as_user(email: str):
    """Override the actor dependency with a specific seeded user."""

    def dep(db: Session = Depends(dbmod.get_db)):
        return db.execute(select(User).where(User.email == email)).scalars().one()

    app.dependency_overrides[require_actor] = dep


def _make_change(client, title="Engineer change on search"):
    resp = client.post(
        "/api/changes",
        json={
            "title": title,
            "risk_type": "normal",
            "system_keys": ["search-api"],
            "window_start": "2026-12-10T22:00",
            "window_end": "2026-12-11T00:00",
            "rollback_plan": "revert patch",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_engineer_can_create_submit_and_edit_own(client):
    _as_user("dev@Ricozchange.dev")  # engineer
    change = _make_change(client)
    cid = change["id"]

    patched = client.patch(f"/api/changes/{cid}", json={"description": "tuned"})
    assert patched.status_code == 200

    submitted = client.post(f"/api/changes/{cid}/submit")
    assert submitted.status_code == 200
    final = client.get(f"/api/changes/{cid}").json()
    assert final["status"] in ("submitted", "approved")


def test_engineer_cannot_approve(client):
    _as_user("dev@Ricozchange.dev")  # engineer
    change = _make_change(client)
    client.post(f"/api/changes/{change['id']}/submit")

    resp = client.post(f"/api/changes/{change['id']}/approvals", json={"decision": "approved"})
    assert resp.status_code == 403
    assert "role" in resp.json()["detail"].lower()


def test_owner_cannot_approve_own_change(client):
    # Default demo actor (Priya, admin) creates AND tries to approve: denied.
    change = _make_change(client, "Admin's own change")
    client.post(f"/api/changes/{change['id']}/submit")

    resp = client.post(f"/api/changes/{change['id']}/approvals", json={"decision": "approved"})
    assert resp.status_code == 403
    assert "own change" in resp.json()["detail"]


def test_engineer_cannot_manage_freezes(client):
    _as_user("dev@Ricozchange.dev")  # engineer
    resp = client.post(
        "/api/freezes",
        json={"name": "Diwali freeze", "starts_at": "2026-11-01T00:00", "ends_at": "2026-11-05T00:00"},
    )
    assert resp.status_code == 403


def test_manager_can_manage_freezes(client):
    _as_user("arjun@Ricozchange.dev")  # manager
    resp = client.post(
        "/api/freezes",
        json={"name": "Diwali freeze", "starts_at": "2026-11-01T00:00", "ends_at": "2026-11-05T00:00"},
    )
    assert resp.status_code == 201


def test_engineer_cannot_import_csv(client):
    _as_user("dev@Ricozchange.dev")  # engineer
    resp = client.post("/api/changes/import-csv", files={"file": ("x.csv", "title\nnothing", "text/csv")})
    assert resp.status_code == 403


def test_manager_can_import_csv(client):
    _as_user("arjun@Ricozchange.dev")  # manager
    resp = client.post(
        "/api/changes/import-csv",
        files={
            "file": (
                "x.csv",
                "title,description,risk_type,systems,window_start,window_end\n"
                "Emailed change,imported,normal,search-api,2026-12-10 22:00,2026-12-11 00:00",
                "text/csv",
            )
        },
    )
    assert resp.status_code == 200, resp.text


def test_engineer_cannot_decide_cab(client):
    meeting = client.post("/api/cab", json={"scheduled_at": "2026-12-12T10:00"}).json()
    _as_user("dev@Ricozchange.dev")  # engineer
    resp = client.post(f"/api/cab/items/{meeting['id']}/decide", json={"decision": "approved"})
    assert resp.status_code == 403


def test_denied_attempts_are_audited(client):
    _as_user("dev@Ricozchange.dev")  # engineer
    client.post("/api/freezes", json={"name": "x", "starts_at": "2026-11-01T00:00", "ends_at": "2026-11-02T00:00"})

    audit = client.get("/api/audit?limit=50").json()
    denied = [e for e in audit if e["action"] == "denied" and "Dev Patel" in e["actor"]]
    assert denied, "expected a 'denied' audit entry for the engineer's attempt"
    assert "engineer" in denied[0]["detail"]


def test_non_approver_cannot_act_on_slack_message(client):
    # Change #7's Slack approval belongs to Sara (approver); Mei (engineer) must not act.
    notifications = client.get("/api/notifications").json()
    target = next(n for n in notifications if not n["acted"] and n["approval_id"])
    _as_user("mei@Ricozchange.dev")  # engineer
    resp = client.post(f"/api/notifications/{target['id']}/act", json={"action": "approve"})
    assert resp.status_code == 403


def test_unauthenticated_is_401_when_gated(client):
    config.GATE_BY_DEMO_USER = True
    try:
        resp = client.get("/api/bootstrap")
        assert resp.status_code == 401
    finally:
        config.GATE_BY_DEMO_USER = False
