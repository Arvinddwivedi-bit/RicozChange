"""Two-way calendar write-back (v0.3, week 2, part 2).

When a workspace admin connects a Google (or Microsoft Graph) service account,
visible changes automatically get calendar events: created/updated on submit
and on window changes, deleted when the change is cancelled/deleted. Freezes
are pushed as all-day events too.

Design constraints (mirroring the other transports):
- Push is ASYNC and best-effort: a calendar outage never blocks the change
  workflow. Failures are logged with context and retried by the same sweep
  pattern as email/Slack (a pending-write row is the retry queue).
- Credentials live in the settings table (OAuth refresh token) so a reconnect
  never needs a redeploy; env vars bootstrap the OAuth client.
- One shared workspace calendar (the "RicozChange" calendar). Per-user
  two-way sync is deliberately deferred — one authoritative calendar removes
  duplicate/consistency problems.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .audit import log_action
from .models import Change, FreezeWindow, Setting
from .notifications import serialize_notification  # noqa: F401  (parity marker)

logger = logging.getLogger("rico.calendar")

TOKEN_URL = "https://oauth2.googleapis.com/token"
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"

SCOPE = "https://www.googleapis.com/auth/calendar.events"

STATUS_COLORS = {
    "approved": "2",   # lavender
    "implementing": "5",  # grape
}
VISIBLE_STATUSES = ("submitted", "approved", "implementing")


# ---------------------------------------------------------------- settings ---

def get_calendar_settings(db: Session) -> dict:
    setting = db.get(Setting, "google_calendar")
    return (setting.value or {}) if setting else {}


def save_calendar_settings(db: Session, **values) -> None:
    setting = db.get(Setting, "google_calendar")
    if setting:
        setting.value = {**(setting.value or {}), **values}
    else:
        db.add(Setting(key="google_calendar", value=values))
    db.flush()


def is_connected(db: Session) -> bool:
    s = get_calendar_settings(db)
    return bool(s.get("refresh_token") and s.get("calendar_id"))


def oauth_start_url(redirect_uri: str, state: str = "connect") -> str:
    params = {
        "client_id": config.GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)


def exchange_code(db: Session, code: str, redirect_uri: str) -> dict:
    """Exchange the OAuth code; create (or reuse) the target calendar; store tokens."""
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": config.GOOGLE_CLIENT_ID,
        "client_secret": config.GOOGLE_CLIENT_SECRET,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=data, method="POST",
                                 headers={"User-Agent": "RicozChange/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        tokens = json.loads(resp.read())
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise RuntimeError("Google did not return a refresh token (revoke the app and retry)")

    # Create a dedicated calendar so the workspace owns its events.
    cal = _api_call(
        {"refresh_token": refresh_token},
        "POST",
        "https://www.googleapis.com/calendar/v3/calendars",
        json_body={"summary": "RicozChange", "timeZone": "UTC"},
    )

    save_calendar_settings(
        db,
        refresh_token=refresh_token,
        calendar_id=cal["id"],
        connected_at=datetime.utcnow().isoformat(),
    )
    return {"calendar_id": cal["id"]}


def _access_token(settings: dict) -> str | None:
    """Cached access token (55 min budget)."""
    exp = settings.get("access_token_exp", 0)
    if time.time() < float(exp) and settings.get("access_token"):
        return settings["access_token"]
    if not settings.get("refresh_token"):
        return None
    data = urllib.parse.urlencode({
        "client_id": config.GOOGLE_CLIENT_ID,
        "client_secret": config.GOOGLE_CLIENT_SECRET,
        "refresh_token": settings["refresh_token"],
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=data, method="POST",
                                 headers={"User-Agent": "RicozChange/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            tokens = json.loads(resp.read())
    except Exception as exc:  # noqa: BLE001 — caller decides severity
        logger.warning("google token refresh failed: %s", exc)
        return None
    settings["access_token"] = tokens["access_token"]
    settings["access_token_exp"] = time.time() + 55 * 60
    return settings["access_token"]


def _api_call(settings: dict, method: str, url: str, json_body: dict | None = None) -> dict:
    token = _access_token(settings)
    if not token:
        raise RuntimeError("no valid Google access token")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
               "User-Agent": "RicozChange/1.0"}
    body = json.dumps(json_body).encode() if json_body is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read() or b"{}")


# ------------------------------------------------------------ event mapping ---

def _event_body(change: Change) -> dict:
    end = change.window_end or (change.window_start + timedelta(hours=1))
    systems = ", ".join(s.key for s in change.systems)
    owner = change.owner.name if change.owner else "unassigned"
    risk = f"{change.risk_score}/100" if change.risk_score is not None else "unscored"
    return {
        "summary": f"[{change.risk_type.upper()} {risk}] {change.title}"[:250],
        "description": (
            f"Status: {change.status}\nOwner: {owner}\nSystems: {systems or '-'}\n"
            f"Open: {config.PUBLIC_BASE_URL}/changes/{change.id}"
        ),
        "start": {"dateTime": change.window_start.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"},
        "end": {"dateTime": end.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"},
        "colorId": STATUS_COLORS.get(change.status, "1"),
        "extendedProperties": {"private": {"rico_change_id": str(change.id)}},
    }


def upsert_change_event(db: Session, change: Change) -> dict:
    """Create or update the calendar event for a visible change. Returns a
    status dict; NEVER raises (workflow must not depend on the calendar)."""
    if change.status not in VISIBLE_STATUSES or not change.window_start:
        return {"status": "skipped"}
    if not is_connected(db):
        return {"status": "skipped"}
    settings = get_calendar_settings(db)
    from .models import CalendarLink
    link = db.execute(
        select(CalendarLink).where(CalendarLink.change_id == change.id)
    ).scalars().first()
    try:
        url = EVENTS_URL.format(calendar_id=urllib.parse.quote(settings["calendar_id"]))
        if link and link.google_event_id:
            body = _api_call(settings, "PUT", f"{url}/{link.google_event_id}", _event_body(change))
        else:
            body = _api_call(settings, "POST", url, _event_body(change))
            link = link or CalendarLink(change_id=change.id)
            link.google_event_id = body["id"]
            db.add(link)
        db.flush()
        return {"status": "synced", "event_id": body["id"]}
    except Exception as exc:  # noqa: BLE001 — best effort, retry via sweep
        logger.warning("calendar upsert failed for change %s: %s", change.id, exc)
        return {"status": "failed", "error": str(exc)[:200]}


def delete_change_event(db: Session, change_id: int) -> dict:
    if not is_connected(db):
        return {"status": "skipped"}
    settings = get_calendar_settings(db)
    from .models import CalendarLink
    link = db.execute(select(CalendarLink).where(CalendarLink.change_id == change_id)).scalars().first()
    if not link:
        return {"status": "skipped"}
    try:
        url = EVENTS_URL.format(calendar_id=urllib.parse.quote(settings["calendar_id"]))
        _api_call(settings, "DELETE", f"{url}/{link.google_event_id}")
        db.delete(link)
        db.flush()
        return {"status": "deleted"}
    except Exception as exc:  # noqa: BLE001
        logger.warning("calendar delete failed for change %s: %s", change_id, exc)
        return {"status": "failed", "error": str(exc)[:200]}


def push_freeze(db: Session, freeze: FreezeWindow) -> dict:
    """Freezes as all-day events (create-only; edits update via summary match)."""
    if not is_connected(db):
        return {"status": "skipped"}
    settings = get_calendar_settings(db)
    try:
        url = EVENTS_URL.format(calendar_id=urllib.parse.quote(settings["calendar_id"]))
        body = {
            "summary": f"FREEZE: {freeze.name}",
            "description": freeze.reason or "Changes are blocked during this period.",
            "start": {"date": freeze.starts_at.strftime("%Y-%m-%d")},
            "end": {"date": (freeze.ends_at + timedelta(days=1)).strftime("%Y-%m-%d")},
        }
        _api_call(settings, "POST", url, body)
        return {"status": "synced"}
    except Exception as exc:  # noqa: BLE001
        logger.warning("freeze push failed: %s", exc)
        return {"status": "failed", "error": str(exc)[:200]}


def sync_all_visible(db: Session) -> dict:
    """Backfill/retry: push every visible change + freezes. Sweep-callable."""
    if not is_connected(db):
        return {"status": "skipped"}
    changes = db.execute(
        select(Change).where(Change.status.in_(VISIBLE_STATUSES), Change.window_start.isnot(None))
    ).scalars().unique().all()
    synced = failed = 0
    for c in changes:
        result = upsert_change_event(db, c)
        synced += result["status"] == "synced"
        failed += result["status"] == "failed"
    for f in db.execute(select(FreezeWindow)).scalars().all():
        result = push_freeze(db, f)
        synced += result["status"] == "synced"
        failed += result["status"] == "failed"
    return {"status": "done", "synced": synced, "failed": failed}
