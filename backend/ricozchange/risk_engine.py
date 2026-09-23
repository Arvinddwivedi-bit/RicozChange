"""Explainable, rules-based risk scoring.

Every point comes with a human-readable line item, which is the core
differentiator: approvers see *why* a change is risky, not just a number.
ML can layer on top later once real outcome data exists.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Change, DependencyEdge, FreezeWindow, RiskFactor, change_systems

RISK_TYPE_BASE: dict[str, int] = {
    "standard": 10,
    "normal": 40,
    "major": 70,
    "emergency": 80,
}

RISK_TYPE_LABEL: dict[str, str] = {
    "standard": "Base score: standard, pre-approved change class",
    "normal": "Base score: normal change, full review",
    "major": "Base score: major change, high inherent risk",
    "emergency": "Base score: emergency change, rushed review",
}

ACTIVE_STATUSES = ("draft", "submitted", "approved", "implementing")


def _overlaps(a_start, a_end, b_start, b_end) -> bool:
    if not (a_start and a_end and b_start and b_end):
        return False
    return a_start < b_end and b_start < a_end


def get_change_system_ids(db: Session, change_id: int) -> list[int]:
    rows = db.execute(
        select(change_systems.c.system_id).where(change_systems.c.change_id == change_id)
    ).scalars().all()
    return [int(r) for r in rows]


def find_collisions(
    db: Session,
    system_ids: list[int],
    window_start: datetime | None,
    window_end: datetime | None,
    exclude_change_id: int | None = None,
) -> list[dict]:
    """Active changes touching the same systems inside an overlapping window."""
    if not system_ids or not (window_start and window_end):
        return []

    candidates = db.execute(
        select(Change).where(Change.status.in_(ACTIVE_STATUSES))
    ).scalars().all()

    collisions: list[dict] = []
    for other in candidates:
        if exclude_change_id and other.id == exclude_change_id:
            continue
        if not _overlaps(window_start, window_end, other.window_start, other.window_end):
            continue
        other_system_ids = get_change_system_ids(db, other.id)
        shared = sorted(set(system_ids) & set(other_system_ids))
        if not shared:
            continue
        from .models import SystemNode

        shared_nodes = db.execute(
            select(SystemNode).where(SystemNode.id.in_(shared))
        ).scalars().all()
        collisions.append(
            {
                "change_id": other.id,
                "title": other.title,
                "status": other.status,
                "risk_type": other.risk_type,
                "window_start": other.window_start.isoformat() if other.window_start else None,
                "window_end": other.window_end.isoformat() if other.window_end else None,
                "shared_systems": [
                    {"id": s.id, "key": s.key, "name": s.name} for s in shared_nodes
                ],
            }
        )
    collisions.sort(key=lambda c: c["change_id"])
    return collisions


def find_freeze_overlaps(
    db: Session,
    window_start: datetime | None,
    window_end: datetime | None,
) -> list[dict]:
    if not (window_start and window_end):
        return []
    freezes = db.execute(select(FreezeWindow)).scalars().all()
    return [
        {
            "id": f.id,
            "name": f.name,
            "reason": f.reason,
            "starts_at": f.starts_at.isoformat(),
            "ends_at": f.ends_at.isoformat(),
        }
        for f in freezes
        if _overlaps(window_start, window_end, f.starts_at, f.ends_at)
    ]


def _window_factors(window_start: datetime | None, window_end: datetime | None) -> list[tuple[str, int]]:
    factors: list[tuple[str, int]] = []
    if not (window_start and window_end):
        return factors

    weekday = window_start.weekday()  # Mon=0 .. Sun=6
    hour = window_start.hour
    is_weekend = weekday >= 4 and (weekday != 4 or hour >= 18)  # Fri evening onwards
    is_business = weekday <= 4 and 8 <= hour < 18
    is_night = hour >= 22 or hour < 6

    if is_weekend:
        factors.append(("Weekend window — lower business traffic and staff around to respond", -10))
    elif is_night:
        factors.append(("Overnight window (22:00–06:00) — minimal user traffic", -5))

    if is_business:
        factors.append(("Window overlaps business hours — peak user impact if it fails", 10))
    duration = (window_end - window_start).total_seconds() / 3600
    if duration > 4:
        factors.append((f"Long window ({duration:.0f}h) — extended production exposure", 5))
    return factors


def _history_factors(db: Session, system_ids: list[int], exclude_change_id: int | None) -> list[tuple[str, int]]:
    factors: list[tuple[str, int]] = []
    if not system_ids:
        return factors
    cutoff = datetime.now() - timedelta(days=90)
    rows = db.execute(
        select(Change).where(
            Change.post_change_result.isnot(None),
            Change.created_at >= cutoff,
        )
    ).scalars().all()

    fails: list[str] = []
    successes: list[str] = []
    for ch in rows:
        if exclude_change_id and ch.id == exclude_change_id:
            continue
        ids = get_change_system_ids(db, ch.id)
        if not set(system_ids) & set(ids):
            continue
        if ch.post_change_result == "failed":
            fails.append(ch.title)
        elif ch.post_change_result == "success":
            successes.append(ch.title)

    if fails:
        capped = fails[:3]
        suffix = f" (+{len(fails) - 3} more)" if len(fails) > 3 else ""
        factors.append(
            (f"Past failures on these systems in the last 90 days: {'; '.join(capped)}{suffix}", 10 * len(fails[:2]))
        )
    if len(successes) >= 3:
        factors.append(("3+ recent successful changes on these systems — team knows the routine", -5))
    return factors


def evaluate_change(
    db: Session,
    *,
    system_ids: list[int],
    risk_type: str,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    change_id: int | None = None,
    rollback_plan_present: bool = False,
    include_history: bool = True,
) -> tuple[int, list[dict]]:
    """Return (score, factors) where factors is [{label, points}, ...]."""
    factors: list[dict] = []

    base = RISK_TYPE_BASE.get(risk_type, 40)
    factors.append({"label": RISK_TYPE_LABEL.get(risk_type, f"Base score: {risk_type} change"), "points": base})

    if system_ids:
        from .models import SystemNode

        nodes = db.execute(select(SystemNode).where(SystemNode.id.in_(system_ids))).scalars().all()
        for node in nodes:
            if node.environment == "production":
                factors.append({"label": f"{node.name} is a production system", "points": 8})
            if node.criticality == "critical":
                factors.append({"label": f"{node.name} is business-critical (tier-0)", "points": 15})
            elif node.criticality == "high":
                factors.append({"label": f"{node.name} is high-criticality", "points": 6})

        # Dependents: systems that rely on what we're touching
        dependent_ids = (
            db.execute(select(DependencyEdge.source_id).where(DependencyEdge.target_id.in_(system_ids)))
            .scalars().all()
        )
        dependents = max(len(set(dependent_ids) - set(system_ids)), 0)
        if dependents:
            factors.append(
                {"label": f"{dependents} downstream system(s) depend on what you're changing", "points": min(4 * dependents, 16)}
            )

    # Collisions
    collisions = find_collisions(db, system_ids, window_start, window_end, exclude_change_id=change_id)
    if collisions:
        capped = collisions[:2]
        names = "; ".join(f"#{c['change_id']} “{c['title']}”" for c in capped)
        suffix = f" (+{len(collisions) - 2} more)" if len(collisions) > 2 else ""
        factors.append({"label": f"Overlaps other active changes: {names}{suffix}", "points": min(12 * len(collisions), 24)})

    # Freeze windows
    freezes = find_freeze_overlaps(db, window_start, window_end)
    for f in freezes:
        factors.append({"label": f"Change window overlaps freeze period: {f['name']}", "points": 25})

    # Window quality
    factors.extend({"label": label, "points": pts} for label, pts in _window_factors(window_start, window_end))

    # Rollback readiness
    if not rollback_plan_present:
        factors.append({"label": "No rollback plan drafted yet — recovery would be improvised", "points": 15})
    else:
        factors.append({"label": "Rollback plan in place — recovery is a known procedure", "points": -5})

    # History
    if include_history:
        factors.extend({"label": label, "points": pts} for label, pts in _history_factors(db, system_ids, change_id))

    score = sum(int(f["points"]) for f in factors)
    return max(0, min(score, 100)), factors


def score_and_persist(db: Session, change: Change) -> tuple[int, list[dict]]:
    """(Re)compute the score for a persisted change and store its factors."""
    for f in list(change.factors):
        db.delete(f)
    db.flush()

    score, factors = evaluate_change(
        db,
        system_ids=[s.id for s in change.systems],
        risk_type=change.risk_type,
        window_start=change.window_start,
        window_end=change.window_end,
        change_id=change.id,
        rollback_plan_present=bool(change.rollback_plan),
    )
    for f in factors:
        db.add(RiskFactor(change_id=change.id, label=f["label"], points=f["points"]))
    change.risk_score = score
    change.computed_at = datetime.now()
    db.flush()
    # The factors collection may already be loaded (it is read for deletion
    # above); expire it so the next access re-queries and message builders
    # (approval DMs, Slack payloads) see the fresh line items.
    db.expire(change, ["factors"])
    return score, factors


def suggest_windows(
    db: Session,
    system_ids: list[int],
    days: int = 10,
    duration_hours: float = 2.0,
) -> list[dict]:
    """Rank upcoming overnight windows: no collisions, no freezes, weekends first."""
    suggestions: list[dict] = []
    base = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    for offset in range(1, days + 1):
        day = base + timedelta(days=offset)
        start = day.replace(hour=22)
        end = start + timedelta(hours=duration_hours)
        collisions = find_collisions(db, system_ids, start, end)
        freezes = find_freeze_overlaps(db, start, end)
        if collisions or freezes:
            continue
        is_weekend = start.weekday() >= 5
        why = ["Overnight 22:00 start — minimal traffic", "No overlapping changes"]
        if is_weekend:
            why.insert(0, "Weekend — lowest business impact")
        suggestions.append(
            {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "weekend": is_weekend,
                "why": " · ".join(why),
            }
        )
    suggestions.sort(key=lambda s: (not s["weekend"], s["start"]))
    return suggestions[:3]
