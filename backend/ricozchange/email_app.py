"""Email-to-change + automated email notifications (phase 2, week 3).

Inbound: an engineer emails a mailbox; a deterministic parser extracts title,
systems, window, change type and rollback plan; the pipeline files a DRAFT
change (never submits), scores it with the standard risk engine, records the
EmailInbound audit row and returns a plain-text reply with the score and the
full "why". Safety rules: unknown systems or garbage -> nothing filed, helpful
reply; the same Message-ID never files twice; sender-domain allowlist; inbound
email can never approve anything.

Outbound (transport stub): emails are recorded as Notification(kind="email")
rows — the auditable outbox. Swapping in real SMTP/SendGrid sending later means
replacing one function (`send_email`), callers don't change.

The sweep: post-change "did it work?" prompts, daily pending-approval digests,
and email fallbacks for Slack notifications whose delivery failed.
"""
from __future__ import annotations

import hmac
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config
from .audit import log_action
from .models import Approval, Change, EmailInbound, Notification, Setting, SystemNode, User
from .risk_engine import score_and_persist

WEBHOOK_URL = "/api/integrations/email/inbound"

_TOKEN_DT = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}")
_TOKEN_TIME = re.compile(r"(?<![\d:]\s)\b\d{2}:\d{2}\b")


# ---------------------------------------------------------------- parsing ---

@dataclass
class ParsedEmail:
    title: str = ""
    description: str = ""
    system_keys: list[str] = field(default_factory=list)
    risk_type: str = "normal"
    rollback_plan: str = ""
    window_start: datetime | None = None
    window_end: datetime | None = None
    window_raw: str = ""
    problems: list[str] = field(default_factory=list)


def _parse_window(raw: str) -> tuple[datetime | None, datetime | None, list[str]]:
    """Accept 'YYYY-MM-DD HH:MM - YYYY-MM-DD HH:MM', '... - HH:MM' (same/cross
    midnight), or a single 'YYYY-MM-DD HH:MM' (1h window). Deterministic."""
    problems: list[str] = []
    cleaned = raw.strip().strip("'\"")
    cleaned = cleaned.replace("–", "-").replace("—", "-")
    cleaned = re.sub(r"\s+-\s+", "-", cleaned)  # normalize separators

    full = _TOKEN_DT.findall(cleaned)
    times = [t for t in _TOKEN_TIME.findall(cleaned) if not any(t in f for f in full)]

    def _dt(tok: str) -> datetime:
        return datetime.fromisoformat(tok.replace("T", " "))

    try:
        if len(full) >= 2:
            start, end = _dt(full[0]), _dt(full[1])
        elif len(full) == 1 and times:
            start = _dt(full[0].replace("T", " "))
            hh, mm = times[0].split(":")
            end = start.replace(hour=int(hh), minute=int(mm))
            if end <= start:
                end += timedelta(days=1)
        elif len(full) == 1:
            start = _dt(full[0].replace("T", " "))
            end = start + timedelta(hours=1)
        else:
            return None, None, [f"could not read a date/time from '{raw.strip()}'"]
    except ValueError as exc:
        return None, None, [f"bad date/time in '{raw.strip()}' ({exc})"]

    if end <= start:
        problems.append("window end was before start; ignored the window")
        return start, None, problems
    return start, end, problems


def parse_email(subject: str, body: str) -> ParsedEmail:
    """Deterministic keyword parser. Unknown lines become the description."""
    out = ParsedEmail(title=(subject or "").strip()[:200])
    desc_lines: list[str] = []
    for raw_line in (body or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        low = line.lower()
        if low.startswith("systems:"):
            out.system_keys = [
                k.strip().lower() for k in line.split(":", 1)[1].split(",") if k.strip()
            ]
        elif low.startswith("window:"):
            out.window_raw = line.split(":", 1)[1]
            out.window_start, out.window_end, probs = _parse_window(out.window_raw)
            out.problems.extend(probs)
        elif low.startswith("type:"):
            val = line.split(":", 1)[1].strip().lower()
            out.risk_type = val if val in ("standard", "normal", "major", "emergency") else "normal"
        elif low.startswith("rollback:"):
            out.rollback_plan = line.split(":", 1)[1].strip()
        else:
            desc_lines.append(line)
    out.description = "\n".join(desc_lines).strip()
    return out


def sender_domain(addr: str) -> str:
    return addr.rsplit("@", 1)[-1].strip().lower() if "@" in addr else ""


def domain_allowed(from_addr: str) -> bool:
    if not config.EMAIL_ALLOWED_DOMAINS:
        return True  # empty allowlist = demo mode, allow all
    return sender_domain(from_addr) in config.EMAIL_ALLOWED_DOMAINS


def verify_webhook_key(provided: str | None) -> bool:
    """Shared-secret check for the inbound webhook (constant-time).

    SendGrid Inbound Parse appends our query params to the POST, so the secret
    rides in the configured URL. When EMAIL_WEBHOOK_KEY is empty, verification
    is off (demo mode).
    """
    if not config.EMAIL_WEBHOOK_KEY:
        return True
    return bool(provided) and hmac.compare_digest(provided, config.EMAIL_WEBHOOK_KEY)


# -------------------------------------------------------------- the reply ---

def _fmt_window(change: Change) -> str:
    if not change.window_start:
        return "not set (you can add one in the web app)"
    end = change.window_end or (change.window_start + timedelta(hours=1))
    return f"{change.window_start:%Y-%m-%d %H:%M} - {end:%H:%M} UTC"


def build_reply(change: Change) -> str:
    factors = change.factors or []
    why = "\n".join(f"    {f.points:+d}  {f.label}" for f in factors) or "    (no scored factors)"
    systems = ", ".join(s.key for s in change.systems) or "-"
    return (
        "RicozChange received your change request.\n"
        f"\n  Title:   {change.title}"
        f"\n  Risk:    {change.risk_score}/100"
        f"\n  Why:\n{why}"
        f"\n  Window:  {_fmt_window(change)}"
        f"\n  Systems: {systems}"
        "\n\nThe change was filed as a DRAFT — it is NOT scheduled yet."
        "\nOpen it, review the score, and submit it for approval:"
        f"\n{config.PUBLIC_BASE_URL}/changes/{change.id}"
    )


def build_reject_reply(reason: str, known_systems: list[str] | None = None) -> str:
    extra = ""
    if known_systems:
        extra = "\n  Known systems: " + ", ".join(known_systems)
    return (
        "RicozChange could not file your change request.\n"
        f"\n  Reason: {reason}{extra}"
        "\n\nNothing was filed. Fix the issue and send the email again."
        "\nFormat: subject = title; body lines: systems:, window:, type:, rollback:"
    )


# --------------------------------------------------------- inbound pipeline ---

def process_inbound(
    db: Session, *, message_id: str, from_addr: str, subject: str, body: str
) -> tuple[dict, EmailInbound]:
    """The full inbound pipeline. Returns (result, audit_row). Commits stay with
    the caller. result: {status: created|rejected|duplicate, change_id, reply}."""

    # 1. Message-ID dedupe: the same email is never processed twice.
    mid = (message_id or f"<{datetime.utcnow().isoformat()}@rico.local>").strip()
    existing = db.execute(select(EmailInbound).where(EmailInbound.message_id == mid)).scalars().first()
    if existing:
        return (
            {"status": "duplicate", "change_id": existing.parsed_change_id, "reply": ""},
            existing,
        )

    # 2. Sender-domain allowlist.
    if not domain_allowed(from_addr):
        row = EmailInbound(
            message_id=mid, from_addr=from_addr[:200], subject=(subject or "")[:500],
            body=body or "", status="rejected",
            error_detail=f"sender domain '{sender_domain(from_addr)}' is not allowed",
        )
        db.add(row)
        db.flush()
        return (
            {
                "status": "rejected",
                "change_id": None,
                "reply": build_reject_reply("your email domain is not allowed to file changes"),
            },
            row,
        )

    # 3. Parse.
    parsed = parse_email(subject, body)
    title = parsed.title or "(no subject)"

    # 4. Resolve systems; unknown ones reject the whole email (never guess).
    nodes: list[SystemNode] = []
    unknown: list[str] = []
    if parsed.system_keys:
        found = {
            n.key.lower(): n
            for n in db.execute(
                select(SystemNode).where(func.lower(SystemNode.key).in_(parsed.system_keys))
            ).scalars().all()
        }
        unknown = [k for k in parsed.system_keys if k not in found]
        nodes = [found[k] for k in parsed.system_keys if k in found]
    if parsed.system_keys and unknown:
        known = [k for (k,) in db.execute(select(SystemNode.key).order_by(SystemNode.key)).all()]
        reason = "unknown system(s): " + ", ".join(unknown)
        row = EmailInbound(
            message_id=mid, from_addr=from_addr[:200], subject=(subject or "")[:500],
            body=body or "", status="rejected", error_detail=reason,
        )
        db.add(row)
        db.flush()
        return ({"status": "rejected", "change_id": None, "reply": build_reject_reply(reason, known)}, row)

    # 5. Match the sender to a user (owner). Unmatched senders file ownerless drafts.
    owner = db.execute(
        select(User).where(func.lower(User.email) == from_addr.strip().lower())
    ).scalars().first()

    # 6. File the DRAFT and score it with the standard engine.
    change = Change(
        title=title,
        description=(parsed.description or "Filed by email.")[:8000],
        risk_type=parsed.risk_type,
        status="draft",
        owner_id=owner.id if owner else None,
        window_start=parsed.window_start,
        window_end=parsed.window_end,
        rollback_plan=parsed.rollback_plan,
    )
    change.systems = nodes
    db.add(change)
    db.flush()
    score_and_persist(db, change)
    actor = owner.name if owner else f"{from_addr} (unmapped)"
    log_action(db, "change", change.id, "created", actor=actor, detail=f"via email: {title}")

    row = EmailInbound(
        message_id=mid, from_addr=from_addr[:200], subject=(subject or "")[:500],
        body=body or "", status="created", parsed_change_id=change.id,
    )
    db.add(row)
    db.flush()
    db.refresh(change)
    return ({"status": "created", "change_id": change.id, "reply": build_reply(change)}, row)


# ------------------------------------------------------------- outbound -----

def send_email(db: Session, *, to_addr: str, subject: str, body: str, change_id: int | None = None) -> Notification:
    """Record an outbound email in the auditable outbox.

    Transport stub: real SMTP/SendGrid sending is a one-line swap here; every
    caller already treats delivery as best-effort.
    """
    note = Notification(
        kind="email",
        channel=to_addr,
        change_id=change_id,
        message={"subject": subject[:200], "text": body[:4000]},
    )
    db.add(note)
    db.flush()
    return note


def _daily_digest_marker(db: Session, user_id: int) -> str | None:
    setting = db.get(Setting, f"email_digest:{user_id}")
    return (setting.value or {}).get("last_sent_date") if setting else None


def _set_daily_digest_marker(db: Session, user_id: int, day: str) -> None:
    setting = db.get(Setting, f"email_digest:{user_id}")
    if setting:
        setting.value = {**(setting.value or {}), "last_sent_date": day}
    else:
        db.add(Setting(key=f"email_digest:{user_id}", value={"last_sent_date": day}))


def run_email_sweep(db: Session) -> dict:
    """One sweep pass: post-change prompts, approval digests, Slack fallbacks.
    Every stage is independent — one failure never blocks the others."""
    counts = {"post_change_prompts": 0, "digests": 0, "slack_fallbacks": 0}
    now = datetime.utcnow()

    # 1. "Did it work?" prompts — once per change, after the window closed.
    try:
        due = db.execute(
            select(Change).where(
                Change.status.in_(("completed", "failed")),
                Change.post_change_result.is_(None),
                Change.post_change_prompted_at.is_(None),
                Change.window_end.isnot(None),
                Change.window_end <= now,
            )
        ).scalars().all()
        for change in due:
            owner = change.owner
            if not owner:
                continue
            send_email(
                db,
                to_addr=owner.email,
                subject=f"Did change #{change.id} work?",
                body=(
                    f"Change #{change.id} \"{change.title}\" finished its window at "
                    f"{change.window_end:%Y-%m-%d %H:%M} UTC.\n\n"
                    "Open the change and record the post-change check "
                    "(success / partial / failed) — it feeds the team's failure-rate dashboard:\n"
                    f"{config.PUBLIC_BASE_URL}/changes/{change.id}"
                ),
                change_id=change.id,
            )
            change.post_change_prompted_at = now
            counts["post_change_prompts"] += 1
        db.flush()
    except Exception:  # noqa: BLE001 — sweep stages must never break each other
        db.rollback()

    # 2. Daily pending-approval digest, one per approver per day.
    try:
        today = now.strftime("%Y-%m-%d")
        rows = db.execute(
            select(Approval).where(Approval.decision == "pending")
        ).scalars().unique().all()
        by_approver: dict[int, list[Approval]] = {}
        for ap in rows:
            if ap.change is None or ap.change.status != "submitted":
                continue
            by_approver.setdefault(ap.approver_id, []).append(ap)
        for approver_id, approvals in by_approver.items():
            if _daily_digest_marker(db, approver_id) == today:
                continue
            approver = db.get(User, approver_id)
            if not approver:
                continue
            lines = []
            for ap in approvals:
                c = ap.change
                lines.append(
                    f"  #{c.id}  risk {c.risk_score}/100  {c.title}\n"
                    f"        {config.PUBLIC_BASE_URL}/changes/{c.id}"
                )
            send_email(
                db,
                to_addr=approver.email,
                subject=f"[RicozChange] {len(approvals)} change(s) waiting for your approval",
                body=(
                    f"Changes waiting for your decision as of {today}:\n\n"
                    + "\n".join(lines)
                    + "\n\nYou can also approve straight from Slack if the app is installed."
                ),
                change_id=approvals[0].change_id,
            )
            _set_daily_digest_marker(db, approver_id, today)
            counts["digests"] += 1
        db.flush()
    except Exception:  # noqa: BLE001
        db.rollback()

    # 3. Email fallback for Slack notifications whose delivery failed.
    try:
        failed = db.execute(
            select(Notification).where(Notification.kind == "slack", Notification.delivery_error.isnot(None))
        ).scalars().unique().all()
        # Python-side dedupe (JSON contains are dialect-fragile): map which slack
        # note ids already have a fallback email, via the fallback_for marker.
        fallbacks = db.execute(select(Notification).where(Notification.kind == "email")).scalars().all()
        covered = {
            (n.message or {}).get("fallback_for") for n in fallbacks
        }
        for note in failed:
            if note.id in covered:
                continue
            to_addr = note.channel
            user = db.execute(select(User).where(User.slack_id == to_addr)).scalars().first()
            if not user:
                continue
            msg = note.message or {}
            send_email(
                db,
                to_addr=user.email,
                subject=msg.get("subject", "Approval request (Slack delivery failed)"),
                body=(
                    "Slack could not deliver this approval request, so it is repeated here.\n\n"
                    + str(msg.get("text", ""))[:3000]
                    + (f"\n\nOpen: {config.PUBLIC_BASE_URL}/changes/{note.change_id}" if note.change_id else "")
                ),
                change_id=note.change_id,
            )
            note.message = {**(note.message or {}), "fallback_for": note.id}
            counts["slack_fallbacks"] += 1
        db.flush()
    except Exception:  # noqa: BLE001
        db.rollback()

    return counts
