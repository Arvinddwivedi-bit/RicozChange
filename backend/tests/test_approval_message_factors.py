"""Regression: the approval message's "why this score" block must contain the
scored factors (a stale-collection bug shipped it empty), and button labels
must be free of decorative emoji."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["AUTO_SEED"] = "1"

from sqlalchemy import select  # noqa: E402

from ricozchange import db as dbmod  # noqa: E402
from ricozchange import services  # noqa: E402
from ricozchange.models import Change, Notification, User  # noqa: E402


def test_seeded_approval_message_has_why_factors():
    dbmod.init_db()
    db = dbmod.SessionLocal()
    services.seed_demo_data(db)
    db.commit()
    try:
        note = db.execute(select(Notification)).scalars().first()
        assert note is not None, "seeder must queue approval messages"
        blocks = {b["type"]: b for b in note.message["blocks"]}
        items = blocks["risk_why"]["items"]
        assert items, "risk_why must carry the scored factors"
        assert all("label" in i and isinstance(i["points"], int) for i in items)

        # Clean copy: no decorative emoji in product text.
        assert "Approve" in [a["label"] for a in blocks["actions"]["actions"]]
        joined = note.message["text"] + blocks["section"]["text"]
        for glyph in ("🔔", "✅", "❌"):
            assert glyph not in joined
    finally:
        db.close()


def test_fresh_submit_has_why_factors():
    """The submit path (not just the seeder) must also produce populated factors."""
    dbmod.init_db()
    db = dbmod.SessionLocal()
    services.seed_demo_data(db)
    db.commit()
    try:
        change = Change(
            title="Probe change",
            description="why-factor probe",
            risk_type="major",
            status="draft",
            owner_id=db.execute(select(User).where(User.email == "dev@Ricozchange.dev")).scalars().one().id,
        )
        change.systems = []  # no systems: factors still include type/window lines
        db.add(change)
        db.flush()
        services.submit_change(db, change, actor="probe")
        db.commit()
        note = db.execute(
            select(Notification).where(Notification.change_id == change.id)
        ).scalars().first()
        assert note is not None
        blocks = {b["type"]: b for b in note.message["blocks"]}
        assert blocks["risk_why"]["items"], "fresh submit must embed factors"
    finally:
        db.close()
