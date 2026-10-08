"""FastAPI entry point."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from typing import Literal
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles  # noqa: F401  (kept for future asset serving)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import calendar_app
from . import calendar_sync
from . import config, db as dbmod
from . import services
from . import auth as auth_mod
from . import email_app
from . import github_app
from . import leads
from . import slack_app
from . import teams_app
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
    DeployLink,
    EmailInbound,
    FreezeWindow,
    GitHubConnection,
    GitHubDelivery,
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

# OpenAPI/docs live under /api so platform SPA rewrites (e.g. Vercel's
# catch-all to index.html) can't shadow them - the function serves /api/*.
app = FastAPI(
    title="RicozChange API",
    version="0.1.0",
    lifespan=lifespan,
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

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

# Thread-pool size for sync endpoints (SQLAlchemy blocking calls). FastAPI/anyio
# defaults to 40 worker threads: beyond that, requests queue behind the pool and
# time out under load. Sized from THREADPOOL_TOKENS (default 200) — every sync
# route blocks a thread for its DB work, so this is the real concurrency cap.
# Applied at startup (needs a running event loop; TestClient provides one).
THREADPOOL_TOKENS = int(os.getenv("THREADPOOL_TOKENS", "200"))


def _apply_threadpool_tokens() -> None:
    try:
        from anyio import to_thread

        to_thread.current_default_thread_limiter().total_tokens = THREADPOOL_TOKENS
        logging.getLogger("rico").info("thread-pool tokens: %d", THREADPOOL_TOKENS)
    except Exception as exc:  # noqa: BLE001 — never block startup over this
        logging.getLogger("rico").warning("could not size thread pool: %s", exc)


@app.on_event("startup")
async def start_sweep_loop() -> None:
    _apply_threadpool_tokens()
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


class LeadStatusIn(BaseModel):
    status: Literal["new", "contacted", "closed"]


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


class TeamsLinkIn(BaseModel):
    teams_id: str = ""


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
    # Two-way calendar: window/title edits propagate once the change is visible.
    if change.status in calendar_sync.VISIBLE_STATUSES:
        try:
            calendar_sync.upsert_change_event(db, change)
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
            logging.getLogger("rico.calendar").exception("calendar push on patch failed")
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
    # Two-way calendar: the event appears once the change is visible (best-effort).
    try:
        calendar_sync.upsert_change_event(db, change)
    except Exception:  # noqa: BLE001 — calendar never blocks the workflow
        logging.getLogger("rico.calendar").exception("calendar push on submit failed")
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
    # Two-way calendar: cancelled/rejected events disappear; completed stay for the record.
    if payload.status in ("cancelled", "rejected"):
        try:
            calendar_sync.delete_change_event(db, change.id)
        except Exception:  # noqa: BLE001
            logging.getLogger("rico.calendar").exception("calendar delete on %s failed", payload.status)
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


# ---------- Teams integration (v0.3, week 3) ----------


@app.get("/api/integrations/teams/status")
def teams_status(db: Session = Depends(dbmod.get_db)) -> dict:
    """Connection status for the integrations UI."""
    connected = teams_app.is_connected(db)
    return {
        "connected": connected,
        "client_configured": bool(config.TEAMS_APP_ID and config.TEAMS_APP_PASSWORD),
        "setup": (
            "Register an Azure bot (App ID + client secret), set TEAMS_APP_ID / "
            "TEAMS_APP_PASSWORD, then message the bot once in Teams to complete install."
        ),
    }


@app.post(
    "/api/teams/interactions",
    dependencies=[Depends(rate_limit(webhook_limiter, "teams"))],
)
async def teams_interactions(request: Request, db: Session = Depends(dbmod.get_db)) -> object:
    """Inbound Bot Framework activities (message the bot, Action.Submit cards).

    Auth: `Authorization: Bearer` JWT from the Bot Framework, validated against
    the published OpenID metadata (the Slack-signature pattern ported). Invalid
    tokens are 401 + audit entry — never 500.
    """
    body = await request.body()
    try:
        teams_app.verify_bot_token(request.headers.get("authorization", ""), db)
    except ValueError as exc:
        log_action(db, "system", 0, "teams_interaction_rejected", actor="teams", detail=str(exc)[:200])
        db.commit()
        raise HTTPException(status_code=401, detail=f"invalid Teams token ({exc})")

    try:
        payload = json.loads(body.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="body must be a Bot Framework activity JSON")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="body must be a Bot Framework activity JSON")

    # conversationUpdate: someone added the bot / messaged it first — remember
    # the serviceUrl (and bot/tenant ids) so proactive DMs know where to send.
    if payload.get("type") == "conversationUpdate":
        service_url = str(payload.get("serviceUrl", "")).rstrip("/")
        if service_url:
            member = next((m for m in (payload.get("membersAdded") or [])), None)
            recipient = payload.get("recipient") or {}
            teams_app.save_settings(
                db,
                service_url=service_url,
                bot_id=str(recipient.get("id", "")),
                tenant_id=str((payload.get("channelData") or {}).get("tenant", {}).get("id", "")),
                installed_at=datetime.now().isoformat(),
                first_member_id=str((member or {}).get("id", "")),
            )
            log_action(db, "system", 0, "teams_installed", actor="teams", detail=f"serviceUrl {service_url}")
            db.commit()
        return JSONResponse({"status": "ok"})

    # message with Action.Submit data -> approve/reject.
    value = payload.get("value") if isinstance(payload.get("value"), dict) else {}
    if not value:
        return JSONResponse({"status": "ignored"})
    result = teams_app.handle_interaction(
        db,
        value=value,
        from_id=str((payload.get("from") or {}).get("id", "")),
        conversation_id=str((payload.get("conversation") or {}).get("id", "")),
        activity_id=str(payload.get("id", "")),
    )
    db.commit()
    return JSONResponse(result)


@app.post("/api/integrations/teams/sweep")
def teams_sweep(db: Session = Depends(dbmod.get_db), actor: User = Depends(require_role("admin", "manager"))) -> dict:
    """Manual pass: retry undelivered Teams cards + email fallback (the sweep
    runs this automatically when EMAIL_SWEEP_SECONDS > 0)."""
    counts = teams_app.run_teams_sweep(db)
    db.commit()
    return counts


@app.post("/api/users/{user_id}/teams-link")
def link_teams(user_id: int, payload: TeamsLinkIn, db: Session = Depends(dbmod.get_db), actor: User = Depends(require_role("admin"))) -> dict:
    """Admin manual link (fallback when Graph autolink can't match)."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if payload.teams_id:
        clash = db.execute(select(User).where(User.teams_id == payload.teams_id, User.id != user.id)).scalars().first()
        if clash:
            raise HTTPException(status_code=409, detail=f"teams_id already linked to {clash.name}")
    user.teams_id = payload.teams_id or None
    log_action(db, "user", user.id, "teams_link", actor=actor.name, detail=payload.teams_id or "unlinked")
    db.commit()
    return {"id": user.id, "name": user.name, "teams_id": user.teams_id}


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


# ---------- GitHub deploy-as-change (v0.3, week 1) ----------

class GitHubConnectionIn(BaseModel):
    repo: str = Field(min_length=3, max_length=200)  # "owner/name"
    label: str = ""
    default_system_keys: list[str] = Field(default_factory=list)
    auto_submit: bool = False
    webhook_secret: str = ""


def _serialize_connection(c: GitHubConnection) -> dict:
    return {
        "id": c.id,
        "repo": c.repo,
        "label": c.label,
        "default_system_keys": c.default_system_keys or [],
        "auto_submit": c.auto_submit,
        "has_own_secret": bool(c.webhook_secret),
        "created_at": c.created_at.isoformat(),
    }


def _serialize_delivery(d: GitHubDelivery) -> dict:
    return {
        "id": d.id,
        "delivery_id": d.delivery_id,
        "event": d.event,
        "repo": d.repo,
        "action": d.action,
        "status": d.status,
        "detail": d.detail,
        "change_id": d.change_id,
        "received_at": d.received_at.isoformat(),
    }


@app.get("/api/integrations/github/status")
def github_status(db: Session = Depends(dbmod.get_db)) -> dict:
    """Connection state for the Integrations page."""
    conns = db.execute(select(GitHubConnection).order_by(GitHubConnection.id)).scalars().all()
    return {
        "configured": bool(config.GITHUB_WEBHOOK_SECRET) or len(conns) > 0,
        "webhook_url": f"{config.PUBLIC_BASE_URL}/api/integrations/github/webhook",
        "global_secret_set": bool(config.GITHUB_WEBHOOK_SECRET),
        "connections": [_serialize_connection(c) for c in conns],
    }


@app.get("/api/integrations/github/deliveries")
def github_deliveries(
    limit: int = Query(default=25, le=100),
    db: Session = Depends(dbmod.get_db),
    actor: User = Depends(require_role("admin", "manager")),
) -> dict:
    rows = db.execute(
        select(GitHubDelivery).order_by(GitHubDelivery.id.desc()).limit(limit)
    ).scalars().all()
    return {"items": [_serialize_delivery(d) for d in rows]}


@app.post("/api/integrations/github/connections", status_code=201)
def create_github_connection(
    payload: GitHubConnectionIn, db: Session = Depends(dbmod.get_db), actor: User = Depends(require_role("admin", "manager"))
) -> dict:
    repo = payload.repo.strip()
    if "/" not in repo or repo.count("/") != 1 or any(p.strip() == "" for p in repo.split("/")):
        raise HTTPException(status_code=422, detail="repo must look like 'owner/name'")
    if payload.default_system_keys:
        found = db.execute(
            select(SystemNode).where(SystemNode.key.in_([k.strip().lower() for k in payload.default_system_keys]))
        ).scalars().all()
        if len(found) != len(set(k.strip().lower() for k in payload.default_system_keys)):
            raise HTTPException(status_code=422, detail="one or more default_system_keys do not exist")
    exists = db.execute(select(GitHubConnection).where(GitHubConnection.repo == repo)).scalars().first()
    if exists:
        raise HTTPException(status_code=409, detail=f"{repo} is already connected")
    conn = GitHubConnection(
        repo=repo,
        label=payload.label.strip(),
        default_system_keys=[k.strip().lower() for k in payload.default_system_keys],
        auto_submit=payload.auto_submit,
        webhook_secret=payload.webhook_secret.strip(),
        created_by=actor.id,
    )
    db.add(conn)
    db.flush()
    log_action(db, "github_connection", conn.id, "created", actor=actor.name, detail=repo)
    db.commit()
    db.refresh(conn)
    return _serialize_connection(conn)


@app.delete("/api/integrations/github/connections/{connection_id}")
def delete_github_connection(
    connection_id: int, db: Session = Depends(dbmod.get_db), actor: User = Depends(require_role("admin", "manager"))
) -> dict:
    conn = db.get(GitHubConnection, connection_id)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    log_action(db, "github_connection", conn.id, "deleted", actor=actor.name, detail=conn.repo)
    db.delete(conn)
    db.commit()
    return {"deleted": connection_id}


@app.post("/api/integrations/github/simulate")
def github_simulate(
    payload: dict, db: Session = Depends(dbmod.get_db), actor: User = Depends(require_role("admin", "manager"))
) -> dict:
    """Run the identical event pipeline without GitHub (demos/tests).

    Body: {repo, workflow_name?, environment?, conclusion?, branch?, sha?, login?, email?, auto_submit?}
    When auto_submit is true the connection row is created on the fly for the demo.
    """
    repo = str(payload.get("repo") or "").strip()
    if not repo:
        raise HTTPException(status_code=422, detail="repo is required")
    env = str(payload.get("environment") or "production").strip().lower()
    wf_name = str(payload.get("workflow_name") or f"deploy {env}")
    run_id = str(payload.get("run_id") or f"sim-{datetime.utcnow().timestamp()}")
    delivery_id = str(payload.get("delivery_id") or f"sim-{run_id}")

    if payload.get("auto_submit"):
        conn = db.execute(select(GitHubConnection).where(GitHubConnection.repo == repo)).scalars().first()
        if conn is None:
            systems = [k.strip().lower() for k in (payload.get("system_keys") or ["staging-web"])]
            db.add(GitHubConnection(
                repo=repo, label="simulated", default_system_keys=systems,
                auto_submit=True, created_by=actor.id,
            ))
            db.flush()

    built = {
        "action": "completed",
        "repository": {"full_name": repo},
        "sender": {"login": str(payload.get("login") or "")},
        "workflow_run": {
            "id": run_id,
            "name": wf_name,
            "display_title": f"{wf_name} · {payload.get('branch') or 'main'}",
            "conclusion": str(payload.get("conclusion") or "success"),
            "status": "completed",
            "head_sha": str(payload.get("sha") or ""),
            "head_branch": str(payload.get("branch") or "main"),
            "html_url": f"https://github.com/{repo}/actions/runs/{run_id}",
            "actor": {"email": str(payload.get("email") or "")} if payload.get("email") else {},
        },
    }
    headers = {"x-github-event": "workflow_run"}

    result, row = github_app.process_event(db, delivery_id=delivery_id, headers=headers, payload=built)

    # Outcome loop demo: a failed run immediately records the post-change result.
    outcome = None
    if result.get("status") == "created" and str(payload.get("conclusion") or "success") != "success":
        outcome = github_app.record_deploy_outcome(
            db, repo=repo, run_id=run_id, conclusion=str(payload.get("conclusion")), evt=None
        )
    db.commit()
    return {**result, "delivery_id": row.delivery_id, "outcome": outcome}


@app.post(
    "/api/integrations/github/webhook",
    dependencies=[Depends(rate_limit(webhook_limiter, "github"))],
)
async def github_webhook(request: Request, db: Session = Depends(dbmod.get_db)) -> object:
    """GitHub webhook: production deploys become changes; conclusions close outcomes.

    Signature verified per connection (X-Hub-Signature-256, HMAC SHA-256), with
    GITHUB_WEBHOOK_SECRET as the fallback. Delivery-id idempotent. Unknown repos
    and irrelevant events are acknowledged as 'ignored' (200) — GitHub retries
    on non-2xx, and there is nothing to retry here.
    """
    body = await request.body()
    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid JSON payload")

    event = request.headers.get("x-github-event", "")
    delivery_id = request.headers.get("x-github-delivery", "")
    repo = str((payload.get("repository") or {}).get("full_name") or "")
    sig = request.headers.get("x-hub-signature-256")

    if event != "ping" and not delivery_id:
        raise HTTPException(status_code=400, detail="missing X-GitHub-Delivery header")

    # Secret: per-connection when the repo is connected, else the global fallback.
    conn = db.execute(
        select(GitHubConnection).where(func.lower(GitHubConnection.repo) == repo.lower())
    ).scalars().first() if repo else None
    secret = github_app.connection_secret(conn) if conn else config.GITHUB_WEBHOOK_SECRET
    if not github_app.verify_signature(secret, body, sig):
        log_action(db, "system", 0, "github_webhook_rejected", actor="github", detail=f"invalid signature for {repo or 'unknown repo'}")
        db.commit()
        raise HTTPException(status_code=401, detail="invalid signature")

    if event == "ping":
        return {"status": "ping-ok"}

    # Idempotency FIRST: a redelivered event must never record an outcome twice.
    seen = db.execute(
        select(GitHubDelivery).where(GitHubDelivery.delivery_id == delivery_id)
    ).scalars().first()
    if seen:
        return {"status": "duplicate", "change_id": seen.change_id, "detail": "delivery already processed"}

    # Outcome loop: workflow_run carries the conclusion; map it onto the linked change.
    if event == "workflow_run" and str(payload.get("action") or "") == "completed":
        wr = payload.get("workflow_run") or {}
        outcome = github_app.record_deploy_outcome(
            db,
            repo=repo,
            run_id=str(wr.get("id") or ""),
            conclusion=str(wr.get("conclusion") or ""),
        )
        if outcome.get("status") == "recorded":
            db.add(GitHubDelivery(
                delivery_id=delivery_id, event=event, repo=repo, action="completed",
                status="processed", detail=f"outcome recorded: {outcome.get('result')}",
                change_id=outcome.get("change_id"),
            ))
            db.commit()
            return {**outcome, "status": "outcome-recorded"}
        if outcome.get("status") == "already_recorded":
            db.commit()
            return {"status": "duplicate", "detail": "outcome already recorded for this run"}

    try:
        result, row = github_app.process_event(db, delivery_id=delivery_id, headers=request.headers, payload=payload)
    except Exception:  # noqa: BLE001 — never 500 to GitHub; log and ack
        logging.getLogger("rico.github").exception("github webhook processing failed")
        db.rollback()
        return {"status": "error-acked"}
    db.commit()
    return {
        "status": result["status"],
        "change_id": result.get("change_id"),
        "detail": result.get("detail", ""),
        "auto_submitted": result.get("auto_submitted"),
    }


@app.post("/api/users/{user_id}/github-link")
def link_github(
    user_id: int, payload: SlackLinkIn, db: Session = Depends(dbmod.get_db), actor: User = Depends(require_role("admin"))
) -> dict:
    """Admin maps a GitHub login to a user so deploy changes get the right owner."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if payload.slack_id:
        clash = db.execute(
            select(User).where(User.github_login == payload.slack_id, User.id != user.id)
        ).scalars().first()
        if clash:
            raise HTTPException(status_code=409, detail=f"github_login already mapped to {clash.name}")
    user.github_login = payload.slack_id or None
    log_action(db, "user", user.id, "github_link", actor=actor.name, detail=payload.slack_id or "unmapped")
    db.commit()
    return {"id": user.id, "name": user.name, "github_login": user.github_login}


# ---------- Calendar feed (v0.3, week 2) ----------

@app.get("/api/calendar/changes.ics", include_in_schema=False)
def calendar_feed(request: Request, token: str = Query(default=""), db: Session = Depends(dbmod.get_db)) -> Response:
    """Read-only .ics feed of change windows and freezes.

    Authenticated by the user's personal calendar_token (in the query string —
    calendar clients can't send headers). Rotating the token kills the old URL;
    the audit log records rotations without the token value.
    """
    if not token:
        raise HTTPException(status_code=401, detail="missing calendar token")
    user = db.execute(
        select(User).where(User.calendar_token == token.strip())
    ).scalars().first()
    if user is None:
        raise HTTPException(status_code=401, detail="invalid calendar token")
    ics = calendar_app.build_change_calendar(db)
    return Response(
        content=ics,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": 'inline; filename="ricozchange.ics"',
            "Cache-Control": "no-store",
        },
    )


@app.get("/api/integrations/calendar/status")
def calendar_status(db: Session = Depends(dbmod.get_db), actor: User = Depends(require_actor)) -> dict:
    """The signed-in user's feed URL state for the Integrations page."""
    has_token = bool(actor.calendar_token)
    url = f"{config.PUBLIC_BASE_URL}/api/calendar/changes.ics?token={actor.calendar_token}" if has_token else None
    return {
        "enabled": has_token,
        "url": url,
        "note": "Subscribes in Google Calendar / Outlook — read-only, updates every fetch.",
    }


@app.post("/api/integrations/calendar/rotate")
def calendar_rotate(db: Session = Depends(dbmod.get_db), actor: User = Depends(require_actor)) -> dict:
    """Rotate (or create) the caller's calendar token; the old URL stops working."""
    actor.calendar_token = secrets.token_hex(20)
    log_action(db, "user", actor.id, "calendar_token_rotated", actor=actor.name, detail="feed url regenerated")
    db.commit()
    return {
        "enabled": True,
        "url": f"{config.PUBLIC_BASE_URL}/api/calendar/changes.ics?token={actor.calendar_token}",
    }


# ---------- Google Calendar two-way write-back (v0.3, week 2 part 2) ----------

@app.get("/api/integrations/google/status")
def google_calendar_status(db: Session = Depends(dbmod.get_db)) -> dict:
    connected = calendar_sync.is_connected(db)
    out = {
        "connected": connected,
        "client_configured": bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET),
    }
    if connected and config.GOOGLE_CLIENT_ID:
        out["connect_url"] = calendar_sync.oauth_start_url(
            config.GOOGLE_REDIRECT_URI
            or f"{config.PUBLIC_BASE_URL}/api/integrations/google/oauth/callback"
        )
    s = calendar_sync.get_calendar_settings(db)
    if connected:
        out["calendar_id"] = s.get("calendar_id")
        out["connected_at"] = s.get("connected_at")
    return out


@app.get("/api/integrations/google/connect")
def google_calendar_connect(db: Session = Depends(dbmod.get_db), actor: User = Depends(require_role("admin", "manager"))) -> object:
    if not (config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET):
        raise HTTPException(status_code=501, detail="Google Calendar sync is not configured (set GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET)")
    return RedirectResponse(calendar_sync.oauth_start_url(
        config.GOOGLE_REDIRECT_URI
        or f"{config.PUBLIC_BASE_URL}/api/integrations/google/oauth/callback"
    ))


@app.get("/api/integrations/google/oauth/callback")
def google_calendar_callback(code: str = Query(...), db: Session = Depends(dbmod.get_db)) -> HTMLResponse:
    try:
        calendar_sync.exchange_code(
            db, code,
            config.GOOGLE_REDIRECT_URI
            or f"{config.PUBLIC_BASE_URL}/api/integrations/google/oauth/callback",
        )
    except Exception as exc:  # noqa: BLE001 — show a friendly error page
        logger = logging.getLogger("rico.calendar")
        logger.warning("google oauth exchange failed: %s", exc)
        db.rollback()
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;text-align:center;padding-top:3rem'>"
            f"<h2>Google connection failed</h2><p>{str(exc)[:200]}</p></body></html>"
        )
    log_action(db, "system", 0, "google_calendar_connected", actor="oauth", detail="two-way sync enabled")
    db.commit()
    # Initial backfill so the calendar is immediately useful.
    try:
        calendar_sync.sync_all_visible(db)
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
    return HTMLResponse(
        "<html><body style='font-family:sans-serif;text-align:center;padding-top:3rem'>"
        "<h2>RicozChange calendar sync is on</h2>"
        "<p>Changes and freezes now push to the shared Google calendar automatically.</p></body></html>"
    )


@app.post("/api/integrations/google/disconnect")
def google_calendar_disconnect(db: Session = Depends(dbmod.get_db), actor: User = Depends(require_role("admin", "manager"))) -> dict:
    calendar_sync.save_calendar_settings(db, refresh_token="", calendar_id="")
    log_action(db, "system", 0, "google_calendar_disconnected", actor=actor.name, detail="two-way sync disabled")
    db.commit()
    return {"connected": False}


@app.post("/api/integrations/google/sync")
def google_calendar_sync_now(db: Session = Depends(dbmod.get_db), actor: User = Depends(require_role("admin", "manager"))) -> dict:
    """Manual backfill/retry: push every visible change and freeze."""
    result = calendar_sync.sync_all_visible(db)
    db.commit()
    return result


# ---------- Ricoz marketing-site leads (public form -> admin inbox) ----------


@app.post("/api/leads", status_code=201)
def api_submit_lead(payload: leads.LeadIn, request: Request, db: Session = Depends(dbmod.get_db)) -> dict:
    """Public endpoint for the landing page inquiry form (throttled)."""
    return leads.submit_lead(db, payload, request)


@app.get("/api/leads")
def api_list_leads(
    db: Session = Depends(dbmod.get_db),
    actor: User = Depends(leads.require_leader),
) -> dict:
    return leads.list_leads(db, actor)


@app.patch("/api/leads/{lead_id}")
def api_mark_lead(
    lead_id: str,
    payload: LeadStatusIn,
    db: Session = Depends(dbmod.get_db),
    actor: User = Depends(leads.require_leader),
) -> dict:
    return leads.mark_lead(db, lead_id, payload.status, actor)


# ---------- static SPA (single-service deploy) ----------

# When the built frontend is baked into the image (Render single-service deploy),
# serve it from the same origin: no CORS config, one URL for your manager.
# Registered last, so every /api route above wins; unknown paths fall back to
# index.html so React Router deep links (/changes/7) work on a fresh load.
SPA_DIR = Path(os.getenv("SPA_DIR", Path(__file__).resolve().parent.parent / "static"))
if SPA_DIR.is_dir() and (SPA_DIR / "index.html").exists():
    _SPA_ROOT = SPA_DIR.resolve()
    _INDEX = _SPA_ROOT / "index.html"

    _LANDING = _SPA_ROOT / "landing.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = (SPA_DIR / full_path).resolve()
        if candidate.is_relative_to(_SPA_ROOT) and candidate.is_file():
            return FileResponse(candidate)
        if _LANDING.is_file() and full_path == "landing":
            return FileResponse(_LANDING)
        return FileResponse(_INDEX)
