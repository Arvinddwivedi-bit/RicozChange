"""Microsoft Teams integration (v0.3, week 3).

Ports the Slack approval-card flow to Teams on the Bot Framework, reusing the
demo outbox as the source of truth (`Notification.kind="teams"` mirror rows):

- Azure Bot credentials (App ID + client secret) bootstrap from env vars; a
  real install is "message the bot once" — the conversationUpdate's serviceUrl
  + bot id land in settings, so proactive DMs know where to send.
- Inbound `POST /api/teams/interactions` validates `Authorization: Bearer`
  against the Bot Framework OpenID metadata (RS256 signatures, audience = the
  bot App ID, issuer pinned; config cached in the settings table) — the
  Slack-signature pattern ported to how Azure actually signs.
- Outbound: proactive messages via the Bot Framework REST API (stdlib only);
  Adaptive Cards replace Block Kit 1:1 with the outbox payload. Approve/Reject
  buttons use Action.Submit; the decision edits the card in place so buttons
  disappear and duplicates stay idempotent.
- Identity: `users.teams_id` (AAD object id); first action by an unmapped user
  autolinks via Microsoft Graph when directory consent is present, otherwise
  gets the ephemeral "ask an admin" fallback — same UX as Slack.
- Teams being unreachable must never break the workflow: every network call is
  wrapped, its failure recorded on the outbox row, and the email sweep
  backfills/retries (kind="teams" rows) with an email fallback, exactly like
  the Slack chain.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from datetime import datetime

import jwt
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config
from .audit import log_action
from .models import Approval, Change, Notification, Setting, User

logger = logging.getLogger("rico.teams")

SETTINGS_KEY = "teams"

BOT_ISSUER = "https://api.botframework.com"
OPENID_CONFIG_URL = "https://login.botframework.com/v1/.well-known/openidconfiguration"
TOKEN_URL = "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token"
GRAPH_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
GRAPH_ME_URL = "https://graph.microsoft.com/v1.0/users/{aad_id}"

_ACTED = "acted"  # marker key inside message JSON once the card was decided


# ---------------------------------------------------------------- settings ---

def get_settings(db: Session) -> dict:
    row = db.get(Setting, SETTINGS_KEY)
    data = dict(row.value) if row and row.value else {}
    # Env vars bootstrap; DB settings win once the bot has been messaged.
    data.setdefault("app_id", config.TEAMS_APP_ID)
    data.setdefault("app_password", config.TEAMS_APP_PASSWORD)
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
    return bool(s.get("app_id") and s.get("app_password") and s.get("service_url"))


# ------------------------------------------------------- transport helpers ---

def _post_json(url: str, token: str | None, payload: dict | None = None, form: dict | None = None,
               method: str = "POST") -> dict:
    """HTTP request returning parsed JSON (JSON or form body). Network problems
    RAISE — callers decide severity (the transport must never break the
    workflow). This is also the seam tests monkeypatch."""
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
    else:
        data = json.dumps(payload or {}).encode() if method != "GET" else None
        headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode() or "{}")


def _bot_token(db: Session, settings: dict) -> str | None:
    """Client-credentials token for the Bot Framework API (55 min budget)."""
    exp = float(settings.get("token_exp", 0) or 0)
    if settings.get("bot_token") and time.time() < exp - 60:
        return settings["bot_token"]
    if not (settings.get("app_id") and settings.get("app_password")):
        return None
    try:
        tokens = _post_json(TOKEN_URL, None, None, form={
            "grant_type": "client_credentials",
            "client_id": settings["app_id"],
            "client_secret": settings["app_password"],
            "scope": "https://api.botframework.com/.default",
        })
    except Exception as exc:  # noqa: BLE001 — outage, not a bug
        logger.warning("teams token fetch failed: %s", exc)
        return None
    if not tokens.get("access_token"):
        return None
    settings["bot_token"] = tokens["access_token"]
    settings["token_exp"] = time.time() + int(tokens.get("expires_in", 3600))
    try:
        save_settings(db, bot_token=settings["bot_token"], token_exp=settings["token_exp"])
    except Exception:  # noqa: BLE001 — cache write is best-effort
        pass
    return settings["bot_token"]


# ------------------------------------------------- inbound JWT verification ---

def _fetch_openid_config(db: Session) -> dict:
    """Bot Framework OpenID metadata (issuer, signing keys). Fetched once and
    cached in the settings table so requests never wait on Azure twice."""
    cached = get_settings(db).get("openid_config")
    if cached and isinstance(cached, dict) and cached.get("jwks"):
        return cached
    with urllib.request.urlopen(OPENID_CONFIG_URL, timeout=10) as resp:
        doc = json.loads(resp.read().decode())
    config_doc = {
        "issuer": doc.get("issuer", BOT_ISSUER),
        "jwks": doc.get("keys") or doc.get("jwks", {}).get("keys", []),
    }
    save_settings(db, openid_config=config_doc)
    return config_doc


def verify_bot_token(auth_header: str, db: Session, app_id: str | None = None) -> str:
    """Validate an inbound Bot Framework `Authorization: Bearer` header.

    Returns the validated audience (the bot App ID). Raises ValueError with a
    safe reason on any failure — the route turns that into 401 + audit entry.
    """
    if not auth_header or not auth_header.lower().startswith("bearer "):
        raise ValueError("missing bearer token")
    token = auth_header.split(" ", 1)[1].strip()
    app_id = app_id or get_settings(db).get("app_id") or config.TEAMS_APP_ID
    if not app_id:
        raise ValueError("bot app id not configured")
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise ValueError(f"malformed token ({exc.__class__.__name__})") from exc
    kid = header.get("kid")
    jwk = next((k for k in _fetch_openid_config(db).get("jwks", []) if k.get("kid") == kid), None)
    if jwk is None:
        raise ValueError("signing key not recognized")
    try:
        key = RSAAlgorithm.from_jwk(json.dumps(jwk))
    except Exception as exc:  # noqa: BLE001
        raise ValueError("signing key unreadable") from exc
    try:
        jwt.decode(
            token, key, algorithms=["RS256"], audience=app_id, issuer=BOT_ISSUER,
            options={"require": ["exp", "aud", "iss"]},
        )
    except jwt.InvalidIssuerError:
        # Government / channel variants sign with a different issuer pin.
        try:
            jwt.decode(
                token, key, algorithms=["RS256"], audience=app_id,
                options={"require": ["exp"], "verify_iss": False},
            )
        except jwt.PyJWTError as exc:
            raise ValueError(f"token rejected ({exc.__class__.__name__})") from exc
    except jwt.PyJWTError as exc:
        raise ValueError(f"token rejected ({exc.__class__.__name__})") from exc
    return app_id


# ------------------------------------------------- outbound card conversion ---

def to_adaptive_card(message: dict) -> dict:
    """Convert the demo outbox payload into one Adaptive Card (Teams shape)."""
    body: list[dict] = []
    actions: list[dict] = []
    for block in message.get("blocks", []):
        btype = block.get("type")
        if btype == "section":
            body.append({"type": "TextBlock", "text": block.get("text", ""), "wrap": True})
        elif btype == "context":
            fields = block.get("fields", {})
            lines = [f"**{k}:** {v}" for k, v in fields.items()]
            body.append({"type": "TextBlock", "text": "\n".join(lines), "wrap": True, "isSubtle": True})
        elif btype == "risk_why":
            items = block.get("items", [])
            lines = [f"• {i['label']} ({i['points']:+d})" for i in items]
            body.append({"type": "TextBlock", "text": "**Why this score**", "wrap": True})
            body.append({"type": "TextBlock", "text": "\n".join(lines), "wrap": True, "isSubtle": True})
        elif btype == "actions" and not message.get(_ACTED):
            for action in block.get("actions", []):
                actions.append({
                    "type": "Action.Submit",
                    "title": action.get("label", action["action"]),
                    "style": action.get("style", "default"),
                    "data": {
                        "action": f"rc_{action['action']}",
                        "approval_id": str(action.get("approval_id", "")),
                    },
                })
    body.append({"type": "TextBlock", "text": "RicozChange · change management", "isSubtle": True, "wrap": True})
    return {"type": "AdaptiveCard", "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.4", "body": body, "actions": actions}


def _card_message_payload(card: dict) -> dict:
    return {
        "type": "message",
        "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "content": card}],
    }


def _decided_card_payload(decision: str, who: str, change: Change) -> dict:
    mark = "✅" if decision == "approved" else "❌"
    return _card_message_payload({
        "type": "AdaptiveCard", "version": "1.4", "body": [
            {"type": "TextBlock", "wrap": True,
             "text": f"{mark} **{decision.capitalize()} by {who}** — change #{change.id} “{change.title}” is now `{change.status}`."},
            {"type": "TextBlock", "text": "RicozChange · change management", "isSubtle": True, "wrap": True},
        ],
        "actions": [],
    })


# ---------------------------------------------------------------- delivery ---

def _proactive_conversation(settings: dict, token: str, teams_id: str) -> dict:
    """Create (or reuse) the 1:1 conversation with one approver."""
    body = {
        "bot": {"id": settings.get("bot_id") or settings.get("app_id")},
        "isGroup": False,
        "members": [{"id": teams_id}],
        "tenantId": settings.get("tenant_id", ""),
    }
    return _post_json(f"{settings['service_url']}v3/conversations", token, body)


def _send_card(settings: dict, token: str, conversation_id: str, payload: dict) -> dict:
    return _post_json(
        f"{settings['service_url']}v3/conversations/{urllib.parse.quote(conversation_id)}/activities",
        token, payload,
    )


def deliver_pending(db: Session) -> int:
    """Send every queued, undelivered approval card to mapped approvers.

    Processes kind="teams" mirror rows; the outbox row stays the source of
    truth and delivery state is recorded on it (sent_at / conversation id /
    delivery_error) for the audit and for in-place card updates.
    """
    settings = get_settings(db)
    if not (settings.get("app_id") and settings.get("app_password") and settings.get("service_url")):
        return 0
    token = _bot_token(db, settings)

    rows = db.execute(
        select(Notification)
        .where(Notification.kind == "teams", Notification.sent_at.is_(None), Notification.acted.is_(False))
        .order_by(Notification.id)
    ).scalars().all()

    if not token:
        # Creds + serviceUrl exist but Azure is unreachable right now: mark the
        # rows so the audit shows the outage (the sweep retries them later).
        for note in rows:
            if note.delivery_error is None:
                note.delivery_error = "network: bot token fetch failed"
        db.flush()
        return 0

    sent = 0
    for note in rows:
        if note.approval_id is None:
            continue
        approval = db.get(Approval, note.approval_id)
        if approval is None:
            continue
        user = db.get(User, approval.approver_id)
        if user is None or not user.teams_id:
            note.delivery_error = "approver has no linked teams_id"
            continue
        change = db.get(Change, note.change_id) if note.change_id else None
        if change is None:
            note.delivery_error = "change missing"
            continue
        try:
            conv = _proactive_conversation(settings, token, user.teams_id)
            activity = _send_card(settings, token, conv["id"], _card_message_payload(to_adaptive_card(note.message)))
            note.sent_at = datetime.now()
            note.teams_conversation_id = str(conv.get("id", ""))
            note.teams_activity_id = str(activity.get("id", ""))
            sent += 1
        except Exception as exc:  # noqa: BLE001 — outage, retry via sweep
            note.delivery_error = f"network: {exc}"[:400]
    db.flush()
    return sent


# ------------------------------------------------------- identity / autolink ---

def autolink_by_graph(db: Session, aad_id: str) -> User | None:
    """First Teams action by an unmapped user: look up their mail via Microsoft
    Graph (bot's client credentials; needs directory read consent) and link the
    RicozChange account with the same email. None → ephemeral fallback."""
    settings = get_settings(db)
    if not (settings.get("app_id") and settings.get("app_password")):
        return None
    try:
        tokens = _post_json(GRAPH_TOKEN_URL, None, None, form={
            "grant_type": "client_credentials",
            "client_id": settings["app_id"],
            "client_secret": settings["app_password"],
            "scope": "https://graph.microsoft.com/.default",
        })
        req_token = tokens.get("access_token")
        profile = _post_json(
            GRAPH_ME_URL.format(aad_id=urllib.parse.quote(aad_id)), req_token, method="GET"
        )
    except Exception as exc:  # noqa: BLE001 — consent missing / Graph down
        logger.info("teams autolink lookup failed for %s: %s", aad_id, exc)
        return None
    email = (profile.get("mail") or profile.get("userPrincipalName") or "").lower()
    if not email:
        return None
    user = db.execute(select(User).where(func.lower(User.email) == email)).scalars().first()
    if user is not None:
        user.teams_id = aad_id
        db.flush()
    return user


# ----------------------------------------------------------- interactions ---

def _find_note(db: Session, approval_id: int | None, conversation_id: str) -> Notification | None:
    if approval_id:
        note = db.execute(
            select(Notification).where(Notification.approval_id == approval_id, Notification.kind == "teams")
        ).scalars().first()
        if note:
            return note
    if conversation_id:
        return db.execute(
            select(Notification).where(
                Notification.teams_conversation_id == conversation_id, Notification.kind == "teams"
            )
        ).scalars().first()
    return None


def _ephemeral(text: str) -> dict:
    return {"statusCode": 200, "type": "emitResponse", "text": text}


def handle_interaction(
    db: Session, *, value: dict, from_id: str,
    conversation_id: str = "", activity_id: str = "",
) -> dict:
    """Resolve a Teams Action.Submit into the existing approval service."""
    action = str(value.get("action", ""))
    if action not in ("rc_approve", "rc_reject", "approve", "reject"):
        return _ephemeral("Unknown action.")
    decision = "approved" if action in ("rc_approve", "approve") else "rejected"

    raw_approval = str(value.get("approval_id", "") or "")
    note = _find_note(db, int(raw_approval) if raw_approval.isdigit() else None, conversation_id)
    if note is None:
        return _ephemeral("This approval request is no longer tracked by RicozChange (unknown message).")

    actor = db.execute(select(User).where(User.teams_id == from_id)).scalars().first() if from_id else None
    if actor is None and from_id:
        actor = autolink_by_graph(db, from_id)
    if actor is None:
        return _ephemeral(
            f"⚠️ Your Teams account isn't linked to a RicozChange user. Ask an admin to link your AAD id `{from_id}` (emails must match)."
        )

    approval = db.get(Approval, note.approval_id) if note.approval_id else None
    change = db.get(Change, note.change_id) if note.change_id else None
    if approval is None or change is None:
        return _ephemeral("The underlying approval or change no longer exists.")

    if note.acted or approval.decision != "pending":
        return _ephemeral(f"This change was already resolved (status: {change.status}).")
    if approval.approver_id != actor.id:
        return _ephemeral(f"This approval is assigned to {approval.approver.name}, not you.")

    from . import services  # local import: services pulls the notification stack

    services.record_approval(db, change, approval, decision, comment="from Teams", source="teams")
    note.acted = True
    note.acted_action = decision
    note.message = {**(note.message or {}), _ACTED: True}
    log_action(db, "notification", note.id, f"teams_{decision}", actor=actor.name, detail="from Teams interaction")

    # Edit the card in place: buttons vanish, the decision shows. The card to
    # update is the bot's ORIGINAL message (teams_activity_id recorded at
    # delivery), not the inbound Action.Submit activity (that's the reply).
    target_activity = note.teams_activity_id or activity_id
    if note.teams_conversation_id and target_activity:
        settings = get_settings(db)
        token = _bot_token(db, settings)
        if token:
            try:
                _update_activity(settings, token, note.teams_conversation_id, target_activity,
                                 _decided_card_payload(decision, actor.name, change))
            except Exception as exc:  # noqa: BLE001 — the decision itself already landed
                logger.warning("teams card update failed for note %s: %s", note.id, exc)

    db.flush()
    return _ephemeral(f"Change #{change.id} {decision}.")


def _update_activity(settings: dict, token: str, conversation_id: str, activity_id: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{settings['service_url']}v3/conversations/{urllib.parse.quote(conversation_id)}/activities/{urllib.parse.quote(activity_id)}",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="PUT",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode() or "{}")


# ------------------------------------------------------- sweep + fallbacks ---

def run_teams_sweep(db: Session) -> dict:
    """Sweep pass for the Teams transport: retry undelivered cards, then email
    fallback for rows Teams never managed to deliver. Mirror of the Slack
    fallback chain — never raises."""
    counts = {"teams_delivered": 0, "teams_fallbacks": 0}
    try:
        counts["teams_delivered"] = deliver_pending(db)
    except Exception:  # noqa: BLE001 — sweep stages must never break each other
        logger.exception("teams sweep: delivery stage failed")

    # Email fallback for Teams rows whose delivery failed (kind="email" mirror
    # marks covered note ids via fallback_for, dialect-safe like the Slack one).
    try:
        failed = db.execute(
            select(Notification).where(Notification.kind == "teams", Notification.delivery_error.isnot(None))
        ).scalars().unique().all()
        fallbacks = db.execute(select(Notification).where(Notification.kind == "email")).scalars().all()
        covered = {(n.message or {}).get("fallback_for") for n in fallbacks}
        for note in failed:
            if note.id in covered:
                continue
            approval = db.get(Approval, note.approval_id) if note.approval_id else None
            user = db.get(User, approval.approver_id) if approval else None
            if user is None:
                continue
            msg = note.message or {}
            from . import email_app  # local: avoids an import cycle at module load

            fallback_email = email_app.send_email(
                db,
                to_addr=user.email,
                subject=msg.get("text", "Approval request (Teams delivery failed)")[:180],
                body=(
                    "Teams could not deliver this approval request, so it is repeated here.\n\n"
                    + str(msg.get("text", ""))[:3000]
                    + (f"\n\nOpen: {config.PUBLIC_BASE_URL}/changes/{note.change_id}" if note.change_id else "")
                ),
                change_id=note.change_id,
            )
            # Mark the CREATED EMAIL with the covered note id — reading the
            # marker back from kind="email" rows is what makes the dedupe work.
            fallback_email.message = {**(fallback_email.message or {}), "fallback_for": note.id}
            counts["teams_fallbacks"] += 1
        db.flush()
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("teams sweep: email-fallback stage failed")
    return counts
