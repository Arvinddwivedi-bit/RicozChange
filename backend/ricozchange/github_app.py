"""GitHub deploy-as-change (v0.3, week 1).

A production deploy on a connected repo becomes a change request: scored
against the connection's default systems, filed with the deployer as owner
(GitHub login or email mapping), linked to the run, and its outcome recorded
from the workflow_run conclusion — closing the "did it work?" loop for deploys.

Safety rules (mirroring the email pipeline):
- HMAC SHA-256 signature verification (X-Hub-Signature-256), constant-time.
- Unique delivery_id: GitHub retries never create duplicates.
- Unknown repo (no connection) or non-production event → ignored, never an error.
- Unknown payloads rejected with 4xx, never a 500.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config
from .audit import log_action
from .models import (
    Change,
    DeployLink,
    GitHubConnection,
    GitHubDelivery,
    SystemNode,
    User,
)
from .notifications import queue_approval_requests
from .risk_engine import score_and_persist
from .services import submit_change

logger = logging.getLogger("rico.github")

PRODUCTION_ENVS = {"production", "prod", "live"}
NON_PRODUCTION_MARKERS = ("staging", "stage", "dev", "test", "qa", "e2e", "preview")


# ------------------------------------------------------------------ secrets ---

def verify_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    """GitHub HMAC SHA-256: 'sha256=<hex>'. Constant-time; empty secret = off."""
    if not secret:
        return True
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature_header[7:], expected)


def connection_secret(conn: GitHubConnection) -> str:
    return conn.webhook_secret or config.GITHUB_WEBHOOK_SECRET


# ------------------------------------------------------------ event parsing ---

def extract_event(headers, payload: dict) -> dict:
    """Flatten the two supported GitHub events into one shape.

    workflow_run (action completed): run id/url, head_sha, head_branch, name,
    conclusion, env from run_name/inputs ('deploy production').
    deployment (status): deployment id/url, sha, ref, environment.
    """
    event = headers.get("x-github-event", "")
    action = str(payload.get("action") or "")
    out = {
        "event": event,
        "action": action,
        "repo": str((payload.get("repository") or {}).get("full_name") or ""),
        "run_id": "",
        "run_url": "",
        "name": "",
        "conclusion": "",
        "environment": "",
        "sha": "",
        "branch": "",
        "deployer_login": "",
        "deployer_email": "",
    }
    if event == "workflow_run":
        wr = payload.get("workflow_run") or {}
        out["run_id"] = str(wr.get("id") or "")
        out["run_url"] = str(wr.get("html_url") or wr.get("url") or "")
        out["name"] = str(wr.get("name") or wr.get("display_title") or "")
        out["conclusion"] = str(wr.get("conclusion") or "")
        out["sha"] = str(wr.get("head_sha") or "")[:60]
        out["branch"] = str(wr.get("head_branch") or "")
        # workflow_run has no environment field: infer from the workflow name.
        # Explicit production markers win; non-production markers lose; anything
        # else defaults to production (repo connections opt in knowingly).
        env_text = f"{wr.get('name') or ''} {wr.get('display_title') or ''}".lower()
        out["environment"] = (
            "staging" if any(m in env_text for m in NON_PRODUCTION_MARKERS)
            else "production" if any(p in env_text for p in PRODUCTION_ENVS)
            else "production"
        )
        actor = payload.get("sender") or {}
        out["deployer_login"] = str(actor.get("login") or "")
        out["deployer_email"] = str(
            (wr.get("actor") or {}).get("email") or (payload.get("pusher") or {}).get("email") or ""
        )
    elif event == "deployment":
        dep = payload.get("deployment") or {}
        out["run_id"] = str(dep.get("id") or "")
        out["run_url"] = str(dep.get("url") or "")
        out["environment"] = str(dep.get("environment") or "").lower()
        out["sha"] = str(dep.get("sha") or "")[:60]
        out["branch"] = str(dep.get("ref") or "")
        out["name"] = out["environment"]
        actor = payload.get("sender") or {}
        out["deployer_login"] = str(actor.get("login") or "")
    return out


def is_relevant(evt: dict) -> bool:
    """workflow_run must be completed; deployment handled on status events.
    Environment must look like production."""
    if evt["event"] == "workflow_run":
        return evt["action"] == "completed" and _is_production(evt["environment"])
    if evt["event"] == "deployment":
        return _is_production(evt["environment"])
    return False


def _is_production(env: str) -> bool:
    env = (env or "").lower()
    if not env:
        return False  # unknown environment: not production, not ours to file
    return any(p in env for p in PRODUCTION_ENVS)


def derive_change_type(evt: dict, payload: dict) -> str:
    """Heuristic mapping: major for hotfix/rollback-ish runs, else normal.
    (Commit-scope parsing lands with the repo-connection UI polish.)"""
    name = f"{evt['name']} {evt['branch']}".lower()
    if "hotfix" in name or "rollback" in name or "emergency" in name:
        return "major"
    return "normal"


# ------------------------------------------------------------- the pipeline ---

def _resolve_owner(db: Session, evt: dict) -> User | None:
    if evt["deployer_login"]:
        user = db.execute(
            select(User).where(func.lower(User.github_login) == evt["deployer_login"].lower())
        ).scalars().first()
        if user:
            return user
    if evt["deployer_email"]:
        return db.execute(
            select(User).where(func.lower(User.email) == evt["deployer_email"].lower())
        ).scalars().first()
    return None


def process_event(db: Session, *, delivery_id: str, headers, payload: dict) -> tuple[dict, GitHubDelivery]:
    """Full event pipeline. Returns (result, delivery_row). Commits stay with the caller.
    result: {status: created|ignored|duplicate|rejected, change_id?, detail}."""

    evt = extract_event(headers, payload)
    repo = evt["repo"]

    def _row(status: str, detail: str = "", change_id: int | None = None) -> GitHubDelivery:
        return GitHubDelivery(
            delivery_id=delivery_id, event=evt["event"], repo=repo, action=evt["action"],
            status=status, detail=detail[:300], change_id=change_id,
        )

    # 1. Idempotency: GitHub retries must never double-file.
    existing = db.execute(
        select(GitHubDelivery).where(GitHubDelivery.delivery_id == delivery_id)
    ).scalars().first()
    if existing:
        return {"status": "duplicate", "change_id": existing.change_id, "detail": "already processed"}, existing

    # 2. Only completed production deploys are interesting.
    if evt["event"] not in ("workflow_run", "deployment"):
        row = _row("ignored", f"unsupported event {evt['event']}")
        db.add(row)
        db.flush()
        return {"status": "ignored", "detail": f"unsupported event {evt['event']}"}, row

    # 3. The repo must be connected.
    conn = db.execute(
        select(GitHubConnection).where(func.lower(GitHubConnection.repo) == repo.lower())
    ).scalars().first()
    if conn is None:
        row = _row("ignored", "repo not connected")
        db.add(row)
        db.flush()
        return {"status": "ignored", "detail": "repo not connected"}, row

    # 4. Non-production or in-progress events are noise.
    if not is_relevant(evt):
        row = _row("ignored", f"not a completed production deploy (action={evt['action']}, env={evt['environment'] or '?'})")
        db.add(row)
        db.flush()
        return {"status": "ignored", "detail": "not a completed production deploy"}, row

    # 5. Resolve systems from the connection; unresolvable config rejects cleanly.
    keys = [k.strip().lower() for k in (conn.default_system_keys or []) if k.strip()]
    nodes = (
        db.execute(select(SystemNode).where(func.lower(SystemNode.key).in_(keys))).scalars().all()
        if keys else []
    )
    if keys and len(nodes) != len(set(keys)):
        row = _row("error", "connection references unknown system keys")
        db.add(row)
        db.flush()
        return {"status": "rejected", "detail": "connection references unknown system keys"}, row

    # 6. Resolve the owner (deployer); unmapped deployers file ownerless drafts.
    owner = _resolve_owner(db, evt)
    sha_short = evt["sha"][:8] if evt["sha"] else "unknown"
    title = f"Deploy {repo} — {evt['name'] or evt['environment'] or 'production'} ({sha_short})"
    description = (
        f"Auto-created from a GitHub production deploy.\n"
        f"Repo: {repo}\nRun: {evt['run_url'] or evt['run_id']}\n"
        f"Branch: {evt['branch'] or '-'}  Commit: {evt['sha'] or '-'}\n"
        f"Deployer: @{evt['deployer_login'] or 'unknown'}"
    )

    change = Change(
        title=title[:200],
        description=description,
        risk_type=derive_change_type(evt, payload),
        status="draft",
        source="github",
        owner_id=owner.id if owner else None,
        window_start=datetime.utcnow(),
        window_end=None,
    )
    change.systems = list(nodes)
    db.add(change)
    db.flush()
    score_and_persist(db, change)
    db.add(DeployLink(
        change_id=change.id, repo=repo, run_id=evt["run_id"], run_url=evt["run_url"][:500],
        head_sha=evt["sha"], branch=evt["branch"][:120], environment=evt["environment"][:40],
    ))
    actor = owner.name if owner else f"@{evt['deployer_login']}" if evt["deployer_login"] else "github-webhook"
    log_action(db, "change", change.id, "created", actor=actor, detail=f"via GitHub deploy: {title[:120]}")

    # 7. Optional auto-submit: the same routing/fallback rules as the web form.
    auto_note = ""
    if conn.auto_submit:
        try:
            submit_change(db, change, actor=actor)
            auto_note = " (auto-submitted)"
        except ValueError as exc:
            auto_note = f" (auto-submit failed: {exc})"

    row = _row("processed", f"change created{auto_note}", change_id=change.id)
    db.add(row)
    db.flush()
    db.refresh(change)
    return {"status": "created", "change_id": change.id, "detail": f"change created{auto_note}", "auto_submitted": bool(conn.auto_submit)}, row


def record_deploy_outcome(db: Session, *, repo: str, run_id: str, conclusion: str, evt: dict | None = None) -> dict:
    """Close the outcome loop: find the change linked to this run and record the
    post-change result from the deploy conclusion."""
    link = db.execute(
        select(DeployLink).where(DeployLink.repo == repo, DeployLink.run_id == str(run_id))
    ).scalars().first()
    if link is None:
        return {"status": "no_link"}
    if link.conclusion:
        return {"status": "already_recorded"}
    result = {"success": "success", "failure": "failed"}.get(conclusion)
    if result is None:
        return {"status": "ignored", "detail": f"conclusion {conclusion} does not map to an outcome"}

    from .models import Approval  # local import to avoid cycles
    change = db.get(Change, link.change_id)
    if change is None:
        return {"status": "no_change"}
    link.conclusion = conclusion

    from .services import record_post_change
    actor = change.owner.name if change.owner else "github-webhook"
    record_post_change(db, change, result=result, notes=f"GitHub deploy {conclusion} ({run_id})")
    log_action(db, "deploy_link", link.id, f"outcome:{conclusion}", actor=actor, detail=repo)

    # Deploy outcome recorded: pending approvals on auto-changes are moot now.
    if change.status == "submitted":
        for ap in change.approvals:
            if ap.decision == "pending":
                ap.decision = "superseded" if result == "success" else "rejected"
                ap.source = "github"
    db.flush()
    return {"status": "recorded", "change_id": change.id, "result": result}
