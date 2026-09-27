"""FastAPI entry point."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles  # noqa: F401  (kept for future asset serving)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config, db as dbmod
from . import services
from . import auth as auth_mod
from . import email_app
from . import slack_app
from .rate_limit import rate_limit, webhook_limiter, simulate_limiter, sweep_limiter
from fastapi.security import HTTPAuthorizationCredentials
from .auth import _bearer, get_actor, require_actor, require_role
from .ai_drafting import draft_change_docs
from .audit import log_action
from .models import (
    Approval,
    AuditLog,
    CABItem,
    CABMeeting,
    Change,
    DependencyEdge,
    EmailInbound,
    FreezeWindow,
    Notification,
    RiskFactor,
    StandardChangeTemplate,
    SystemNode,
    User,
)
from .notifications import serialize_notification
from .risk_engine import (
    evaluate_change,
    find_collisions,
    find_freeze_overlaps,
    get_change_system_ids,
    score_and_persist,
    suggest_windows,
)

app = FastAPI(title="RicozChange API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS or ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- logging (phase-2 week 4 hygiene) ----------
# One consistent format for app loggers; delivery paths log failures with
# context instead of failing silently. LOG_LEVEL overrides (default INFO).
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("rico").setLevel(logging.INFO)

# Background email sweep: only runs when EMAIL_SWEEP_SECONDS > 0
# (Render sets 300; local/demo stays manual via POST /api/integrations/email/sweep).
SWEEP_INTERVAL_SECONDS = int(os.getenv("EMAIL_SWEEP_SECONDS", "0") or "0")


@app.on_event("startup")
async def start_sweep_loop() -> None:
    if SWEEP_INTERVAL_SECONDS <= 0:
        return

    async def _loop() -> None:
        log = logging.getLogger("rico.email")
        while True:
            await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
            try:
                db = dbmod.SessionLocal()
                try:
                    counts = email_app.run_email_sweep(db)
                    db.commit()
                    if any(counts.values()):
                        log.info("background sweep: %s", counts)
                finally:
                    db.close()
            except Exception:  # noqa: BLE001 — the loop must survive anything
                log.exception("background sweep failed")

    asyncio.create_task(_loop())


@app.on_event("startup")
def on_startup() -> None:
    # Migrate BEFORE create_all: on an existing database, create_all would
    # create brand-new tables (e.g. `settings`) that the next migration then
    # tries to create again. Migrating first keeps them from racing.
    _run_migrations()
    dbmod.init_db()
    if config.AUTO_SEED:
        db = dbmod.SessionLocal()
        try:
            services.seed_demo_data(db)
        finally:
            db.close()


def _run_migrations() -> None:
    """Bring the database to the current schema, whatever its age.

    Runs BEFORE create_all (see on_startup).
    - Fresh database (no tables): mark at head; create_all then builds the
      full schema matching the models.
    - Legacy unversioned database (users exists, no alembic_version): adopt at
      the baseline revision, then upgrade (applies every later migration).
    - Already-versioned database: just upgrade.
    Never blocks startup on failure — the app still runs, migrations retry next boot.
    """
    try:
        from alembic import command
        from alembic.config import Config as AlembicConfig
        from sqlalchemy import inspect

        tables = inspect(dbmod.engine).get_table_names()
        base = Path(__file__).resolve().parent.parent
        cfg = AlembicConfig(str(base / "alembic.ini"))
        cfg.set_main_option("script_location", str(base / "alembic"))
        if "alembic_version" not in tables:
            if "users" not in tables:
                command.stamp(cfg, "head")
                print("alembic: stamped fresh database at head")
                return
            command.stamp(cfg, "d8013b0b6b62")  # baseline schema
            print("alembic: stamped existing database at baseline")
        command.upgrade(cfg, "head")
    except Exception as exc:  # noqa: BLE001
        print(f"alembic migrations skipped: {exc}")


# ---------- helpers ----------

def get_change_or_404(db: Session, change_id: int) -> Change:
    change = db.get(Change, change_id)
    if change is None:
        raise HTTPException(status_code=404, detail="Change not found")
    return change


def _deny(db: Session, actor: User, entity_type: str, entity_id: int, reason: str) -> None:
    """Audit-log a denied attempt (committed so it survives the 403) and raise."""
    log_action(db, entity_type, entity_id, "denied", actor=actor.name, detail=reason)
    db.commit()
    raise HTTPException(status_code=403, detail=reason)


def _is_owner_or_manager(actor: User, change: Change) -> bool:
    return actor.role in ("admin", "manager") or change.owner_id == actor.id


# ---------- schemas ----------

class ChangeIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = ""
    risk_type: str = "normal"
    system_keys: list[str] = Field(default_factory=list)
    window_start: datetime | None = None
    window_end: datetime | None = None
    rollback_plan: str = ""
    template_id: int | None = None


class ChangePatch(BaseModel):
    title: str | None = None
    description: str | None = None
    risk_type: str | None = None
    system_keys: list[str] | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    rollback_plan: str | None = None


class StatusIn(BaseModel):
    status: str
    detail: str = ""


class ApprovalIn(BaseModel):
    decision: str
    comment: str = ""


class ApprovalsIn(BaseModel):
    decision: str
    comment: str = ""


class PostChangeIn(BaseModel):
    result: str
    notes: str = ""


class ApplyDraftsIn(BaseModel):
    rollback_plan: str | None = None
    test_plan: str | None = None
    comms_plan: str | None = None


class CABCreateIn(BaseModel):
    scheduled_at: datetime
    notes: str = ""


class CABAddItemIn(BaseModel):
    change_id: int


class CABDecideIn(BaseModel):
    decision: str
    voter: str = "CAB member"


class FreezeIn(BaseModel):
    name: str
    reason: str = ""
    starts_at: datetime
    ends_at: datetime


class SimulatorIn(BaseModel):
    system_keys: list[str]
    risk_type: str
    window_start: datetime
    window_end: datetime
    rollback_plan_present: bool = False
    exclude_change_id: int | None = None


class NotificationActionIn(BaseModel):
    action: str  # approve | reject
    comment: str = ""


class SlackLinkIn(BaseModel):
    slack_id: str = ""


# ---------- generic list endpoints ----------

@app.get("/api")
def root() -> dict:
    return {"status": "ok", "service": "RicozChange API", "docs": "/docs"}


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "time": datetime.now().isoformat()}


@app.get("/api/auth/me")
def auth_me(
    db: Session = Depends(dbmod.get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """Identity + auth-mode discovery for the SPA.

    Deliberately bypasses get_actor's 401 in gated mode: with a valid token the
    actor is resolved exactly as every other route would (same JWKS path), and
    without one the frontend is told to show sign-in. Demo mode answers the
    seeded actor so the UI can run token-free.
    """
    if credentials is not None:
        try:
            actor = auth_mod.get_actor(credentials=credentials, db=db)
        except HTTPException as exc:
            if exc.status_code == 401:
                return {"auth_mode": "clerk", "actor": None}
            raise
    else:
        if config.GATE_BY_DEMO_USER:
            return {"auth_mode": "clerk", "actor": None}
        actor = auth_mod.get_actor(credentials=None, db=db)
    users = db.execute(select(User).order_by(User.id)).scalars().all()
    return {
        "auth_mode": "clerk" if config.GATE_BY_DEMO_USER else "demo",
        "actor": {"id": actor.id, "name": actor.name, "email": actor.email, "role": actor.role},
        "users": [{"id": u.id, "name": u.name, "email": u.email, "role": u.role} for u in users],
    }


@app.get("/api/bootstrap")
def bootstrap(db: Session = Depends(dbmod.get_db), actor: User = Depends(require_actor)) -> dict:
    """Everything the SPA needs on first load."""
    users = db.execute(select(User).order_by(User.id)).scalars().all()
    systems = db.execute(select(SystemNode).order_by(SystemNode.id)).scalars().all()
    edges = db.execute(select(DependencyEdge)).scalars().all()
    templates = db.execute(select(StandardChangeTemplate).order_by(StandardChangeTemplate.id)).scalars().all()
    return {
        "actor": {"id": actor.id, "name": actor.name, "email": actor.email, "role": actor.role},
        "users": [{"id": u.id, "name": u.name, "email": u.email, "role": u.role} for u in users],
        "systems": [
            {"id": s.id, "key": s.key, "name": s.name, "environment": s.environment,
             "criticality": s.criticality, "owner_team": s.owner_team}
            for s in systems
        ],
        "edges": [{"source": e.source_id, "target": e.target_id, "kind": e.kind} for e in edges],
        "templates": [
            {"id": t.id, "name": t.name, "icon": t.icon, "description": t.description,
             "default_duration_minutes": t.default_duration_minutes,
             "checklist": t.checklist, "rollback_plan": t.rollback_plan}
            for t in templates
        ],
    }


@app.get("/api/users")
def list_users(db: Session = Depends(dbmod.get_db)) -> list[dict]:
    users = db.execute(select(User).order_by(User.id)).scalars().all()
    return [{"id": u.id, "name": u.name, "email": u.email, "role": u.role} for u in users]


@app.get("/api/systems")
def list_systems(db: Session = Depends(dbmod.get_db)) -> list[dict]:
    systems = db.execute(select(SystemNode).order_by(SystemNode.id)).scalars().all()
    return [
        {"id": s.id, "key": s.key, "name": s.name, "environment": s.environment,
         "criticality": s.criticality, "owner_team": s.owner_team}
        for s in systems
    ]


@app.get("/api/graph")
def dependency_graph(db: Session = Depends(dbmod.get_db)) -> dict:
    systems = db.execute(select(SystemNode)).scalars().all()
    edges = db.execute(select(DependencyEdge)).scalars().all()
    return {
        "nodes": [
            {"id": s.id, "key": s.key, "name": s.name, "environment": s.environment,
             "criticality": s.criticality}
            for s in systems
        ],
        "edges": [{"source": e.source_id, "target": e.target_id} for e in edges],
    }


# ---------- changes ----------

@app.get("/api/changes")
def list_changes(
    status: str | None = Query(default=None),
    db: Session = Depends(dbmod.get_db),
) -> list[dict]:
    stmt = select(Change).order_by(Change.id.desc())
    if status:
        stmt = stmt.where(Change.status == status)
    rows = db.execute(stmt).scalars().unique().all()
    return [serialize_change(c) for c in rows]


def serialize_change(c: Change) -> dict:
    return {
        "id": c.id,
        "title": c.title,
        "description": c.description,
        "risk_type": c.risk_type,
        "status": c.status,
        "owner": {"id": c.owner.id, "name": c.owner.name} if c.owner else None,
        "template_id": c.template_id,
        "cab_meeting_id": c.cab_meeting_id,
        "window_start": c.window_start.isoformat() if c.window_start else None,
        "window_end": c.window_end.isoformat() if c.window_end else None,
        "risk_score": c.risk_score,
        "systems": [{"id": s.id, "key": s.key, "name": s.name} for s in c.systems],
        "rollback_plan": c.rollback_plan,
        "test_plan": c.test_plan,
        "comms_plan": c.comms_plan,
        "post_change_result": c.post_change_result,
        "post_change_notes": c.post_change_notes,
        "created_at": c.created_at.isoformat(),
        "updated_at": c.updated_at.isoformat(),
    }


def serialize_change_detail(c: Change) -> dict:
    data = serialize_change(c)
    data.update(
        {
            "factors": [{"label": f.label, "points": f.points} for f in c.factors],
            "ai_rollback_draft": c.ai_rollback_draft,
            "ai_test_draft": c.ai_test_draft,
            "ai_comms_draft": c.ai_comms_draft,
            "approvals": [
                {
                    "id": a.id,
                    "approver": {"id": a.approver.id, "name": a.approver.name} if a.approver else None,
                    "decision": a.decision,
                    "comment": a.comment,
                    "source": a.source,
                    "decided_at": a.decided_at.isoformat() if a.decided_at else None,
                }
                for a in c.approvals
            ],
            "transitions": list(services.TRANSITIONS.get(c.status, ())),
        }
    )
    return data


@app.get("/api/changes/{change_id}")
def get_change(change_id: int, db: Session = Depends(dbmod.get_db)) -> dict:
    change = get_change_or_404(db, change_id)
    data = serialize_change_detail(change)

    collisions = find_collisions(
        db, [s.id for s in change.systems], change.window_start, change.window_end, exclude_change_id=change.id
    )
    freezes = find_freeze_overlaps(db, change.window_start, change.window_end)
    audit = db.execute(
        select(AuditLog)
        .where(AuditLog.entity_type == "change", AuditLog.entity_id == change.id)
        .order_by(AuditLog.id.desc())
    ).scalars().all()
    approval_audit_ids = [a.id for a in change.approvals]
    if approval_audit_ids:
        extra = db.execute(
            select(AuditLog)
            .where(AuditLog.entity_type == "approval", AuditLog.entity_id.in_(approval_audit_ids))
            .order_by(AuditLog.id.desc())
        ).scalars().all()
        audit = list(audit) + list(extra)
        audit.sort(key=lambda e: e.created_at, reverse=True)

    data["collisions"] = collisions
    data["freeze_overlaps"] = freezes
    data["audit"] = [
        {"id": e.id, "action": e.action, "actor": e.actor, "detail": e.detail,
         "created_at": e.created_at.isoformat()}
        for e in audit
    ]
    return data


@app.post("/api/changes", status_code=201)
def create_change(payload: ChangeIn, db: Session = Depends(dbmod.get_db), actor: User = Depends(require_actor)) -> dict:
    nodes = db.execute(select(SystemNode).where(SystemNode.key.in_(payload.system_keys))).scalars().all()
    if payload.system_keys and len(nodes) != len(set(payload.system_keys)):
        unknown = set(payload.system_keys) - {n.key for n in nodes}
        raise HTTPException(status_code=400, detail=f"Unknown systems: {', '.join(sorted(unknown))}")

    if payload.window_start and payload.window_end and payload.window_end <= payload.window_start:
        raise HTTPException(status_code=400, detail="window_end must be after window_start")

    change = Change(
        title=payload.title,
        description=payload.description,
        risk_type=payload.risk_type if payload.risk_type in ("standard", "normal", "major", "emergency") else "normal",
        owner_id=actor.id,
        template_id=payload.template_id,
        window_start=payload.window_start,
        window_end=payload.window_end,
        rollback_plan=payload.rollback_plan,
    )
    change.systems = list(nodes)
    db.add(change)
    db.flush()
    score_and_persist(db, change)
    log_action(db, "change", change.id, "created", actor=actor.name, detail=change.title)
    db.commit()
    db.refresh(change)
    return serialize_change_detail(change)


@app.patch("/api/changes/{change_id}")
def patch_change(change_id: int, payload: ChangePatch, db: Session = Depends(dbmod.get_db), actor: User = Depends(require_actor)) -> dict:
    change = get_change_or_404(db, change_id)
    if not _is_owner_or_manager(actor, change):
        _deny(db, actor, "change", change.id, "only the change owner can edit a draft change")
    if change.status not in ("draft", "rejected"):
        raise HTTPException(status_code=409, detail=f"Change is {change.status}; only draft/rejected changes can be edited")

    data = payload.model_dump(exclude_unset=True)
    if "system_keys" in data:
        keys = data.pop("system_keys") or []
        nodes = db.execute(select(SystemNode).where(SystemNode.key.in_(keys))).scalars().all()
        if keys and len(nodes) != len(set(keys)):
            unknown = set(keys) - {n.key for n in nodes}
            raise HTTPException(status_code=400, detail=f"Unknown systems: {', '.join(sorted(unknown))}")
        change.systems = list(nodes)
    if "window_start" in data and "window_end" in data and data["window_start"] and data["window_end"]:
        if data["window_end"] <= data["window_start"]:
            raise HTTPException(status_code=400, detail="window_end must be after window_start")
    for field, value in data.items():
        setattr(change, field, value)

    score_and_persist(db, change)
    log_action(db, "change", change.id, "updated", actor=actor.name, detail=", ".join(sorted(data.keys())))
    db.commit()
    db.refresh(change)
    return serialize_change_detail(change)


@app.post("/api/changes/{change_id}/submit")
def submit(change_id: int, db: Session = Depends(dbmod.get_db), actor: User = Depends(require_actor)) -> dict:
    change = get_change_or_404(db, change_id)
    if not _is_owner_or_manager(actor, change):
        _deny(db, actor, "change", change.id, "only the change owner can submit a change")
    if change.status != "draft":
        raise HTTPException(status_code=409, detail=f"Only draft changes can be submitted (currently {change.status})")
    if not change.systems:
        raise HTTPException(status_code=400, detail="Attach at least one affected system before submitting")
    result = services.submit_change(db, change, actor=actor.name)
    db.commit()
    return result


@app.post("/api/changes/{change_id}/status")
def set_status(change_id: int, payload: StatusIn, db: Session = Depends(dbmod.get_db), actor: User = Depends(require_actor)) -> dict:
    change = get_change_or_404(db, change_id)
    if not _is_owner_or_manager(actor, change):
        _deny(db, actor, "change", change.id, "only the change owner can update the status")
    try:
        services.transition(db, change, payload.status, actor=actor.name, detail=payload.detail)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if payload.status in ("completed", "failed"):
        change.post_change_prompted_at = datetime.now()
    db.commit()
    return serialize_change_detail(change)


@app.post("/api/changes/{change_id}/approvals")
def decide_approvals(change_id: int, payload: ApprovalsIn, db: Session = Depends(dbmod.get_db), actor: User = Depends(require_role("approver", "manager", "admin"))) -> dict:
    """Web one-click decision across the actor's pending approvals (fast-track style)."""
    if payload.decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="decision must be approved or rejected")
    change = get_change_or_404(db, change_id)
    if change.owner_id == actor.id:
        _deny(db, actor, "change", change.id, "you cannot approve your own change")
    mine = [a for a in change.approvals if a.decision == "pending" and a.approver_id == actor.id]
    if not mine:
        raise HTTPException(status_code=409, detail="No pending approval for you on this change")
    outcome = {"change_status": change.status, "outcome": "waiting"}
    for approval in mine:
        outcome = services.record_approval(db, change, approval, payload.decision, payload.comment, source="web")
    db.commit()
    return outcome


@app.post("/api/changes/{change_id}/ai-draft")
def ai_draft(change_id: int, db: Session = Depends(dbmod.get_db), actor: User = Depends(require_actor)) -> dict:
    change = get_change_or_404(db, change_id)
    result = draft_change_docs(db, change)
    db.commit()
    return result


@app.post("/api/changes/{change_id}/apply-drafts")
def apply_drafts(change_id: int, payload: ApplyDraftsIn, db: Session = Depends(dbmod.get_db), actor: User = Depends(require_actor)) -> dict:
    """Human-approved application of AI drafts (optionally edited)."""
    change = get_change_or_404(db, change_id)
    applied = []
    if payload.rollback_plan is not None:
        change.rollback_plan = payload.rollback_plan
        applied.append("rollback_plan")
    if payload.test_plan is not None:
        change.test_plan = payload.test_plan
        applied.append("test_plan")
    if payload.comms_plan is not None:
        change.comms_plan = payload.comms_plan
        applied.append("comms_plan")
    if not applied:
        raise HTTPException(status_code=400, detail="Nothing to apply")
    log_action(db, "change", change.id, "drafts_applied", actor=actor.name, detail=", ".join(applied))
    score_and_persist(db, change)  # rollback presence affects the score
    db.commit()
    return serialize_change_detail(change)


@app.post("/api/changes/{change_id}/post-change")
def post_change(change_id: int, payload: PostChangeIn, db: Session = Depends(dbmod.get_db), actor: User = Depends(require_actor)) -> dict:
    if payload.result not in ("success", "failed", "partial"):
        raise HTTPException(status_code=400, detail="result must be success, failed or partial")
    change = get_change_or_404(db, change_id)
    if not _is_owner_or_manager(actor, change):
        _deny(db, actor, "change", change.id, "only the change owner can record the post-change result")
    if change.status not in ("completed", "failed"):
        raise HTTPException(status_code=409, detail="Record the post-change check after the window closes")
    services.record_post_change(db, change, payload.result, payload.notes)
    db.commit()
    return serialize_change_detail(change)


@app.get("/api/changes/{change_id}/audit")
def change_audit(change_id: int, db: Session = Depends(dbmod.get_db)) -> list[dict]:
    change = get_change_or_404(db, change_id)
    rows = db.execute(
        select(AuditLog).where(AuditLog.entity_type == "change", AuditLog.entity_id == change.id).order_by(AuditLog.id)
    ).scalars().all()
    return [
        {"id": e.id, "action": e.action, "actor": e.actor, "detail": e.detail, "created_at": e.created_at.isoformat()}
        for e in rows
    ]


@app.post("/api/changes/import-csv")
def import_csv(file: UploadFile = File(...), db: Session = Depends(dbmod.get_db), actor: User = Depends(require_role("manager", "admin"))) -> dict:
    content = file.file.read().decode("utf-8-sig")
    try:
        result = services.import_changes_csv(db, content, actor=actor.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    return result


# ---------- simulator ----------

@app.post("/api/simulate")
def simulate(payload: SimulatorIn, db: Session = Depends(dbmod.get_db)) -> dict:
    nodes = db.execute(select(SystemNode).where(SystemNode.key.in_(payload.system_keys))).scalars().all()
    score, factors = evaluate_change(
        db,
        system_ids=[n.id for n in nodes],
        risk_type=payload.risk_type,
        window_start=payload.window_start,
        window_end=payload.window_end,
        change_id=payload.exclude_change_id,
        rollback_plan_present=payload.rollback_plan_present,
    )
    collisions = find_collisions(db, [n.id for n in nodes], payload.window_start, payload.window_end, payload.exclude_change_id)
    freezes = find_freeze_overlaps(db, payload.window_start, payload.window_end)
    return {"score": score, "factors": factors, "collisions": collisions, "freeze_overlaps": freezes}


@app.get("/api/suggest-windows")
def suggest_windows_endpoint(
    system_keys: str = Query(..., description="Comma-separated system keys"),
    days: int = Query(default=10, ge=1, le=30),
    duration_hours: float = Query(default=2.0, gt=0, le=12),
    db: Session = Depends(dbmod.get_db),
) -> list[dict]:
    keys = [k.strip() for k in system_keys.split(",") if k.strip()]
    nodes = db.execute(select(SystemNode).where(SystemNode.key.in_(keys))).scalars().all()
    return suggest_windows(db, [n.id for n in nodes], days=days, duration_hours=duration_hours)


# ---------- approvals & CAB ----------

@app.get("/api/approvals/mine")
def my_approvals(db: Session = Depends(dbmod.get_db), actor: User = Depends(require_actor)) -> list[dict]:
    rows = db.execute(
        select(Approval).where(Approval.approver_id == actor.id, Approval.decision == "pending")
    ).scalars().all()
    out = []
    for a in rows:
        change = db.get(Change, a.change_id)
        if change is None:
            continue
        out.append({"approval_id": a.id, "change": serialize_change(change)})
    return out


@app.post("/api/approvals/{approval_id}")
def decide_approval(approval_id: int, payload: ApprovalIn, db: Session = Depends(dbmod.get_db), actor: User = Depends(require_role("approver", "manager", "admin"))) -> dict:
    approval = db.get(Approval, approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    if approval.approver_id != actor.id:
        raise HTTPException(status_code=403, detail="This approval belongs to someone else")
    if payload.decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="decision must be approved or rejected")
    change = db.get(Change, approval.change_id)
    if change is None:
        raise HTTPException(status_code=404, detail="Change not found")
    if change.owner_id == actor.id:
        _deny(db, actor, "change", change.id, "you cannot approve your own change")
    outcome = services.record_approval(db, change, approval, payload.decision, payload.comment, source="web")
    db.commit()
    return outcome


@app.get("/api/cab")
def list_cab(db: Session = Depends(dbmod.get_db)) -> list[dict]:
    meetings = db.execute(select(CABMeeting).order_by(CABMeeting.scheduled_at)).scalars().unique().all()
    return [serialize_cab(m, db) for m in meetings]


def serialize_cab(m: CABMeeting, db: Session | None = None) -> dict:
    items_out = []
    for i in m.items:
        change = db.get(Change, i.change_id) if db else None
        items_out.append(
            {
                "id": i.id,
                "change_id": i.change_id,
                "decision": i.decision,
                "votes": i.votes,
                "change": serialize_change(change) if change else None,
            }
        )
    return {
        "id": m.id,
        "scheduled_at": m.scheduled_at.isoformat(),
        "notes": m.notes,
        "status": m.status,
        "items": items_out,
    }


@app.get("/api/cab/{meeting_id}")
def get_cab(meeting_id: int, db: Session = Depends(dbmod.get_db)) -> dict:
    meeting = db.get(CABMeeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="CAB meeting not found")
    items = db.execute(select(CABItem).where(CABItem.meeting_id == meeting.id)).scalars().all()
    out_items = []
    for i in items:
        change = db.get(Change, i.change_id)
        out_items.append(
            {
                "id": i.id,
                "change_id": i.change_id,
                "decision": i.decision,
                "votes": i.votes,
                "change": serialize_change(change) if change else None,
            }
        )
    return {
        "id": meeting.id,
        "scheduled_at": meeting.scheduled_at.isoformat(),
        "notes": meeting.notes,
        "status": meeting.status,
        "items": out_items,
    }


@app.post("/api/cab", status_code=201)
def create_cab(payload: CABCreateIn, db: Session = Depends(dbmod.get_db), actor: User = Depends(require_role("manager", "admin"))) -> dict:
    meeting = CABMeeting(scheduled_at=payload.scheduled_at, notes=payload.notes)
    db.add(meeting)
    db.commit()
    db.refresh(meeting)
    return {"id": meeting.id, "scheduled_at": meeting.scheduled_at.isoformat(), "notes": meeting.notes, "status": meeting.status, "items": []}


@app.post("/api/cab/{meeting_id}/items", status_code=201)
def add_cab_item(meeting_id: int, payload: CABAddItemIn, db: Session = Depends(dbmod.get_db), actor: User = Depends(require_role("manager", "admin"))) -> dict:
    meeting = db.get(CABMeeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="CAB meeting not found")
    change = db.get(Change, payload.change_id)
    if change is None:
        raise HTTPException(status_code=404, detail="Change not found")
    item = CABItem(meeting_id=meeting.id, change_id=change.id)
    db.add(item)
    change.cab_meeting_id = meeting.id
    db.commit()
    db.refresh(item)
    return {"id": item.id, "meeting_id": meeting.id, "change_id": change.id, "decision": item.decision}


@app.post("/api/cab/items/{item_id}/decide")
def decide_cab_item(item_id: int, payload: CABDecideIn, db: Session = Depends(dbmod.get_db), actor: User = Depends(require_role("manager", "admin"))) -> dict:
    item = db.get(CABItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="CAB item not found")
    if payload.decision not in ("approved", "rejected", "deferred"):
        raise HTTPException(status_code=400, detail="decision must be approved, rejected or deferred")
    result = services.cab_decide(db, item, payload.decision, voter=actor.name)
    db.commit()
    return result


# ---------- freezes ----------

@app.get("/api/freezes")
def list_freezes(db: Session = Depends(dbmod.get_db)) -> list[dict]:
    rows = db.execute(select(FreezeWindow).order_by(FreezeWindow.starts_at)).scalars().all()
    return [
        {"id": f.id, "name": f.name, "reason": f.reason,
         "starts_at": f.starts_at.isoformat(), "ends_at": f.ends_at.isoformat()}
        for f in rows
    ]


@app.post("/api/freezes", status_code=201)
def create_freeze(payload: FreezeIn, db: Session = Depends(dbmod.get_db), actor: User = Depends(require_role("manager", "admin"))) -> dict:
    if payload.ends_at <= payload.starts_at:
        raise HTTPException(status_code=400, detail="ends_at must be after starts_at")
    freeze = FreezeWindow(
        name=payload.name, reason=payload.reason,
        starts_at=payload.starts_at, ends_at=payload.ends_at,
    )
    db.add(freeze)
    db.commit()
    db.refresh(freeze)
    return {"id": freeze.id, "name": freeze.name, "reason": freeze.reason,
            "starts_at": freeze.starts_at.isoformat(), "ends_at": freeze.ends_at.isoformat()}


# ---------- Slack demo outbox ----------

@app.get("/api/notifications")
def list_notifications(db: Session = Depends(dbmod.get_db)) -> list[dict]:
    rows = db.execute(select(Notification).order_by(Notification.id.desc())).scalars().all()
    return [serialize_notification(n) for n in rows]


@app.post("/api/notifications/{notification_id}/act")
def act_on_notification(notification_id: int, payload: NotificationActionIn, db: Session = Depends(dbmod.get_db), actor: User = Depends(require_actor)) -> dict:
    note = db.get(Notification, notification_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    if note.acted:
        raise HTTPException(status_code=409, detail="Already acted on this message")
    if payload.action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="action must be approve or reject")
    if note.approval_id is None:
        raise HTTPException(status_code=409, detail="This message is not an approval request")

    approval = db.get(Approval, note.approval_id)
    change = db.get(Change, note.change_id) if note.change_id else None
    if approval is None or change is None:
        raise HTTPException(status_code=404, detail="Approval or change not found")
    if actor.role not in ("admin", "manager") and approval.approver_id != actor.id:
        _deny(db, actor, "notification", note.id, "only the assigned approver can act on this message")
    if change.owner_id == actor.id:
        _deny(db, actor, "change", change.id, "you cannot approve your own change")

    decision = "approved" if payload.action == "approve" else "rejected"
    services.record_approval(db, change, approval, decision, payload.comment, source="slack")
    note.acted = True
    note.acted_action = decision
    log_action(db, "notification", note.id, f"slack_{decision}", actor=actor.name)
    db.commit()
    return {"notification_id": note.id, "action": decision, "change_status": change.status}


# ---------- dashboards ----------

@app.get("/api/dashboard")
def dashboard(db: Session = Depends(dbmod.get_db)) -> dict:
    total = db.execute(select(func.count()).select_from(Change)).scalar_one()
    by_status = dict(db.execute(select(Change.status, func.count()).group_by(Change.status)).all())
    pending_approvals = db.execute(
        select(func.count()).select_from(Approval).where(Approval.decision == "pending")
    ).scalar_one()
    upcoming = db.execute(
        select(Change)
        .where(Change.window_start >= datetime.now(), Change.status.in_(("approved", "implementing")))
        .order_by(Change.window_start)
        .limit(5)
    ).scalars().unique().all()
    top_risk = db.execute(
        select(Change).where(Change.status.in_(("submitted", "approved", "implementing"))).order_by(Change.risk_score.desc()).limit(5)
    ).scalars().unique().all()
    return {
        "total_changes": total,
        "by_status": by_status,
        "pending_approvals": pending_approvals,
        "cfr": services.cfr_summary(db),
        "upcoming": [serialize_change(c) for c in upcoming],
        "top_risk": [serialize_change(c) for c in top_risk],
        "trends": services.change_trends(db),
    }


@app.get("/api/audit")
def all_audit(limit: int = Query(default=100, le=500), db: Session = Depends(dbmod.get_db)) -> list[dict]:
    rows = db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)).scalars().all()
    return [
        {"id": e.id, "entity_type": e.entity_type, "entity_id": e.entity_id, "action": e.action,
         "actor": e.actor, "detail": e.detail, "created_at": e.created_at.isoformat()}
        for e in rows
    ]


# ---------- Slack integration (phase 2, week 2) ----------

@app.get("/api/integrations/slack/status")
def slack_status(db: Session = Depends(dbmod.get_db)) -> dict:
    """Connection status for the integrations UI."""
    connected = slack_app.is_connected(db)
    out = {"connected": connected}
    if connected and config.SLACK_CLIENT_ID:
        out["install_url"] = slack_app.oauth_access_url(
            config.SLACK_CLIENT_ID,
            config.SLACK_REDIRECT_URI or f"{config.PUBLIC_BASE_URL}/api/integrations/slack/oauth/callback",
            state="install",
        )
    return out


@app.get("/api/integrations/slack/install")
def slack_install(db: Session = Depends(dbmod.get_db)) -> object:
    if not config.SLACK_CLIENT_ID:
        raise HTTPException(status_code=501, detail="Slack OAuth is not configured (set SLACK_CLIENT_ID / SLACK_CLIENT_SECRET)")
    url = slack_app.oauth_access_url(
        config.SLACK_CLIENT_ID,
        config.SLACK_REDIRECT_URI or f"{config.PUBLIC_BASE_URL}/api/integrations/slack/oauth/callback",
        state="install",
    )
    return RedirectResponse(url)


@app.get("/api/integrations/slack/oauth/callback")
def slack_oauth_callback(code: str = Query(...), state: str = Query(default=""), db: Session = Depends(dbmod.get_db)) -> object:
    try:
        data = slack_app.exchange_oauth_code(
            code,
            config.SLACK_REDIRECT_URI or f"{config.PUBLIC_BASE_URL}/api/integrations/slack/oauth/callback",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    team = data.get("team") or {}
    bot = data.get("access_token", "")
    slack_app.save_settings(
        db,
        bot_token=bot,
        team_id=team.get("id", ""),
        team_name=team.get("name", ""),
        bot_user_id=data.get("bot_user", {}).get("app_id", "") if isinstance(data.get("bot_user"), dict) else data.get("bot_user", ""),
        installed_at=datetime.now().isoformat(),
    )
    log_action(db, "system", 0, "slack_installed", actor="oauth", detail=f"team {team.get('name', team.get('id', '?'))}")
    db.commit()
    return HTMLResponse(
        "<html><body style='font-family:sans-serif;text-align:center;padding-top:3rem'>"
        "<h2>RicozChange is connected to Slack</h2>"
        f"<p>Workspace: <b>{team.get('name', '?')}</b> — you can close this tab.</p>"
        "</body></html>"
    )


@app.post(
    "/api/slack/interactions",
    dependencies=[Depends(rate_limit(webhook_limiter, "slack"))],
)
async def slack_interactions(request: Request, db: Session = Depends(dbmod.get_db)) -> object:
    """Inbound Slack interactive payloads (approve/reject buttons)."""
    body = await request.body()
    settings = slack_app.get_settings(db)
    ts = request.headers.get("x-slack-signature-timestamp", "")
    sig = request.headers.get("x-slack-signature", "")
    if not slack_app.verify_signature(settings.get("signing_secret", ""), ts, body, sig):
        log_action(db, "system", 0, "slack_interaction_rejected", actor="slack", detail="invalid signature")
        db.commit()
        raise HTTPException(status_code=401, detail="invalid Slack signature")

    payload = slack_app.parse_interaction_body(body)
    result = slack_app.handle_interaction(db, payload)
    db.commit()
    return JSONResponse(result)


@app.post("/api/users/{user_id}/slack-link")
def link_slack(user_id: int, payload: SlackLinkIn, db: Session = Depends(dbmod.get_db), actor: User = Depends(require_role("admin"))) -> dict:
    """Admin manual link (fallback when email autolink can't match)."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if payload.slack_id:
        clash = db.execute(select(User).where(User.slack_id == payload.slack_id, User.id != user.id)).scalars().first()
        if clash:
            raise HTTPException(status_code=409, detail=f"slack_id already linked to {clash.name}")
    user.slack_id = payload.slack_id or None
    log_action(db, "user", user.id, "slack_link", actor=actor.name, detail=payload.slack_id or "unlinked")
    db.commit()
    return {"id": user.id, "name": user.name, "slack_id": user.slack_id}


# ---------- Email integration (phase 2, week 3) ----------

class EmailInboundIn(BaseModel):
    """SendGrid Inbound Parse POSTs multipart form fields; this model accepts
    the JSON/JSON-encoded subset our pipeline needs (parsed by FastAPI from
    form data in the webhook route)."""
    message_id: str = ""
    from_addr: str
    subject: str = ""
    body: str = ""


def _serialize_inbound(row: EmailInbound) -> dict:
    return {
        "id": row.id,
        "message_id": row.message_id,
        "from_addr": row.from_addr,
        "subject": row.subject,
        "status": row.status,
        "error_detail": row.error_detail,
        "parsed_change_id": row.parsed_change_id,
        "received_at": row.received_at.isoformat(),
    }


@app.get("/api/integrations/email/status")
def email_status(db: Session = Depends(dbmod.get_db)) -> dict:
    """Connection state for the Integrations page."""
    return {
        "webhook_url": f"{config.PUBLIC_BASE_URL}{email_app.WEBHOOK_URL}",
        "signature_check": bool(config.EMAIL_WEBHOOK_KEY),
        "mailbox": config.EMAIL_FROM_ADDR,
        "allowed_domains": sorted(config.EMAIL_ALLOWED_DOMAINS) or ["(any — demo mode)"],
    }


@app.get("/api/integrations/email/inbound")
def email_inbound_list(
    limit: int = Query(default=20, le=100),
    db: Session = Depends(dbmod.get_db),
    actor: User = Depends(require_role("admin", "manager")),
) -> dict:
    rows = db.execute(
        select(EmailInbound).order_by(EmailInbound.id.desc()).limit(limit)
    ).scalars().all()
    return {"items": [_serialize_inbound(r) for r in rows]}


@app.post(
    "/api/integrations/email/simulate",
    dependencies=[Depends(rate_limit(simulate_limiter, "emailsim"))],
)
def email_simulate(payload: EmailInboundIn, db: Session = Depends(dbmod.get_db), actor: User = Depends(require_actor)) -> dict:
    """Run the identical inbound pipeline without a mail server (demos/tests)."""
    from_addr = payload.from_addr.strip() or "demo@ricozchange.dev"
    result, row = email_app.process_inbound(
        db,
        message_id=payload.message_id or f"<sim-{datetime.utcnow().timestamp()}@rico.local>",
        from_addr=from_addr,
        subject=payload.subject,
        body=payload.body,
    )
    db.commit()
    db.refresh(row)
    return {**result, "inbound_id": row.id, "status_code": row.status, "error_detail": row.error_detail}


@app.post(
    "/api/integrations/email/inbound",
    dependencies=[Depends(rate_limit(webhook_limiter, "email"))],
)
async def email_inbound_webhook(request: Request, db: Session = Depends(dbmod.get_db)) -> dict:
    """SendGrid Inbound Parse webhook (multipart form; JSON also accepted).

    Signature: SendGrid appends our configured query params to the POST URL, so
    the shared secret rides as ?key=... — verified constant-time when
    EMAIL_WEBHOOK_KEY is set. Sender must be on the allowlist; Message-ID is
    deduped; the pipeline never auto-submits what it files.
    """
    message_id = from_addr = subject = body = ""
    if (request.headers.get("content-type") or "").startswith("application/json"):
        try:
            data = await request.json()
        except Exception:  # noqa: BLE001
            data = {}
        from_addr = str(data.get("from_addr") or "")
        subject = str(data.get("subject") or "")
        body = str(data.get("body") or "")
        message_id = str(data.get("message_id") or "")
    else:
        form = await request.form()
        envelope_raw = form.get("envelope")
        from_addr = str(form.get("from") or "")
        subject = str(form.get("subject") or "")
        body = str(form.get("text") or "")
        message_id = str(form.get("Message-Id") or form.get("message_id") or "")
        if envelope_raw:
            try:
                env = json.loads(str(envelope_raw))
                from_addr = env.get("from") or from_addr
                to_list = env.get("to") or []
                if to_list and not message_id:
                    message_id = f"<envelope:{to_list[0]}:{subject[:80]}>"
            except Exception:  # noqa: BLE001 — malformed envelope: fall back to fields
                pass
    if not from_addr:
        raise HTTPException(status_code=400, detail="missing sender ('from' field)")

    provided_key = request.query_params.get("key")
    if not email_app.verify_webhook_key(provided_key):
        log_action(db, "system", 0, "email_inbound_rejected", actor="webhook", detail="invalid webhook key")
        db.commit()
        raise HTTPException(status_code=401, detail="invalid webhook key")

    result, row = email_app.process_inbound(
        db, message_id=message_id, from_addr=from_addr, subject=subject, body=body
    )
    db.commit()
    return {"status": result["status"], "change_id": result["change_id"], "reply": result["reply"], "inbound_id": row.id}


@app.post(
    "/api/integrations/email/sweep",
    dependencies=[Depends(rate_limit(sweep_limiter, "sweep"))],
)
def email_sweep(db: Session = Depends(dbmod.get_db), actor: User = Depends(require_role("admin", "manager"))) -> dict:
    """Run one outbound sweep: post-change prompts, digests, Slack fallbacks."""
    counts = email_app.run_email_sweep(db)
    db.commit()
    return counts


# ---------- static SPA (single-service deploy) ----------

# When the built frontend is baked into the image (Render single-service deploy),
# serve it from the same origin: no CORS config, one URL for your manager.
# Registered last, so every /api route above wins; unknown paths fall back to
# index.html so React Router deep links (/changes/7) work on a fresh load.
SPA_DIR = Path(os.getenv("SPA_DIR", Path(__file__).resolve().parent.parent / "static"))
if SPA_DIR.is_dir() and (SPA_DIR / "index.html").exists():
    _SPA_ROOT = SPA_DIR.resolve()
    _INDEX = _SPA_ROOT / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = (SPA_DIR / full_path).resolve()
        if candidate.is_relative_to(_SPA_ROOT) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_INDEX)
