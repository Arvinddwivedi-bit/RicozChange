"""Calendar feed (v0.3, week 2) — .ics output and token auth tests."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["AUTO_SEED"] = "1"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from ricozchange import db as dbmod  # noqa: E402
from ricozchange.main import app  # noqa: E402
from ricozchange.models import Change, FreezeWindow, User  # noqa: E402


@pytest.fixture()
def client():
    dbmod.init_db()
    with TestClient(app) as c:
        yield c


def _db():
    return dbmod.SessionLocal()


def _rotate(client) -> str:
    r = client.post("/api/integrations/calendar/rotate").json()
    assert r["enabled"] is True and "token=" in r["url"]
    return r["url"].split("token=")[1]


def test_feed_requires_valid_token(client):
    assert client.get("/api/calendar/changes.ics").status_code == 401
    assert client.get("/api/calendar/changes.ics?token=wrong").status_code == 401
    token = _rotate(client)
    ok = client.get(f"/api/calendar/changes.ics?token={token}")
    assert ok.status_code == 200
    assert ok.headers["content-type"].startswith("text/calendar")


def test_feed_contains_changes_and_freezes(client):
    token = _rotate(client)
    body = client.get(f"/api/calendar/changes.ics?token={token}").text
    assert body.startswith("BEGIN:VCALENDAR")
    assert "PRODID:-//RicozChange//Change Calendar//EN" in body
    assert "END:VCALENDAR" in body
    # seeded data: at least one visible change and the quarter-end freeze
    assert "UID:change-" in body
    assert "UID:freeze-" in body
    assert "FREEZE:" in body
    # every event block is well-formed
    assert body.count("BEGIN:VEVENT") == body.count("END:VEVENT")
    # CRLF line endings (RFC 5545)
    assert "\r\n" in body


def test_feed_excludes_drafts_and_completed(client):
    with _db() as db:
        draft = Change(title="Secret draft", risk_type="normal", status="draft",
                       window_start=__import__("datetime").datetime(2030, 5, 1, 10, 0))
        done = Change(title="Old news", risk_type="normal", status="completed",
                      window_start=__import__("datetime").datetime(2030, 5, 2, 10, 0))
        db.add_all([draft, done])
        db.commit()
    token = _rotate(client)
    body = client.get(f"/api/calendar/changes.ics?token={token}").text
    assert "Secret draft" not in body
    assert "Old news" not in body


def test_text_escaping_and_line_folding(client):
    # exercise the builder directly: escaping + folding are pure functions
    from ricozchange import calendar_app
    from datetime import datetime as DT
    lines = calendar_app._event_lines(
        uid="unit@ricozchange",
        summary="Upgrade db; with comma, and \\ backslash",
        description="line one\nline two; careful",
        start=DT(2030, 6, 1, 10, 0), end=DT(2030, 6, 1, 12, 0),
    )
    text = "\r\n".join(line for l in lines for line in calendar_app._fold(l))
    assert "SUMMARY:Upgrade db\\; with comma\\, and \\\\ backslash" in text
    assert "line one\\nline two\\; careful" in text
    for line in text.split("\r\n"):
        assert len(line.encode()) <= 75, line

    # and the composed feed renders a real event correctly end to end
    with _db() as db:
        db.add(Change(
            title="Upgrade db; with comma, and \\ backslash",
            risk_type="major", status="approved",
            window_start=DT(2030, 6, 1, 10, 0), window_end=DT(2030, 6, 1, 12, 0),
        ))
        db.commit()
    token = _rotate(client)
    body = client.get(f"/api/calendar/changes.ics?token={token}").text
    assert "Upgrade db\\; with comma\\, and \\\\ backslash" in body
    unfolded = body.replace("\r\n ", "")
    assert "Status: approved" in unfolded


def test_rotation_kills_old_token(client):
    old = _rotate(client)
    assert client.get(f"/api/calendar/changes.ics?token={old}").status_code == 200
    new = _rotate(client)
    assert new != old
    assert client.get(f"/api/calendar/changes.ics?token={old}").status_code == 401
    assert client.get(f"/api/calendar/changes.ics?token={new}").status_code == 200


def test_status_reports_disabled_until_rotated(client):
    with _db() as db:
        me = db.execute(select(User).where(User.email == "priya@Ricozchange.dev")).scalars().one()
        me.calendar_token = None  # earlier tests may have rotated
        db.commit()
    r = client.get("/api/integrations/calendar/status").json()
    assert r["enabled"] is False and r["url"] is None
    token = _rotate(client)
    r = client.get("/api/integrations/calendar/status").json()
    assert r["enabled"] is True and r["url"].endswith(token)
