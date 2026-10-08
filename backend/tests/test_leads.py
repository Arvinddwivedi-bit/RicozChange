"""Landing-page lead capture: public submit (validated + throttled), admin
inbox listing, status transitions. Stored in the settings key/value table."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ricozchange import db as dbmod
from ricozchange import leads
from ricozchange.main import app

_TEST_ADMIN_TOKEN = "test-leads-admin-token"


@pytest.fixture()
def client():
    with TestClient(app) as c:
        leads._RATE.clear()
        yield c


def _admin_get(client: TestClient, path: str = "/api/leads"):
    return client.get(path, headers={"Authorization": f"Bearer {_TEST_ADMIN_TOKEN}"})


def _admin_patch(client: TestClient, lead_id: str, status: str):
    return client.patch(
        f"/api/leads/{lead_id}",
        json={"status": status},
        headers={"Authorization": f"Bearer {_TEST_ADMIN_TOKEN}"},
    )


def _submit(client: TestClient, **overrides) -> dict:
    payload = {
        "name": "Priya Sharma",
        "email": "priya@sharmait.in",
        "company": "Sharma IT Services",
        "city": "Pune",
        "message": "Interested in the IT services franchise for our city.",
        **overrides,
    }
    return client.post("/api/leads", json=payload)


def test_submit_lead_returns_201(client):
    res = _submit(client)
    assert res.status_code == 201
    body = res.json()
    assert body["ok"] is True
    assert body["id"].startswith("lead_")


def test_submit_rejects_invalid_email(client):
    res = _submit(client, email="not-an-email")
    assert res.status_code == 422


def test_submit_rejects_short_fields(client):
    assert client.post("/api/leads", json={"name": "P", "email": "a@b.co", "company": "X Co"}).status_code == 422
    assert client.post("/api/leads", json={"name": "Priya Sharma", "email": "a@b.co", "company": "X"}).status_code == 422


def test_submit_is_throttled_per_ip(client):
    for _ in range(5):
        assert _submit(client).status_code == 201
    assert _submit(client).status_code == 429


def test_lead_is_persisted(client):
    _submit(client, email="persist@check.in")
    db = dbmod.SessionLocal()
    try:
        setting = db.get(leads.models.Setting, leads.LEADS_KEY)
        assert setting is not None
        items = setting.value["items"]
        assert items[0]["email"] == "persist@check.in"
        assert items[0]["status"] == "new"
    finally:
        db.close()


def test_list_requires_admin(client, monkeypatch):
    # Anonymous (demo-mode) requests are rejected even though the implicit
    # actor would be admin — the leads inbox must stay private.
    assert client.get("/api/leads").status_code == 401

    # With LEADS_ADMIN_TOKEN set, that static bearer token acts as admin.
    _submit(client)
    monkeypatch.setenv("LEADS_ADMIN_TOKEN", _TEST_ADMIN_TOKEN)
    res = _admin_get(client)
    assert res.status_code == 200
    body = res.json()
    assert body["new_count"] >= 1
    assert any(i["email"] == "priya@sharmait.in" for i in body["items"])


def test_list_rejects_wrong_admin_token(client, monkeypatch):
    monkeypatch.setenv("LEADS_ADMIN_TOKEN", _TEST_ADMIN_TOKEN)
    assert (
        client.get("/api/leads", headers={"Authorization": "Bearer wrong-token"}).status_code
        == 401
    )


def test_mark_lead_status_transition(client, monkeypatch):
    monkeypatch.setenv("LEADS_ADMIN_TOKEN", _TEST_ADMIN_TOKEN)
    _submit(client, email="mark@check.in")
    lead_id = _admin_get(client).json()["items"][0]["id"]
    res = _admin_patch(client, lead_id, "contacted")
    assert res.status_code == 200
    items = _admin_get(client).json()["items"]
    assert next(i for i in items if i["id"] == lead_id)["status"] == "contacted"


def test_mark_lead_requires_admin(client, monkeypatch):
    monkeypatch.setenv("LEADS_ADMIN_TOKEN", _TEST_ADMIN_TOKEN)
    _submit(client, email="guard@check.in")
    lead_id = _admin_get(client).json()["items"][0]["id"]
    assert client.patch(f"/api/leads/{lead_id}", json={"status": "closed"}).status_code == 401


def test_mark_lead_rejects_bad_status(client, monkeypatch):
    monkeypatch.setenv("LEADS_ADMIN_TOKEN", _TEST_ADMIN_TOKEN)
    res = _admin_patch(client, "lead_x", "bogus")
    assert res.status_code == 422


def test_mark_lead_unknown_id_404(client, monkeypatch):
    monkeypatch.setenv("LEADS_ADMIN_TOKEN", _TEST_ADMIN_TOKEN)
    res = _admin_patch(client, "lead_missing", "closed")
    assert res.status_code == 404
