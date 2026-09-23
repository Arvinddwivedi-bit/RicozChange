"""Workflow services: state machine, approvals, CAB, seeding, CSV import."""
from __future__ import annotations

import csv
import io
import random
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .audit import log_action
from .models import (
    Approval,
    CABItem,
    CABMeeting,
    Change,
    DependencyEdge,
    FreezeWindow,
    PostChangeResult,
    StandardChangeTemplate,
    SystemNode,
    User,
)
from .notifications import queue_approval_requests
from .risk_engine import score_and_persist

APPROVER_ROLES = ("manager", "approver", "admin")

# Allowed status transitions
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "draft": ("submitted", "cancelled"),
    "submitted": ("approved", "rejected", "cancelled"),
    "approved": ("implementing", "cancelled"),
    "implementing": ("completed", "failed"),
    "completed": (),
    "failed": (),
    "rejected": ("draft",),
    "cancelled": (),
}


def can_transition(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, ())


def transition(db: Session, change: Change, target: str, actor: str, detail: str = "") -> None:
    if not can_transition(change.status, target):
        raise ValueError(f"Invalid transition {change.status} → {target}")
    change.status = target
    log_action(db, "change", change.id, f"status:{target}", actor=actor, detail=detail)
    db.flush()


def eligible_approvers(db: Session) -> list[User]:
    return list(
        db.execute(select(User).where(User.role.in_(APPROVER_ROLES)).order_by(User.id)).scalars().all()
    )


# ---------- Submission ----------

def submit_change(db: Session, change: Change, actor: str) -> dict:
    """Score, fast-track check, route to CAB or queue approvals. Returns routing info."""
    score, _ = score_and_persist(db, change)

    if change.risk_type == "standard" and score < 25:
        change.status = "submitted"
        log_action(
            db, "change", change.id, "fast_track", actor=actor,
            detail=f"standard change, score {score} < 25 → auto-approve eligible",
        )
        auto_approve(db, change, actor=actor, comment="Auto fast-track: standard change with low risk score")
        db.flush()
        return {"fast_tracked": True, "score": score}

    for approver in eligible_approvers(db):
        db.add(Approval(change_id=change.id, approver_id=approver.id))

    next_cab = db.execute(
        select(CABMeeting)
        .where(CABMeeting.status == "scheduled", CABMeeting.scheduled_at >= datetime.now())
        .order_by(CABMeeting.scheduled_at)
    ).scalars().first()
    if next_cab is None:
        next_cab = CABMeeting(scheduled_at=datetime.now() + timedelta(days=1), notes="Auto-created CAB")
        db.add(next_cab)
        db.flush()
    db.add(CABItem(meeting_id=next_cab.id, change_id=change.id))
    change.cab_meeting_id = next_cab.id

    change.status = "submitted"
    log_action(
        db, "change", change.id, "status:submitted", actor=actor,
        detail=f"score {score}; routed to CAB #{next_cab.id} + {len(eligible_approvers(db))} approver(s)",
    )
    queue_approval_requests(db, change)
    db.flush()
    return {"fast_tracked": False, "score": score, "cab_meeting_id": next_cab.id}


def auto_approve(db: Session, change: Change, actor: str, comment: str) -> None:
    """Fast-track: approval recorded from every eligible approver."""
    for approver in eligible_approvers(db):
        db.add(Approval(
            change_id=change.id,
            approver_id=approver.id,
            decision="approved",
            comment=comment,
            source="web",
            decided_at=datetime.now(),
        ))
    change.status = "approved"
    log_action(db, "change", change.id, "status:approved", actor=actor, detail=comment)
    db.flush()


def record_approval(db: Session, change: Change, approval: Approval, decision: str, comment: str = "", source: str = "web") -> dict:
    """Any-of approval policy: one approval (with no rejections) resolves the change;
    any rejection rejects it. Remaining pending rows are closed as superseded."""
    approval.decision = decision
    approval.comment = comment
    approval.source = source
    approval.decided_at = datetime.now()
    actor = approval.approver.name if approval.approver else "approver"
    log_action(db, "approval", approval.id, f"decision:{decision}", actor=actor, detail=comment)

    if change.status != "submitted":
        return {"change_status": change.status, "outcome": "no-op"}

    rejected = [a for a in change.approvals if a.decision == "rejected"]
    approved = [a for a in change.approvals if a.decision == "approved"]
    if rejected:
        _close_superseded(db, change, "rejected")
        transition(db, change, "rejected", actor=actor, detail="an approver rejected")
        return {"change_status": change.status, "outcome": "rejected"}
    if approved:
        _close_superseded(db, change, "approved")
        transition(db, change, "approved", actor=actor, detail="approval quorum reached (any-of)")
        return {"change_status": change.status, "outcome": "approved"}
    return {"change_status": change.status, "outcome": "waiting"}


def _close_superseded(db: Session, change: Change, decision: str) -> None:
    for a in change.approvals:
        if a.decision == "pending":
            a.decision = "closed"
            a.comment = "Auto-closed: decision already reached (any-of policy)"


# ---------- CAB ----------

def cab_decide(db: Session, item: CABItem, decision: str, voter: str) -> dict:
    item.decision = decision
    votes = list(item.votes or [])
    votes.append({"voter": voter, "vote": decision})
    item.votes = votes

    change = db.get(Change, item.change_id)
    if change is None:
        raise ValueError("Change not found")

    if decision == "approved" and change.status == "submitted":
        for approver in eligible_approvers(db):
            db.add(Approval(
                change_id=change.id,
                approver_id=approver.id,
                decision="approved",
                comment="Approved in CAB",
                source="cab",
                decided_at=datetime.now(),
            ))
        transition(db, change, "approved", actor=voter, detail=f"CAB #{item.meeting_id} approved")
    elif decision in ("rejected", "deferred") and change.status == "submitted":
        transition(db, change, "rejected", actor=voter, detail=f"CAB #{item.meeting_id} {decision}")
    db.flush()
    return {"change_status": change.status, "decision": decision}


# ---------- Post-change check & CFR ----------

def record_post_change(db: Session, change: Change, result: str, notes: str = "") -> None:
    change.post_change_result = result
    change.post_change_notes = notes
    db.add(PostChangeResult(change_id=change.id, result=result, notes=notes))
    actor = change.owner.name if change.owner else "system"
    log_action(db, "change", change.id, f"post_change:{result}", actor=actor, detail=notes)
    db.flush()


def cfr_summary(db: Session) -> dict:
    rows = db.execute(select(Change).where(Change.post_change_result.isnot(None))).scalars().all()
    total = len(rows)
    failed = sum(1 for r in rows if r.post_change_result == "failed")
    partial = sum(1 for r in rows if r.post_change_result == "partial")
    success = sum(1 for r in rows if r.post_change_result == "success")
    rate = round(100.0 * (failed + partial) / total, 1) if total else 0.0
    return {"total": total, "success": success, "failed": failed, "partial": partial, "failure_rate_pct": rate}


def change_trends(db: Session) -> dict:
    """Time-series for dashboard charts: weekly volume by class and per-window CFR.

    Weeks are ISO weeks covering the last 8 weeks including the current one.
    Volume buckets use window_start; CFR buckets use window_end (outcomes are
    known after the window closes).
    """
    now = datetime.now()
    start = now - timedelta(weeks=7)
    start = start - timedelta(days=start.weekday())  # Monday of that week

    changes = db.execute(
        select(Change).where(Change.window_start >= start)
    ).scalars().unique().all()

    def bucket(dt: datetime) -> int:
        """Index 0..7 of the ISO week containing dt."""
        monday = dt - timedelta(days=dt.weekday())
        return min(7, max(0, (monday - start).days // 7))

    volume = [ {"standard": 0, "normal": 0, "major": 0, "emergency": 0} for _ in range(8) ]
    cfr = [ {"success": 0, "failed": 0, "partial": 0} for _ in range(8) ]
    for ch in changes:
        if ch.window_start:
            volume[bucket(ch.window_start)][ch.risk_type] = volume[bucket(ch.window_start)].get(ch.risk_type, 0) + 1
        if ch.post_change_result and ch.window_end:
            cfr[bucket(ch.window_end)][ch.post_change_result] = cfr[bucket(ch.window_end)].get(ch.post_change_result, 0) + 1

    week_labels = [f"{(start + timedelta(weeks=i)).strftime('%d %b')}" for i in range(8)]

    type_mix = dict(db.execute(select(Change.risk_type, func.count()).group_by(Change.risk_type)).all())

    system_counts = {}
    for ch in changes:
        for s in ch.systems:
            system_counts[s.name] = system_counts.get(s.name, 0) + 1
    system_heat = sorted(system_counts.items(), key=lambda kv: -kv[1])[:6]

    return {
        "weeks": week_labels,
        "volume": volume,
        "cfr": cfr,
        "type_mix": type_mix,
        "system_heat": system_heat,
    }


# ---------- CSV import ----------

REQUIRED_COLS = {"title", "risk_type", "systems", "window_start", "window_end"}


def import_changes_csv(db: Session, content: str, actor: str) -> dict:
    reader = csv.DictReader(io.StringIO(content))
    fields = set(reader.fieldnames or [])
    missing = REQUIRED_COLS - fields
    if missing:
        raise ValueError(f"CSV missing columns: {', '.join(sorted(missing))}")

    created, errors = 0, []
    for i, row in enumerate(reader, start=2):
        try:
            system_keys = [k.strip() for k in row["systems"].split(";") if k.strip()]
            nodes = db.execute(select(SystemNode).where(SystemNode.key.in_(system_keys))).scalars().all()
            found = {n.key for n in nodes}
            unknown = [k for k in system_keys if k not in found]
            if unknown:
                raise ValueError(f"unknown systems: {', '.join(unknown)}")

            ch = Change(
                title=row["title"].strip(),
                description=(row.get("description") or "").strip(),
                risk_type=row["risk_type"].strip().lower(),
                owner_id=_owner_id(db, row.get("owner_email") or ""),
                rollback_plan=(row.get("rollback_plan") or "").strip(),
            )
            ch.window_start = _parse_dt(row["window_start"])
            ch.window_end = _parse_dt(row["window_end"])
            ch.systems = list(nodes)
            db.add(ch)
            db.flush()
            score_and_persist(db, ch)
            log_action(db, "change", ch.id, "imported", actor=actor, detail="CSV import")
            created += 1
        except Exception as exc:  # row-level error, keep importing
            errors.append(f"row {i}: {exc}")
    db.flush()
    return {"created": created, "errors": errors}


def _parse_dt(value: str | None) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"bad datetime {value!r} (use YYYY-MM-DD HH:MM)")


def _owner_id(db: Session, email: str) -> int | None:
    email = (email or "").strip()
    if not email:
        return None
    user = db.execute(select(User).where(User.email == email)).scalars().first()
    return user.id if user else None


# ---------- Demo seeding ----------

def seed_demo_data(db: Session) -> None:
    """Idempotent demo bootstrap: systems, dependencies, freezes, templates, users,
    history, one pending risky change, a CAB meeting and Slack outbox entries."""
    if db.execute(select(User).limit(1)).scalars().first() is not None:
        return

    users = {
        "priya@Ricozchange.dev": User(name="Priya Sharma", email="priya@Ricozchange.dev", role="admin"),
        "arjun@Ricozchange.dev": User(name="Arjun Mehta", email="arjun@Ricozchange.dev", role="manager"),
        "sara@Ricozchange.dev": User(name="Sara Iqbal", email="sara@Ricozchange.dev", role="approver"),
        "dev@Ricozchange.dev": User(name="Dev Patel", email="dev@Ricozchange.dev", role="engineer"),
        "mei@Ricozchange.dev": User(name="Mei Chen", email="mei@Ricozchange.dev", role="engineer"),
    }
    for u in users.values():
        db.add(u)

    systems = {
        "payments-api": SystemNode(key="payments-api", name="Payments API", environment="production", criticality="critical", owner_team="payments"),
        "payments-db": SystemNode(key="payments-db", name="Payments DB", environment="production", criticality="critical", owner_team="payments"),
        "checkout-web": SystemNode(key="checkout-web", name="Checkout Web", environment="production", criticality="high", owner_team="storefront"),
        "orders-api": SystemNode(key="orders-api", name="Orders API", environment="production", criticality="high", owner_team="storefront"),
        "users-db": SystemNode(key="users-db", name="Users DB", environment="production", criticality="high", owner_team="identity"),
        "auth-service": SystemNode(key="auth-service", name="Auth Service", environment="production", criticality="critical", owner_team="identity"),
        "search-api": SystemNode(key="search-api", name="Search API", environment="production", criticality="medium", owner_team="discovery"),
        "search-index": SystemNode(key="search-index", name="Search Index", environment="production", criticality="medium", owner_team="discovery"),
        "staging-web": SystemNode(key="staging-web", name="Staging Web", environment="staging", criticality="low", owner_team="platform"),
    }
    for s in systems.values():
        db.add(s)
    db.flush()

    edges = [
        ("checkout-web", "orders-api"), ("checkout-web", "payments-api"),
        ("orders-api", "payments-db"), ("payments-api", "payments-db"),
        ("auth-service", "users-db"), ("orders-api", "users-db"),
        ("search-api", "search-index"),
    ]
    for src, dst in edges:
        db.add(DependencyEdge(source_id=systems[src].id, target_id=systems[dst].id))

    db.add(FreezeWindow(
        name="Quarter-end finance freeze",
        reason="No changes to billing-adjacent systems during quarter close",
        starts_at=datetime.now() + timedelta(days=6),
        ends_at=datetime.now() + timedelta(days=8),
    ))

    templates = [
        StandardChangeTemplate(
            name="Restart service", icon="🔄",
            description="Rolling restart of a service to clear memory leaks or apply small config",
            default_duration_minutes=30,
            checklist=["Verify replica healthy", "Restart one instance", "Health check 200", "Restart remaining instances"],
            rollback_plan="None needed; restart is the recovery. If an instance fails to return, start the previous image.",
        ),
        StandardChangeTemplate(
            name="Renew TLS certificate", icon="🔐",
            description="Replace an expiring TLS certificate with the renewed one",
            default_duration_minutes=45,
            checklist=["Verify new cert chain", "Install cert", "Reload nginx/envoy", "Check expiry + TLS handshake"],
            rollback_plan="Reinstall previous cert from backup and reload the proxy.",
        ),
        StandardChangeTemplate(
            name="Scale instance count", icon="📈",
            description="Horizontal scale-out of a stateless service",
            default_duration_minutes=20,
            checklist=["Confirm headroom", "Add instances", "Confirm traffic spread", "Watch error rate 15m"],
            rollback_plan="Remove added instances; the load balancer drains them automatically.",
        ),
    ]
    for t in templates:
        db.add(t)
    db.flush()

    # ---- Historical changes (feed the risk engine + CFR) ----
    now = datetime.now()
    history_spec = [
        ("Rotate payments-db connection pool", "normal", ["payments-db"], -49, -48, "failed"),
        ("Upgrade orders-api to v2.4", "normal", ["orders-api"], -43, -43, "success"),
        ("Rotate TLS certificate — checkout-web", "standard", ["checkout-web"], -36, -35, "success"),
        ("Patch auth-service CVE-2026-1183", "emergency", ["auth-service"], -28, -27, "partial"),
        ("Reindex search index v3", "major", ["search-index", "search-api"], -20, -19, "success"),
        ("Scale checkout-web to 6 replicas", "standard", ["checkout-web"], -14, -14, "success"),
        ("Migrate users-db to encrypted volumes", "major", ["users-db"], -9, -8, "success"),
        ("Nightly users-db vacuum tuning", "standard", ["users-db"], -4, -3, "success"),
        ("Restart orders-api canary fleet", "standard", ["orders-api"], -2, -1, "success"),
    ]
    for title, rtype, syskeys, start_days, end_days, result in history_spec:
        start = now + timedelta(days=start_days, hours=1)
        ch = Change(
            title=title, description="Seeded historical change", risk_type=rtype,
            status="completed" if result == "success" else ("failed" if result == "failed" else "completed"),
            owner_id=random.choice(list(users.values())).id,
            window_start=start, window_end=now + timedelta(days=end_days, hours=3),
            rollback_plan="Snapshot restore + previous image.",
            post_change_result=result,
            post_change_notes="Seeded outcome",
        )
        ch.systems = [systems[k] for k in syskeys]
        db.add(ch)
        db.flush()
        score_and_persist(db, ch)
        log_action(db, "change", ch.id, "created", actor="system seed", detail="imported history")
        log_action(db, "change", ch.id, f"status:{ch.status}", actor="system seed", detail=f"outcome: {result}")
        db.add(PostChangeResult(change_id=ch.id, result=result, notes="Seeded outcome"))

    # ---- One live pending risky change with approvals + Slack outbox ----
    risky = Change(
        title="Migrate payments-db to new instance class",
        description="Move payments-db to db.r6g.2xlarge during Tuesday night. Requires a brief write freeze.",
        risk_type="major", status="draft",
        owner_id=users["dev@Ricozchange.dev"].id,
        window_start=now + timedelta(days=1, hours=2),
        window_end=now + timedelta(days=1, hours=5),
        rollback_plan="Point DNS back to the old instance; data replicates continuously.",
    )
    risky.systems = [systems["payments-db"], systems["payments-api"]]
    db.add(risky)
    db.flush()
    score_and_persist(db, risky)

    # Submitted (not draft) so that a Slack approval resolves the change through
    # the any-of policy — record_approval only transitions submitted changes.
    risky.status = "submitted"
    log_action(db, "change", risky.id, "status:submitted", actor="system seed", detail="demo scenario: awaiting approval")

    for approver in (users["arjun@Ricozchange.dev"], users["sara@Ricozchange.dev"]):
        db.add(Approval(change_id=risky.id, approver_id=approver.id))
    db.flush()
    queue_approval_requests(db, risky)

    # ---- Upcoming CAB with the risky change on the agenda ----
    cab = CABMeeting(scheduled_at=now + timedelta(days=1, hours=4), notes="Weekly CAB")
    db.add(cab)
    db.flush()
    db.add(CABItem(meeting_id=cab.id, change_id=risky.id))
    risky.cab_meeting_id = cab.id

    # ---- In-flight standard changes for the dashboard ----
    for tmpl, syskey in zip(templates[:2], ("orders-api", "search-api")):
        ch = Change(
            title=f"{tmpl.name} — {syskey}",
            description=tmpl.description, risk_type="standard", status="approved",
            owner_id=users["mei@Ricozchange.dev"].id, template_id=tmpl.id,
            window_start=now + timedelta(days=2),
            window_end=now + timedelta(days=2, minutes=tmpl.default_duration_minutes),
            rollback_plan=tmpl.rollback_plan,
        )
        ch.systems = [systems[syskey]]
        db.add(ch)
        db.flush()
        score_and_persist(db, ch)

    log_action(db, "system", 0, "seeded", actor="system", detail="demo dataset created")
    db.commit()
