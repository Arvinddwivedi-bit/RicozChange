"""ADMIN_EMAILS auto-provisioning on first Clerk sign-in."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Isolated test env: in-memory SQLite, deterministic actor (same as test_api).
# Must be set before any ricozchange import (config captures DATABASE_URL).
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["AUTO_SEED"] = "1"

from ricozchange import config, db as dbmod  # noqa: E402
from ricozchange import services  # noqa: E402
from ricozchange.auth import _user_from_email  # noqa: E402
from ricozchange.models import AuditLog, User  # noqa: E402


@pytest.fixture()
def session():
    """Seed the shared in-memory DB directly — no app lifespan (tests must not
    re-run startup; a second lifespan run disturbs shared state)."""
    dbmod.init_db()
    db = dbmod.SessionLocal()
    services.seed_demo_data(db)
    db.commit()
    try:
        yield db
    finally:
        # Remove provisioned test users: other test modules (test_slack) share
        # this in-memory DB and queue approval notes per eligible approver —
        # a leftover admin without a slack_id would break their assertions.
        try:
            db.rollback()
            db.execute(delete(User).where(User.email == "boss@example.com"))
            db.commit()
        except Exception:
            db.rollback()
        db.close()


def _admin_emails(monkeypatch, value: str) -> None:
    monkeypatch.setattr(
        config,
        "ADMIN_EMAILS",
        {e.strip().lower() for e in value.split(",") if e.strip()},
    )


def test_admin_email_auto_provisions(session, monkeypatch):
    _admin_emails(monkeypatch, "boss@Example.com")
    user = _user_from_email(session, "boss@example.com", clerk_subject="user_abc123")
    assert user.role == "admin"
    assert user.clerk_id == "user_abc123"
    assert user.email == "boss@example.com"
    entry = session.execute(
        select(AuditLog).where(AuditLog.action == "user_provisioned").order_by(AuditLog.id.desc())
    ).scalars().first()
    assert entry is not None and entry.entity_id == user.id


def test_admin_email_matching_is_case_insensitive(session, monkeypatch):
    _admin_emails(monkeypatch, "BOSS@Example.com, other@x.dev")
    user = _user_from_email(session, "boss@example.com", clerk_subject="user_q")
    assert user.role == "admin"


def test_non_admin_unknown_email_is_rejected(session, monkeypatch):
    _admin_emails(monkeypatch, "boss@example.com")
    with pytest.raises(HTTPException) as exc:
        _user_from_email(session, "stranger@nowhere.dev")
    assert exc.value.status_code == 403


def test_known_user_gets_clerk_id_stamped(session, monkeypatch):
    _admin_emails(monkeypatch, "")
    sara = session.execute(select(User).where(User.email == "sara@Ricozchange.dev")).scalars().one()
    user = _user_from_email(session, "sara@Ricozchange.dev", clerk_subject="user_sara")
    assert user.id == sara.id
    assert user.clerk_id == "user_sara"
