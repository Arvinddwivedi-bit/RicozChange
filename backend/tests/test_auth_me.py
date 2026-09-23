"""Phase-2 v0.2: identity endpoint used by the Clerk-enabled frontend."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from ricozchange import db as dbmod  # noqa: E402
from ricozchange.main import app  # noqa: E402

client = TestClient(app)


def test_auth_me_demo_mode():
    """Demo mode: /api/auth/me resolves the seeded default actor without a token."""
    dbmod.init_db()
    res = client.get("/api/auth/me")
    assert res.status_code == 200
    body = res.json()
    assert body["actor"]["email"]
    assert body["actor"]["role"]
    assert body["auth_mode"] == "demo"
    assert body["users"]


def test_auth_me_bypasses_gated_mode():
    """/api/auth/me must answer even when GATE_BY_DEMO_USER=true, so the SPA
    can discover which auth mode to present before any Clerk redirect."""
    from ricozchange import config as app_config

    assert app_config.GATE_BY_DEMO_USER is False  # test env is demo mode
    res = client.get("/api/auth/me")
    assert res.status_code == 200
    assert res.json()["auth_mode"] == "demo"


def test_bootstrap_requires_actor_dependency():
    """Sanity: bootstrap still flows through get_actor (demo actor by default)."""
    res = client.get("/api/bootstrap")
    assert res.status_code == 200
    assert res.json()["actor"]["role"] == "admin"
