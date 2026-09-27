"""Calendar feed (v0.3, week 2) — read-only .ics of change windows and freezes.

RFC 5545 output that subscribes cleanly in Google Calendar and Outlook:
- One VCALENDAR with VEVENTs for scheduled changes (submitted/approved/
  implementing) and freeze windows (as all-day events).
- Text escaping per §3.4 (backslash, semicolon, comma, newline), CRLF line
  endings, UTC timestamps with Z suffix.
- UID per event (stable: change-<id>@ricozchange / freeze-<id>@ricozchange) so
  calendar clients update in place instead of duplicating on re-fetch.
- No external dependencies — the feed alone delivers most of the week's value.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .models import Change, FreezeWindow

CAL_DOMAIN = "ricozchange"

VISIBLE_STATUSES = ("submitted", "approved", "implementing")

STATUS_SUMMARY = {
    "submitted": "awaiting approval",
    "approved": "approved",
    "implementing": "in progress",
}


def _esc(text: str) -> str:
    """RFC 5545 §3.4 escaping, applied to every TEXT property value."""
    return (
        (text or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _dt_utc(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _fold(line: str) -> list[str]:
    """RFC 5545 §3.1 content lines must not exceed 75 octets; fold with CRLF + space."""
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return [line]
    parts: list[str] = []
    chunk = b""
    limit = 75
    for ch in line:
        b = ch.encode("utf-8")
        if len(chunk) + len(b) > limit:
            parts.append(chunk.decode("utf-8"))
            chunk = b" " + b  # continuation lines start with a space
            limit = 75  # the leading space counts toward the octet budget
        else:
            chunk += b
    if chunk:
        parts.append(chunk.decode("utf-8"))
    return parts


def _event_lines(
    *, uid: str, summary: str, description: str, start: datetime, end: datetime | None,
    all_day: bool = False,
) -> list[str]:
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{_dt_utc(datetime.utcnow())}",
    ]
    if all_day:
        # DTSTART;VALUE=DATE:YYYYMMDD — one-day all-day event starting that day
        lines.append(f"DTSTART;VALUE=DATE:{start.strftime('%Y%m%d')}")
        lines.append(f"DTEND;VALUE=DATE:{(start + timedelta(days=1)).strftime('%Y%m%d')}")
    else:
        lines.append(f"DTSTART:{_dt_utc(start)}")
        lines.append(f"DTEND:{_dt_utc(end or (start + timedelta(hours=1)))}")
    lines.append(f"SUMMARY:{_esc(summary)}")
    if description:
        lines.append(f"DESCRIPTION:{_esc(description)}")
    lines.append("END:VEVENT")
    return lines


def build_change_calendar(db: Session, *, actor_name: str = "everyone") -> str:
    """The full feed: visible change windows + freezes, newest stamp first."""
    changes = db.execute(
        select(Change)
        .where(
            Change.status.in_(VISIBLE_STATUSES),
            Change.window_start.isnot(None),
        )
        .order_by(Change.window_start)
    ).scalars().unique().all()
    freezes = db.execute(select(FreezeWindow).order_by(FreezeWindow.starts_at)).scalars().all()

    out: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//RicozChange//Change Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:RicozChange — {config.PUBLIC_BASE_URL.split('//')[-1].split('.')[0]}",
        "X-WR-TIMEZONE:UTC",
    ]

    for c in changes:
        end = c.window_end or (c.window_start + timedelta(hours=1))
        systems = ", ".join(s.key for s in c.systems)
        state = STATUS_SUMMARY.get(c.status, c.status)
        risk = f"{c.risk_score}/100" if c.risk_score is not None else "unscored"
        owner = c.owner.name if c.owner else "unassigned"
        lines = _event_lines(
            uid=f"change-{c.id}@{CAL_DOMAIN}",
            summary=f"[{c.risk_type.upper()} {risk}] {c.title}",
            description=(
                f"Status: {state}\nOwner: {owner}\nSystems: {systems or '-'}\n"
                f"Open: {config.PUBLIC_BASE_URL}/changes/{c.id}"
            ),
            start=c.window_start,
            end=end,
        )
        out.extend(lines)

    for f in freezes:
        lines = _event_lines(
            uid=f"freeze-{f.id}@{CAL_DOMAIN}",
            summary=f"FREEZE: {f.name}",
            description=f.reason or "Changes are blocked during this period.",
            start=f.starts_at,
            end=None,
            all_day=True,
        )
        out.extend(lines)

    out.append("END:VCALENDAR")

    # CRLF join (RFC 5545 requires CRLF) with folding applied per line.
    physical: list[str] = []
    for line in out:
        physical.extend(_fold(line))
    return "\r\n".join(physical) + "\r\n"
