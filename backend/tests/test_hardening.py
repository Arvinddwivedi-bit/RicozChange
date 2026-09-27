"""Phase-2 week-4 hardening: rate limits on public endpoints."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["AUTO_SEED"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from ricozchange import db as dbmod  # noqa: E402
from ricozchange.main import app  # noqa: E402
from ricozchange.rate_limit import SlidingWindowLimiter, webhook_limiter, simulate_limiter  # noqa: E402


@pytest.fixture()
def client():
    dbmod.init_db()
    with TestClient(app) as c:
        yield c


def test_limiter_allows_then_429s():
    lim = SlidingWindowLimiter(max_events=3, window_seconds=60.0)
    assert lim.check("k") and lim.check("k") and lim.check("k")
    assert not lim.check("k")
    assert lim.retry_after("k") >= 1
    assert lim.check("other")  # keys are independent


def test_webhook_rate_limited(client, monkeypatch):
    webhook_limiter._hits.clear()  # earlier tests may have filled the bucket
    # shrink the window for a fast test
    monkeypatch.setattr(webhook_limiter, "max_events", 2)
    ok1 = client.post("/api/integrations/email/inbound", json={"message_id": "<r1@x>", "from_addr": "dev@Ricozchange.dev", "subject": "s", "body": "x"})
    ok2 = client.post("/api/integrations/email/inbound", json={"message_id": "<r2@x>", "from_addr": "dev@Ricozchange.dev", "subject": "s", "body": "x"})
    assert ok1.status_code == 200 and ok2.status_code == 200
    blocked = client.post("/api/integrations/email/inbound", json={"message_id": "<r3@x>", "from_addr": "dev@Ricozchange.dev", "subject": "s", "body": "x"})
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers


def test_simulate_rate_limited(client, monkeypatch):
    simulate_limiter._hits.clear()
    monkeypatch.setattr(simulate_limiter, "max_events", 1)
    first = client.post("/api/integrations/email/simulate", json={"from_addr": "dev@Ricozchange.dev", "subject": "s", "body": "systems: staging-web"})
    second = client.post("/api/integrations/email/simulate", json={"from_addr": "dev@Ricozchange.dev", "subject": "s", "body": "systems: staging-web"})
    assert first.status_code == 200
    assert second.status_code == 429


def test_limiter_disabled_flag(client, monkeypatch):
    from ricozchange import rate_limit
    monkeypatch.setattr(rate_limit, "_DISABLED", True)
    webhook_limiter._hits.clear()
    monkeypatch.setattr(webhook_limiter, "max_events", 0)  # would always block
    resp = client.post("/api/integrations/email/inbound", json={"message_id": "<dis@x>", "from_addr": "dev@Ricozchange.dev", "subject": "s", "body": "x"})
    assert resp.status_code == 200  # disabled limiter lets everything through
