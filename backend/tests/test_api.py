"""End-to-end API tests on an isolated in-memory database."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi import Depends
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Isolated test env: in-memory SQLite, no Claude calls, deterministic actor.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["AUTO_SEED"] = "1"
os.environ.pop("ANTHROPIC_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

from ricozchange import config, db as dbmod  # noqa: E402
from ricozchange.main import app  # noqa: E402
from ricozchange import services  # noqa: E402
from ricozchange.auth import require_actor  # noqa: E402
from ricozchange.models import Approval, User  # noqa: E402


@pytest.fixture()
def client():
    dbmod.init_db()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(require_actor, None)


def _as_user(email: str):
    """Act as a specific seeded user (used where the owner rule forbids self-approval)."""

    def dep(db: Session = Depends(dbmod.get_db)):
        return db.execute(select(User).where(User.email == email)).scalars().one()

    app.dependency_overrides[require_actor] = dep


def _db():
    return dbmod.SessionLocal()


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_bootstrap_seeded(client):
    data = client.get("/api/bootstrap").json()
    assert data["actor"]["email"] == config.DEFAULT_USER_EMAIL
    assert len(data["systems"]) >= 8
    assert len(data["templates"]) == 3
    assert any(e["source"] and e["target"] for e in data["edges"])


def test_change_lifecycle_with_fast_track(client):
    # Standard change on a low-criticality staging system → should auto-approve.
    resp = client.post(
        "/api/changes",
        json={
            "title": "Restart staging web",
            "risk_type": "standard",
            "system_keys": ["staging-web"],
            "window_start": "2026-12-05T01:00",
            "window_end": "2026-12-05T01:30",
            "rollback_plan": "Restart again.",
        },
    )
    assert resp.status_code == 201, resp.text
    change = resp.json()
    assert change["risk_score"] is not None
    assert change["factors"], "explainable factors must exist"

    submitted = client.post(f"/api/changes/{change['id']}/submit").json()
    assert submitted["fast_tracked"] is True

    detail = client.get(f"/api/changes/{change['id']}").json()
    assert detail["status"] == "approved"
    assert any(a["decision"] == "approved" for a in detail["approvals"])


def test_risky_change_requires_approval_and_slack_flow(client):
    resp = client.post(
        "/api/changes",
        json={
            "title": "Payments DB failover test",
            "risk_type": "major",
            "system_keys": ["payments-db", "payments-api"],
            "window_start": "2026-12-05T10:00",
            "window_end": "2026-12-05T13:00",
        },
    )
    change = resp.json()
    assert resp.status_code == 201

    # Should NOT fast-track and should queue Slack-style notifications.
    submitted = client.post(f"/api/changes/{change['id']}/submit").json()
    assert submitted["fast_tracked"] is False

    notifications = client.get("/api/notifications").json()
    mine = [n for n in notifications if n["change_id"] == change["id"] and not n["acted"]]
    assert mine, "approval request notifications must be queued"

    # Approve via the Slack-demo action endpoint. The change is owned by the
    # demo actor, so the assigned approver must act (owner-cannot-approve-own).
    with dbmod.SessionLocal() as db:
        approval = db.get(Approval, mine[0]["approval_id"])
        approver_email = db.get(User, approval.approver_id).email
    _as_user(approver_email)
    acted = client.post(
        f"/api/notifications/{mine[0]['id']}/act", json={"action": "approve", "comment": "lgtm"}
    )
    assert acted.status_code == 200
    detail = client.get(f"/api/changes/{change['id']}").json()
    assert detail["status"] == "approved"

    # Back to the owner for execution (approvers decide, owners implement).
    app.dependency_overrides.pop(require_actor, None)

    # Implement → complete → post-change check feeds CFR.
    assert client.post(f"/api/changes/{change['id']}/status", json={"status": "implementing"}).status_code == 200
    assert client.post(f"/api/changes/{change['id']}/status", json={"status": "completed"}).status_code == 200
    post = client.post(f"/api/changes/{change['id']}/post-change", json={"result": "failed", "notes": "write freeze overran"})
    assert post.status_code == 200

    cfr = client.get("/api/dashboard").json()["cfr"]
    assert cfr["total"] >= 7  # 6 seeded + this one
    assert cfr["failed"] >= 2


def test_collision_detected_and_freeze_penalty(client):
    # Two overlapping changes on payments-db.
    base = {
        "title": "Payments DB maintenance A",
        "risk_type": "normal",
        "system_keys": ["payments-db"],
        "window_start": "2026-12-06T02:00",
        "window_end": "2026-12-06T04:00",
        "rollback_plan": "snapshot",
    }
    first = client.post("/api/changes", json=base).json()

    sim = client.post(
        "/api/simulate",
        json={
            "system_keys": ["payments-db"],
            "risk_type": "normal",
            "window_start": "2026-12-06T03:00",
            "window_end": "2026-12-06T05:00",
            "rollback_plan_present": True,
        },
    ).json()
    assert any(c["change_id"] == first["id"] for c in sim["collisions"])
    assert any("Overlaps other active changes" in f["label"] for f in sim["factors"])


def test_freeze_window_penalty(client):
    # Seed freeze is ~6 days out; simulate a window inside it.
    freezes = client.get("/api/freezes").json()
    assert freezes, "seeded freeze must exist"
    freeze = freezes[0]
    sim = client.post(
        "/api/simulate",
        json={
            "system_keys": ["checkout-web"],
            "risk_type": "normal",
            "window_start": freeze["starts_at"][:16],
            "window_end": freeze["ends_at"][:16],
            "rollback_plan_present": True,
        },
    ).json()
    assert any("freeze" in f["label"].lower() for f in sim["factors"])


def test_suggest_windows_avoids_collisions(client):
    suggestions = client.get("/api/suggest-windows", params={"system_keys": "payments-db"}).json()
    assert suggestions, "should find at least one safe overnight slot"
    for s in suggestions:
        assert "22:00" in s["start"]


def test_ai_draft_fallback_and_apply(client):
    resp = client.post(
        "/api/changes",
        json={
            "title": "Upgrade search API",
            "risk_type": "normal",
            "system_keys": ["search-api"],
            "window_start": "2026-12-07T23:00",
            "window_end": "2026-12-08T01:00",
        },
    )
    change = resp.json()
    draft = client.post(f"/api/changes/{change['id']}/ai-draft").json()
    assert draft["engine"] == "template"  # no API key in tests
    assert "Rollback plan" in draft["drafts"]["rollback_plan"]

    applied = client.post(
        f"/api/changes/{change['id']}/apply-drafts",
        json={"rollback_plan": draft["drafts"]["rollback_plan"]},
    ).json()
    assert "Rollback plan" in applied["rollback_plan"]


def test_csv_import(client):
    csv_content = (
        "title,risk_type,systems,window_start,window_end,description,rollback_plan,owner_email\n"
        "Imported cert renewal,standard,auth-service,2026-12-09 02:00,2026-12-09 03:00,renew cert,restore old cert,priya@Ricozchange.dev\n"
        "Bad systems row,normal,no-such-system,2026-12-09 02:00,2026-12-09 03:00,,,\n"
    )
    resp = client.post(
        "/api/changes/import-csv",
        files={"file": ("changes.csv", csv_content, "text/csv")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] == 1
    assert len(data["errors"]) == 1
    assert "unknown systems" in data["errors"][0]


def test_cab_flow(client):
    resp = client.post(
        "/api/changes",
        json={
            "title": "Orders API blue-green cutover",
            "risk_type": "major",
            "system_keys": ["orders-api"],
            "window_start": "2026-12-06T23:00",
            "window_end": "2026-12-07T02:00",
            "rollback_plan": "Switch back to blue.",
        },
    )
    change = resp.json()
    submitted = client.post(f"/api/changes/{change['id']}/submit").json()
    meeting_id = submitted["cab_meeting_id"]
    assert meeting_id

    cab = client.get(f"/api/cab/{meeting_id}").json()
    item = next(i for i in cab["items"] if i["change_id"] == change["id"])
    result = client.post(f"/api/cab/items/{item['id']}/decide", json={"decision": "approved"}).json()
    assert result["change_status"] == "approved"


def test_invalid_transition_rejected(client):
    resp = client.post(
        "/api/changes",
        json={
            "title": "Small config tweak",
            "risk_type": "normal",
            "system_keys": ["staging-web"],
            "window_start": "2026-12-05T02:00",
            "window_end": "2026-12-05T02:30",
            "rollback_plan": "revert",
        },
    )
    change = resp.json()
    bad = client.post(f"/api/changes/{change['id']}/status", json={"status": "completed"})
    assert bad.status_code == 409


def test_audit_trail_records_actions(client):
    resp = client.post(
        "/api/changes",
        json={
            "title": "Audit trail check",
            "risk_type": "normal",
            "system_keys": ["users-db"],
            "window_start": "2026-12-05T03:00",
            "window_end": "2026-12-05T04:00",
            "rollback_plan": "restore",
        },
    )
    change = resp.json()
    audit = client.get(f"/api/changes/{change['id']}/audit").json()
    actions = [e["action"] for e in audit]
    assert "created" in actions
    # A draft edit must also land in the append-only trail.
    client.patch(f"/api/changes/{change['id']}", json={"description": "tweaked"})
    audit = client.get(f"/api/changes/{change['id']}/audit").json()
    actions = [e["action"] for e in audit]
    assert "updated" in actions
