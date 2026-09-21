"""AI drafting of rollback plans, test checklists and stakeholder comms.

Uses the Claude API when ANTHROPIC_API_KEY is set; otherwise falls back to a
deterministic template so the demo always works. Every draft is stored
separately from the approved plan — a human always edits and applies it.
"""
from __future__ import annotations

import json
import re

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .audit import log_action
from .models import Change, SystemNode

SYSTEM_PROMPT = (
    "You are an IT change management assistant. Given a change request, produce "
    "three short markdown documents as STRICT JSON with keys: rollback_plan, test_plan, "
    "comms_plan. Each value is a markdown string with numbered, concrete steps. Be specific "
    "to the named systems. Keep each under 150 words. No text outside the JSON."
)


def _similarity_context(db: Session, change: Change) -> str:
    """Snippet of similar past changes on the same systems, to ground the draft."""
    ids = [s.id for s in change.systems]
    if not ids:
        return ""
    rows = db.execute(
        select(Change).where(Change.status.in_(("completed", "failed")))
    ).scalars().all()
    similar: list[Change] = []
    for other in rows:
        if other.id == change.id:
            continue
        if ids and set(ids) & {s.id for s in other.systems}:
            similar.append(other)
        if len(similar) >= 3:
            break
    if not similar:
        return ""
    lines = ["Similar past changes on these systems:"]
    for ch in similar:
        outcome = ch.post_change_result or "closed"
        lines.append(f"- “{ch.title}” ({outcome})")
        if ch.rollback_plan:
            lines.append(f"  Rollback used: {ch.rollback_plan[:200]}")
    return "\n".join(lines)


def _fallback_drafts(change: Change) -> dict[str, str]:
    names = ", ".join(s.name for s in change.systems) or "the target systems"
    window = ""
    if change.window_start:
        fmt = change.window_start.strftime("%a %d %b %H:%M")
        end = change.window_end.strftime("%H:%M") if change.window_end else "?"
        window = f" during the window {fmt}–{end}"
    return {
        "rollback_plan": (
            f"## Rollback plan — {change.title}\n\n"
            f"1. Stop the change activity on {names} and confirm the failure scope.\n"
            f"2. Restore the pre-change snapshot/backup taken before the window.\n"
            f"3. Re-deploy the previous known-good version/config to {names}.\n"
            f"4. Run smoke checks (health endpoints, one end-to-end transaction).\n"
            f"5. If not restored within 30 minutes, escalate to the service owner and declare the window failed."
        ),
        "test_plan": (
            f"## Test checklist — {change.title}\n\n"
            f"1. Pre-check: backups and snapshots of {names} verified.\n"
            f"2. Apply the change in {change.risk_type} mode{window}.\n"
            f"3. Health checks: service endpoints return 200 on {names}.\n"
            f"4. Functional check: run one end-to-end business transaction.\n"
            f"5. Watch error rate and latency dashboards for 15 minutes."
        ),
        "comms_plan": (
            f"## Stakeholder comms — {change.title}\n\n"
            f"- **T-24h**: post the change notice for {names} in #it-ops and the affected team channels.\n"
            f"- **T-1h**: reminder with the exact window{window} and expected impact.\n"
            f"- **On completion**: post success summary; if the rollback path is used, notify stakeholders within 10 minutes.\n"
            f"- **Owner**: {change.owner.name if change.owner else 'change owner'} replies to questions during the window."
        ),
    }


def _extract_json(text: str) -> dict | None:
    text = re.sub(r"```(?:json)?", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def draft_change_docs(db: Session, change: Change) -> dict:
    """Generate drafts. Returns {"ai_used": bool, "engine": str, "drafts": {...}}."""
    names = ", ".join(s.name for s in change.systems) or "the target systems"
    used_ai = False
    drafts: dict[str, str] = {}

    if config.ANTHROPIC_API_KEY:
        try:
            prompt = (
                f"Change title: {change.title}\n"
                f"Description: {change.description or '(none)'}\n"
                f"Risk class: {change.risk_type}\n"
                f"Systems affected: {names}\n"
                f"Window: {change.window_start} to {change.window_end}\n"
                f"{_similarity_context(db, change)}"
            )
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": config.ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": config.CLAUDE_MODEL,
                    "max_tokens": config.AI_MAX_OUTPUT_TOKENS,
                    "system": SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=45,
            )
            resp.raise_for_status()
            text = "".join(
                block.get("text", "") for block in resp.json().get("content", [])
            )
            parsed = _extract_json(text)
            if parsed and all(k in parsed for k in ("rollback_plan", "test_plan", "comms_plan")):
                drafts = {k: str(parsed[k]) for k in ("rollback_plan", "test_plan", "comms_plan")}
                used_ai = True
        except Exception:
            used_ai = False  # fall through to template

    if not drafts:
        drafts = _fallback_drafts(change)

    change.ai_rollback_draft = drafts["rollback_plan"]
    change.ai_test_draft = drafts["test_plan"]
    change.ai_comms_draft = drafts["comms_plan"]
    log_action(
        db,
        "change",
        change.id,
        "ai_draft_generated",
        actor="ai",
        detail=f"engine={'claude' if used_ai else 'template'}; drafts stored for human review",
    )
    return {"ai_used": used_ai, "engine": "claude" if used_ai else "template", "drafts": drafts}
