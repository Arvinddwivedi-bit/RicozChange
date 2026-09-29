"""Two-way calendar write-back (v0.3 week 2 part 2) — fake-transport tests."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["AUTO_SEED"] = "1"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from ricozchange import calendar_sync, config, db as dbmod  # noqa: E402
from ricozchange.main import app  # noqa: E402
from ricozchange.models import CalendarLink, Change, Setting  # noqa: E402


@pytest.fixture()
def client():
    dbmod.init_db()
    with TestClient(app) as c:
        yield c


def _db():
    return dbmod.SessionLocal()


class FakeTransport:
    """Records calls; returns plausible Google responses."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.next_id = 100
        self.events: dict[str, dict] = {}
        self.fail = False

    def __call__(self, settings, method, url, json_body=None):
        if self.fail:
            raise RuntimeError("google is down (fake)")
        self.calls.append((method, url.split("?")[0]))
        if url.endswith("/events") and method == "POST":
            eid = f"evt{self.next_id}"
            self.next_id += 1
            self.events[eid] = json_body or {}
            return {"id": eid, **(json_body or {})}
        if method == "PUT":
            eid = url.rsplit("/", 1)[1]
            self.events[eid] = json_body or {}
            return {"id": eid, **(json_body or {})}
        if method == "DELETE":
            eid = url.rsplit("/", 1)[1]
            self.events.pop(eid, None)
            return {}
        return {}


@pytest.fixture()
def fake_transport(monkeypatch):
    ft = FakeTransport()
    monkeypatch.setattr(calendar_sync, "_api_call", ft)
    monkeypatch.setattr(config, "GOOGLE_CLIENT_ID", "fake-client")
    monkeypatch.setattr(config, "GOOGLE_CLIENT_SECRET", "fake-secret")
    return ft


def _connect(db):
    calendar_sync.save_calendar_settings(
        db, refresh_token="fake-refresh", calendar_id="cal-rico", connected_at=datetime.now().isoformat()
    )
    db.commit()


def test_skips_when_not_connected(client, fake_transport):
    with _db() as db:
        c = db.execute(select(Change).where(Change.status == "submitted")).scalars().first()
        result = calendar_sync.upsert_change_event(db, c)
        assert result["status"] == "skipped"
        assert fake_transport.calls == []


def test_submit_creates_event_when_connected(client, fake_transport):
    with _db() as db:
        _connect(db)
    r = client.post("/api/changes", json={
        "title": "Sync me to the calendar", "risk_type": "major", "system_keys": ["payments-db"],
        "window_start": "2030-03-01T10:00:00", "window_end": "2030-03-01T11:00:00",
    })
    cid = r.json()["id"]
    client.post(f"/api/changes/{cid}/submit")
    with _db() as db:
        link = db.execute(select(CalendarLink).where(CalendarLink.change_id == cid)).scalars().first()
        assert link is not None, "submit should push a calendar event"
        assert fake_transport.events[link.google_event_id]["summary"].startswith("[MAJOR")
        assert "payments-db" in fake_transport.events[link.google_event_id]["description"]


def test_submit_without_connection_never_calls_transport(client, fake_transport):
    # fresh state: no settings row at all
    r = client.post("/api/changes", json={
        "title": "No google configured", "risk_type": "normal", "system_keys": ["staging-web"],
    })
    cid = r.json()["id"]
    resp = client.post(f"/api/changes/{cid}/submit")
    assert resp.status_code == 200
    assert fake_transport.calls == []


def test_window_patch_updates_same_event(client, fake_transport):
    with _db() as db:
        _connect(db)
    r = client.post("/api/changes", json={
        "title": "Reschedule probe", "risk_type": "normal", "system_keys": ["staging-web"],
        "window_start": "2030-03-01T10:00:00", "window_end": "2030-03-01T11:00:00",
    })
    cid = r.json()["id"]
    client.post(f"/api/changes/{cid}/submit")
    with _db() as db:
        link = db.execute(select(CalendarLink).where(CalendarLink.change_id == cid)).scalars().one()
        eid = link.google_event_id
    creates_before = sum(1 for m, _ in fake_transport.calls if m == "POST")
    # submit already pushed; patch a visible change -> PUT on the SAME event
    # (patch_change only allows draft/rejected, so simulate via direct upsert on the linked change)
    with _db() as db:
        change = db.get(Change, cid)
        change.window_end = datetime(2030, 3, 1, 12, 0)
        result = calendar_sync.upsert_change_event(db, change)
        assert result["status"] == "synced"
    creates_after = sum(1 for m, _ in fake_transport.calls if m == "POST")
    assert creates_after == creates_before  # update, not a new event
    assert fake_transport.events[eid]["end"]["dateTime"].startswith("2030-03-01T12:00")


def test_cancel_deletes_event(client, fake_transport):
    with _db() as db:
        _connect(db)
    r = client.post("/api/changes", json={
        "title": "Cancel probe", "risk_type": "normal", "system_keys": ["staging-web"],
        "window_start": "2030-03-02T10:00:00", "window_end": "2030-03-02T11:00:00",
    })
    cid = r.json()["id"]
    client.post(f"/api/changes/{cid}/submit")
    with _db() as db:
        link = db.execute(select(CalendarLink).where(CalendarLink.change_id == cid)).scalars().one()
        eid = link.google_event_id
    client.post(f"/api/changes/{cid}/status", json={"status": "cancelled"})
    assert eid not in fake_transport.events
    with _db() as db:
        assert db.execute(select(CalendarLink).where(CalendarLink.change_id == cid)).scalars().first() is None


def test_outage_never_blocks_workflow(client, fake_transport):
    with _db() as db:
        _connect(db)
    fake_transport.fail = True
    # create + submit must succeed even though Google is "down"
    r = client.post("/api/changes", json={
        "title": "Outage survivor", "risk_type": "normal", "system_keys": ["staging-web"],
    })
    assert r.status_code == 201
    cid = r.json()["id"]
    sub = client.post(f"/api/changes/{cid}/submit")
    assert sub.status_code == 200
    with _db() as db:
        assert db.get(Change, cid).status == "submitted"


def test_sync_all_backfills(client, fake_transport):
    with _db() as db:
        _connect(db)
    result = client.post("/api/integrations/google/sync").json()
    assert result["status"] == "done"
    assert result["synced"] >= 1  # seeded visible changes
    assert any("FREEZE" in (e or {}).get("summary", "") for e in fake_transport.events.values())


def test_disconnect_clears_connection(client, fake_transport):
    with _db() as db:
        _connect(db)
    r = client.post("/api/integrations/google/disconnect").json()
    assert r["connected"] is False
    with _db() as db:
        assert not calendar_sync.is_connected(db)


def test_connect_route_501_when_unconfigured(client, monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_CLIENT_ID", "")
    monkeypatch.setattr(config, "GOOGLE_CLIENT_SECRET", "")
    assert client.get("/api/integrations/google/connect").status_code == 501


def test_status_shape(client, fake_transport):
    s = client.get("/api/integrations/google/status").json()
    assert s["connected"] is False and s["client_configured"] is True
    with _db() as db:
        _connect(db)
    s = client.get("/api/integrations/google/status").json()
    assert s["connected"] is True and s["calendar_id"] == "cal-rico"
