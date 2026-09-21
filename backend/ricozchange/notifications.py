"""Demo Slack outbox.

In production this posts interactive messages via the Slack Web API. In the
MVP we persist the exact payloads to a `notifications` table and the frontend
renders them in a Slack-look demo view — same data shape, no Slack workspace
needed for the demo.
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Approval, Change, Notification, User

APPROVER_ROLES = ("manager", "approver", "admin")


def build_approval_message(change: Change, approval: Approval) -> dict:
    factors = sorted(change.factors, key=lambda f: abs(f.points), reverse=True)[:4]
    window = ""
    if change.window_start:
        end = change.window_end.strftime("%H:%M") if change.window_end else "?"
        window = f"{change.window_start.strftime('%a %d %b %H:%M')}–{end}"
    return {
        "text": f"Approval needed: change #{change.id} “{change.title}”",
        "blocks": [
            {"type": "section", "text": f"🔔 *Approval needed — change #{change.id}:* “{change.title}”"},
            {
                "type": "context",
                "fields": {
                    "Risk": change.risk_score if change.risk_score is not None else "?",
                    "Class": change.risk_type,
                    "Window": window or "not scheduled",
                    "Systems": ", ".join(s.key for s in change.systems) or "—",
                },
            },
            {
                "type": "risk_why",
                "items": [{"label": f.label, "points": f.points} for f in factors],
            },
            {
                "type": "actions",
                "actions": [
                    {"action": "approve", "label": "✅ Approve", "style": "primary"},
                    {"action": "reject", "label": "❌ Reject", "style": "danger"},
                ],
            },
            {"type": "footer", "text": "RicozChange · approve here or in the web app"},
        ],
    }


def queue_approval_requests(db: Session, change: Change) -> list[Notification]:
    """Queue one Slack-style message per eligible approver."""
    created: list[Notification] = []
    approvers = db.execute(
        select(User).where(User.role.in_(APPROVER_ROLES)).order_by(User.id)
    ).scalars().all()
    # Query approvals directly: the ORM collection may be stale within this transaction.
    approvals = db.execute(
        select(Approval).where(Approval.change_id == change.id, Approval.decision == "pending")
    ).scalars().all()
    for approver in approvers:
        approval = next((a for a in approvals if a.approver_id == approver.id), None)
        if approval is None:
            continue
        message = build_approval_message(change, approval)
        channel = f"@{approver.name.lower().replace(' ', '.')}"
        note = Notification(
            kind="slack",
            channel=channel,
            change_id=change.id,
            approval_id=approval.id,
            message=message,
        )
        db.add(note)
        created.append(note)
    db.flush()
    return created


def serialize_notification(note: Notification) -> dict:
    return {
        "id": note.id,
        "kind": note.kind,
        "channel": note.channel,
        "change_id": note.change_id,
        "approval_id": note.approval_id,
        "message": note.message,
        "acted": note.acted,
        "acted_action": note.acted_action,
        "created_at": note.created_at.isoformat(),
    }


def message_preview(note: Notification) -> str:
    return json.dumps(note.message)[:200]
