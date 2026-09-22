"""Real Slack integration.

Phase-2 week 2: the demo outbox stays the source of truth; this module is the
transport that mirrors it into a real Slack workspace.

- Settings helpers (bot token / signing secret live in the DB `settings` table
  so a reinstall needs no redeploy; env vars bootstrap).
- Signature verification for `POST /api/slack/interactions` (HMAC, ±5 min).
- OAuth install (oauth.v2.access) behind /api/integrations/slack/install.
- Outbound DMs via chat.postMessage; message updates via chat.update.
- Inbound approve/reject actions resolve through services.record_approval with
  source="slack" — the same any-of policy as the web app.

Slack being unreachable must never break the workflow: every network call is
wrapped and its failure recorded on the outbox row (delivery audit).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime
from urllib.parse import parse_qsl
from urllib.request import Request, urlopen

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .audit import log_action
from .models import Approval, Change, Notification, Setting, User

SETTINGS_KEY = "slack"

SCOPES = ("chat:write", "im:read", "im:history", "users:read", "users:read.email")


# ---------- settings ----------

def get_settings(db: Session) -> dict:
    row = db.get(Setting, SETTINGS_KEY)
    data = dict(row.value) if row and row.value else {}
    # Env vars bootstrap; DB settings win once installed via OAuth.
    data.setdefault("bot_token", config.SLACK_BOT_TOKEN)
    data.setdefault("signing_secret", config.SLACK_SIGNING_SECRET)
    return data


def save_settings(db: Session, **fields) -> None:
    row = db.get(Setting, SETTINGS_KEY)
    if row is None:
        row = Setting(key=SETTINGS_KEY, value={})
        db.add(row)
    value = dict(row.value or {})
    value.update(fields)
    row.value = value
    db.flush()


def is_connected(db: Session) -> bool:
    s = get_settings(db)
    return bool(s.get("bot_token")) and bool(s.get("team_id"))


# ---------- signature verification ----------

def verify_signature(signing_secret: str, timestamp: str, body: bytes, signature: str) -> bool:
    """Slack's v0 signing scheme: HMAC-SHA256 over `v0:ts:body`."""
    if not signing_secret or not timestamp or not signature:
        return False
    try:
        if abs(time.time() - int(timestamp)) > 300:  # replay window: ±5 minutes
            return False
    except ValueError:
        return False
    basestring = f"v0:{timestamp}:{body.decode('utf-8', 'replace')}"
    expected = "v0=" + hmac.new(signing_secret.encode(), basestring.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


# ---------- OAuth install ----------

def oauth_access_url(client_id: str, redirect_uri: str, state: str) -> str:
    from urllib.parse import urlencode

    params = urlencode({
        "client_id": client_id,
        "scope": ",".join(SCOPES),
        "redirect_uri": redirect_uri,
        "state": state,
    })
    return f"https://slack.com/oauth/v2/authorize?{params}"


def exchange_oauth_code(code: str, redirect_uri: str) -> dict:
    """Exchange an OAuth code for a bot token. Raises RuntimeError on failure."""
    data = _slack_form_post(
        "https://slack.com/api/oauth.v2.access",
        token=None,
        fields={
            "code": code,
            "client_id": config.SLACK_CLIENT_ID,
            "client_secret": config.SLACK_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
        },
    )
    if not data.get("ok"):
        raise RuntimeError(f"Slack OAuth exchange failed: {data.get('error', 'unknown')}")
    return data


# ---------- Slack Web API client (minimal, stdlib only) ----------

def _slack_form_post(url: str, token: str | None, fields: dict) -> dict:
    from urllib.parse import urlencode

    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, data=urlencode(fields).encode(), headers=headers, method="POST")
    try:
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:  # network errors become API-shaped failures
        return {"ok": False, "error": f"network: {exc}"}


def api_call(db: Session, method: str, fields: dict) -> dict:
    token = get_settings(db).get("bot_token")
    if not token:
        return {"ok": False, "error": "not_installed"}
    return _slack_form_post(f"https://slack.com/api/{method}", token, fields)


# ---------- outbound message conversion ----------

def to_block_kit(message: dict) -> list[dict]:
    """Convert the demo outbox payload into real Slack Block Kit blocks."""
    blocks: list[dict] = []
    for block in message.get("blocks", []):
        btype = block.get("type")
        if btype == "section":
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": block.get("text", "")}})
        elif btype == "context":
            fields = block.get("fields", {})
            lines = [f"*{k}:* {v}" for k, v in fields.items()]
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}})
        elif btype == "risk_why":
            items = block.get("items", [])
            lines = [f"• {i['label']} ({i['points']:+d})" for i in items]
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Why this score*\n" + "\n".join(lines)}})
        elif btype == "actions" and not message.get("acted"):
            elements = [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": action.get("label", action["action"])},
                    "style": "primary" if action.get("style") == "primary" else "danger",
                    "action_id": f"rc_{action['action']}",
                    "value": str(action.get("approval_id", "")),
                }
                for action in block.get("actions", [])
            ]
            blocks.append({"type": "actions", "elements": elements})
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "RicozChange · change management"}]})
    return blocks


def find_notification_by_ts(db: Session, channel: str, ts: str) -> Notification | None:
    return db.execute(
        select(Notification).where(Notification.slack_channel == channel, Notification.slack_ts == ts)
    ).scalars().first()


def autolink_by_email(db: Session, slack_user_id: str) -> User | None:
    """First Slack action by an unmapped user: look up their workspace email
    (users:read.email scope) and link it to the RicozChange account with the
    same email. Returns the linked user, or None if no email match exists."""
    info = api_call(db, "users.info", {"user": slack_user_id})
    email = ((info.get("user") or {}).get("profile") or {}).get("email", "").lower()
    if not email:
        return None
    from sqlalchemy import func

    user = db.execute(select(User).where(func.lower(User.email) == email)).scalars().first()
    if user is not None:
        user.slack_id = slack_user_id
        db.flush()
    return user


# ---------- delivery ----------

def deliver_pending(db: Session) -> int:
    """Send every queued, undelivered approval DM to mapped approvers.

    The outbox row remains the source of truth; Slack transport state is
    recorded on the row (sent_at / slack_ts / delivery_error).
    """
    settings = get_settings(db)
    if not settings.get("bot_token"):
        return 0

    rows = db.execute(
        select(Notification)
        .where(Notification.sent_at.is_(None), Notification.delivery_error.is_(None), Notification.acted.is_(False))
        .order_by(Notification.id)
    ).scalars().all()

    sent = 0
    for note in rows:
        if note.approval_id is None:
            continue
        approval = db.get(Approval, note.approval_id)
        if approval is None:
            continue
        user = db.get(User, approval.approver_id)
        if user is None or not user.slack_id:
            note.delivery_error = "approver has no linked slack_id"
            continue
        change = db.get(Change, note.change_id) if note.change_id else None
        if change is None:
            note.delivery_error = "change missing"
            continue

        result = api_call(db, "chat.postMessage", {
            "channel": user.slack_id,
            "text": note.message.get("text", f"Approval needed: change #{change.id}"),
            "blocks": json.dumps(to_block_kit(note.message)),
        })
        if result.get("ok"):
            note.sent_at = datetime.now()
            note.slack_channel = result.get("channel", user.slack_id)
            note.slack_ts = result.get("ts")
            sent += 1
        else:
            note.delivery_error = str(result.get("error", "unknown"))[:400]
    db.flush()
    return sent


# ---------- inbound interactions ----------

def handle_interaction(db: Session, payload: dict) -> dict:
    """Resolve a Slack block action into the existing approval service."""
    actions = (payload.get("actions") or [])
    if not actions:
        return {"text": "No action recognized."}
    action = actions[0]
    action_id = action.get("action_id", "")
    if action_id not in ("rc_approve", "rc_reject"):
        return {"text": "Unknown action."}
    decision = "approved" if action_id == "rc_approve" else "rejected"

    message = payload.get("message") or {}
    user = payload.get("user") or {}
    slack_user_id = user.get("id", "")
    channel = message.get("channel") or payload.get("channel", {}).get("id", "")
    ts = message.get("ts", "")

    note = find_notification_by_ts(db, channel, ts)
    if note is None:
        return {"text": "This approval request is no longer tracked by RicozChange (unknown message)."}

    actor = db.execute(select(User).where(User.slack_id == slack_user_id)).scalars().first()
    if actor is None and slack_user_id:
        actor = autolink_by_email(db, slack_user_id)
    if actor is None:
        return {
            "response_type": "ephemeral",
            "replace_original": False,
            "text": f"⚠️ Your Slack account isn't linked to a RicozChange user. Ask an admin to link `{slack_user_id}` to your account (emails must match).",
        }

    approval = db.get(Approval, note.approval_id) if note.approval_id else None
    change = db.get(Change, note.change_id) if note.change_id else None
    if approval is None or change is None:
        return {"text": "The underlying approval or change no longer exists."}

    if note.acted or approval.decision != "pending":
        return {
            "response_type": "ephemeral",
            "replace_original": False,
            "text": f"This change was already resolved (status: {change.status}).",
        }
    if approval.approver_id != actor.id:
        return {
            "response_type": "ephemeral",
            "replace_original": False,
            "text": f"This approval is assigned to {approval.approver.name}, not you.",
        }

    from . import services

    services.record_approval(db, change, approval, decision, comment="from Slack", source="slack")
    note.acted = True
    note.acted_action = decision
    log_action(db, "notification", note.id, f"slack_{decision}", actor=actor.name, detail="from Slack interaction")

    # Update the original message so buttons disappear and the decision shows.
    who = actor.name
    if message.get("ts"):
        blocks = to_block_kit(note.message)
        api_call(db, "chat.update", {
            "channel": channel,
            "ts": ts,
            "text": f"{decision.capitalize()} by {who}",
            "blocks": json.dumps([
                {"type": "section", "text": {"type": "mrkdwn",
                    "text": f"{':white_check_mark:' if decision == 'approved' else ':x:'} *{decision.capitalize()} by {who}* — change #{change.id} “{change.title}” is now `{change.status}`."}},
                {"type": "context", "elements": [{"type": "mrkdwn", "text": "RicozChange · change management"}]},
            ]),
        })

    db.flush()
    return {"text": f"Change #{change.id} {decision}."}


def parse_interaction_body(body: bytes) -> dict:
    """Slack interactions arrive as application/x-www-form-urlencoded `payload=...`."""
    parsed = dict(parse_qsl(body.decode("utf-8", "replace")))
    raw = parsed.get("payload", "{}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}
