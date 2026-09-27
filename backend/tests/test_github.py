"""GitHub deploy-as-change (v0.3, week 1) — end-to-end API tests.

Self-contained by design: the in-memory test database is shared across tests
in one process, so every test uses its own repo / run ids and never depends on
another test's rows.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["AUTO_SEED"] = "1"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from ricozchange import config, db as dbmod  # noqa: E402
from ricozchange.main import app  # noqa: E402
from ricozchange.models import Change, DeployLink, GitHubConnection, GitHubDelivery, User  # noqa: E402


@pytest.fixture()
def client():
    dbmod.init_db()
    with TestClient(app) as c:
        yield c


def _db():
    return dbmod.SessionLocal()


def _signed(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _connect(client, repo, systems=None, auto_submit=False, secret=""):
    resp = client.post(
        "/api/integrations/github/connections",
        json={"repo": repo, "label": "test", "default_system_keys": systems or ["staging-web"],
              "auto_submit": auto_submit, "webhook_secret": secret},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _wr_payload(repo, run, name="deploy production", conclusion="success",
                branch="main", sha="abcdef1234567890", login=""):
    return {
        "action": "completed",
        "repository": {"full_name": repo},
        "sender": {"login": login},
        "workflow_run": {
            "id": run, "name": name, "display_title": f"{name} · {branch}",
            "conclusion": conclusion, "status": "completed",
            "head_sha": sha, "head_branch": branch,
            "html_url": f"https://github.com/{repo}/actions/runs/{run}",
        },
    }


def _post_webhook(client, payload, delivery=None, sig_header=None):
    body = json.dumps(payload).encode()
    h = {"Content-Type": "application/json",
         "X-GitHub-Event": "workflow_run",
         "X-GitHub-Delivery": delivery or f"d-{payload['workflow_run']['id']}"}
    if sig_header:
        h["X-Hub-Signature-256"] = sig_header
    return client.post("/api/integrations/github/webhook", content=body, headers=h)


def test_ping_and_unconnected_repo_are_acked(client):
    ping = client.post("/api/integrations/github/webhook", content=b"{}",
                       headers={"X-GitHub-Event": "ping", "X-GitHub-Delivery": "p1"})
    assert ping.json()["status"] == "ping-ok"
    r = _post_webhook(client, _wr_payload("nobody/nowhere", "9000")).json()
    assert r["status"] == "ignored" and "not connected" in r["detail"]


def test_signature_verification(client):
    _connect(client, "sig/checkout", secret="topsecret")
    bad = _post_webhook(client, _wr_payload("sig/checkout", "9100"),
                        sig_header="sha256=" + "0" * 64)
    assert bad.status_code == 401
    good_body = json.dumps(_wr_payload("sig/checkout", "9101")).encode()
    good = client.post("/api/integrations/github/webhook", content=good_body, headers={
        "Content-Type": "application/json", "X-GitHub-Event": "workflow_run",
        "X-GitHub-Delivery": "d-9101", "X-Hub-Signature-256": _signed(good_body, "topsecret"),
    })
    assert good.json()["status"] == "created"


def test_deploy_creates_scored_linked_change(client):
    _connect(client, "link/checkout", systems=["staging-web"])
    r = _post_webhook(client, _wr_payload("link/checkout", "9102")).json()
    assert r["status"] == "created"
    with _db() as db:
        change = db.get(Change, r["change_id"])
        assert change.source == "github"
        assert change.status == "draft"  # auto_submit off
        assert [s.key for s in change.systems] == ["staging-web"]
        assert change.risk_score is not None
        link = db.execute(select(DeployLink).where(DeployLink.change_id == change.id)).scalars().one()
        assert link.repo == "link/checkout" and link.run_id == "9102"
        assert "link/checkout" in change.title and "abcdef12" in change.title
        row = db.execute(select(GitHubDelivery).where(GitHubDelivery.delivery_id == "d-9102")).scalars().one()
        assert row.status == "processed" and row.change_id == change.id


def test_duplicate_delivery_never_double_files(client):
    _connect(client, "dup/checkout")
    first = _post_webhook(client, _wr_payload("dup/checkout", "9103")).json()
    second = _post_webhook(client, _wr_payload("dup/checkout", "9103")).json()
    assert first["status"] == "created"
    assert second["status"] == "duplicate"
    with _db() as db:
        rows = db.execute(select(GitHubDelivery).where(GitHubDelivery.delivery_id == "d-9103")).scalars().all()
        assert len(rows) == 1


def test_non_production_and_inprogress_ignored(client):
    _connect(client, "env/checkout")
    stg = _post_webhook(client, _wr_payload("env/checkout", "9104", name="deploy staging")).json()
    assert stg["status"] == "ignored"
    inp = _post_webhook(client, {
        "action": "in_progress", "repository": {"full_name": "env/checkout"},
        "workflow_run": {"id": "9105", "name": "deploy production", "status": "in_progress",
                          "conclusion": None, "head_branch": "main", "head_sha": "x"},
    }, delivery="d-9105").json()
    assert inp["status"] == "ignored"


def test_outcome_loop_records_result(client):
    _connect(client, "out/checkout", auto_submit=True)
    created = _post_webhook(client, _wr_payload("out/checkout", "9106", conclusion="success")).json()
    assert created["status"] == "created" and created.get("auto_submitted") is True
    with _db() as db:
        assert db.get(Change, created["change_id"]).status == "submitted"
    # the deploy later fails: same run id, new delivery, failure conclusion
    failed = _post_webhook(client, _wr_payload("out/checkout", "9106", conclusion="failure"),
                           delivery="d-9106-fail").json()
    assert failed["status"] == "outcome-recorded" and failed["result"] == "failed"
    with _db() as db:
        change = db.get(Change, created["change_id"])
        assert change.post_change_result == "failed"
        link = db.execute(select(DeployLink).where(DeployLink.change_id == change.id)).scalars().one()
        assert link.conclusion == "failure"
    # a second failure delivery is deduped and never double-records
    again = _post_webhook(client, _wr_payload("out/checkout", "9106", conclusion="failure"),
                          delivery="d-9106-fail2").json()
    assert again["status"] == "duplicate"
    with _db() as db:
        link = db.execute(select(DeployLink).where(DeployLink.change_id == created["change_id"])).scalars().one()
        assert link.conclusion == "failure"


def test_owner_resolved_by_github_login(client):
    with _db() as db:
        dev = db.execute(select(User).where(User.email == "dev@Ricozchange.dev")).scalars().one()
        dev.github_login = "devp-github"
        db.commit()
    _connect(client, "own/checkout")
    r = _post_webhook(client, _wr_payload("own/checkout", "9107", login="devp-github")).json()
    assert r["status"] == "created"
    with _db() as db:
        change = db.get(Change, r["change_id"])
        assert change.owner is not None and change.owner.github_login == "devp-github"


def test_connection_crud_and_validation(client):
    _connect(client, "crud/api", systems=["staging-web", "orders-api"])
    dup = client.post("/api/integrations/github/connections", json={"repo": "crud/api"})
    assert dup.status_code == 409
    assert client.post("/api/integrations/github/connections", json={"repo": "just-a-name"}).status_code == 422
    assert client.post("/api/integrations/github/connections",
                       json={"repo": "crud/other", "default_system_keys": ["nope"]}).status_code == 422
    listing = client.get("/api/integrations/github/status").json()
    conn_id = next(c["id"] for c in listing["connections"] if c["repo"] == "crud/api")
    assert client.delete(f"/api/integrations/github/connections/{conn_id}").status_code == 200
    listing = client.get("/api/integrations/github/status").json()
    assert not any(c["repo"] == "crud/api" for c in listing["connections"])


def test_simulate_matches_pipeline(client):
    sim = client.post("/api/integrations/github/simulate", json={
        "repo": "sim/one", "workflow_name": "deploy production", "conclusion": "success",
        "auto_submit": True, "system_keys": ["staging-web"],
    }).json()
    assert sim["status"] == "created" and sim.get("auto_submitted") is True


def test_hotfix_run_files_major_change(client):
    _connect(client, "hf/checkout")
    r = _post_webhook(client, _wr_payload("hf/checkout", "9108", name="hotfix rollback payments")).json()
    assert r["status"] == "created"
    with _db() as db:
        assert db.get(Change, r["change_id"]).risk_type == "major"
