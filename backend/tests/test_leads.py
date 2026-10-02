"""Landing-page lead capture: public submit (validated + throttled), admin
inbox listing, status transitions. Stored in the settings key/value table."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ricozchange import db as dbmod
from ricozchange import leads
from ricozchange.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        leads._RATE.clear()
        yield c


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


def test_list_requires_admin(client):
    # Demo mode: the implicit actor is admin, so the list is readable.
    res = client.get("/api/leads")
    assert res.status_code == 200
    body = res.json()
    assert body["new_count"] >= 1
    assert any(i["email"] == "priya@sharmait.in" for i in body["items"])


def test_mark_lead_status_transition(client):
    _submit(client, email="mark@check.in")
    body = client.get("/api/leads").json()
    lead_id = body["items"][0]["id"]
    res = client.patch(f"/api/leads/{lead_id}", json={"status": "contacted"})
    assert res.status_code == 200
    items = client.get("/api/leads").json()["items"]
    assert next(i for i in items if i["id"] == lead_id)["status"] == "contacted"


def test_mark_lead_rejects_bad_status(client):
    res = client.patch("/api/leads/lead_x", json={"status": "bogus"})
    assert res.status_code == 422


def test_mark_lead_unknown_id_404(client):
    res = client.patch("/api/leads/lead_missing", json={"status": "closed"})
    assert res.status_code == 404
