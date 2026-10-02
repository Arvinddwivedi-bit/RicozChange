"""Ricoz marketing-site backend hooks (leads capture).

The landing page's "Become a Franchise Partner" flow posts here. Inquiries are
stored in the `settings` key/value table (no migration needed) under the key
`franchise_leads`, newest first, so the demo/prod deployment needs zero schema
changes. Listing requires an admin session; submission is public but throttled.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from . import models
from .auth import require_role

LEADS_KEY = "franchise_leads"
MAX_LEADS = 200

# Public endpoint throttling: in-memory sliding window (one worker is fine for
# a marketing site; rate-limit at the edge/proxy if this ever scales out).
_RATE: dict[str, list[float]] = {}
_RATE_LIMIT = 5          # submissions
_RATE_WINDOW = 3600.0    # per hour, per IP

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class LeadIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=200)
    company: str = Field(min_length=2, max_length=120)
    city: str = Field(default="", max_length=80)
    message: str = Field(default="", max_length=2000)

    @field_validator("email")
    @classmethod
    def _valid_email(cls, v: str) -> str:
        if not _EMAIL_RE.match(v.strip()):
            raise ValueError("a valid email address is required")
        return v.strip()


def _get_leads(db: Session) -> list[dict]:
    setting = db.get(models.Setting, LEADS_KEY)
    return list((setting.value or {}).get("items", [])) if setting else []


def submit_lead(db: Session, payload: LeadIn, request: Request) -> dict:
    ip = (request.client.host if request.client else "unknown") or "unknown"
    now = time.time()
    window = [t for t in _RATE.get(ip, []) if now - t < _RATE_WINDOW]
    if len(window) >= _RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Too many inquiries. Please try again later.")
    window.append(now)
    _RATE[ip] = window

    now_iso = datetime.now(timezone.utc).isoformat()
    lead = {
        "id": f"lead_{int(now * 1000)}_{len(_RATE[ip])}",
        "name": payload.name.strip(),
        "email": str(payload.email).strip().lower(),
        "company": payload.company.strip(),
        "city": payload.city.strip(),
        "message": payload.message.strip(),
        "status": "new",
        "created_at": now_iso,
    }
    setting = db.get(models.Setting, LEADS_KEY)
    value = (setting.value or {}) if setting else {}
    items = list(value.get("items", []))
    items.insert(0, lead)
    items = items[:MAX_LEADS]
    if setting:
        setting.value = {**value, "items": items}
    else:
        db.add(models.Setting(key=LEADS_KEY, value={"items": items}))
    db.commit()
    return {"ok": True, "id": lead["id"]}


def list_leads(db: Session, actor: object) -> dict:
    items = _get_leads(db)
    return {"items": items, "new_count": sum(1 for i in items if i.get("status") == "new")}


def mark_lead(db: Session, lead_id: str, status: str, actor: object) -> dict:
    if status not in ("new", "contacted", "closed"):
        raise HTTPException(status_code=422, detail="status must be new, contacted or closed")
    setting = db.get(models.Setting, LEADS_KEY)
    if not setting:
        raise HTTPException(status_code=404, detail="Lead not found")
    old_items = (setting.value or {}).get("items", [])
    if not any(i.get("id") == lead_id for i in old_items):
        raise HTTPException(status_code=404, detail="Lead not found")
    # Rebuild with fresh dicts: mutating in place would leave the new value
    # comparing equal to the committed one, so SQLAlchemy would skip the UPDATE.
    items = [
        {**i, "status": status} if i.get("id") == lead_id else dict(i)
        for i in old_items
    ]
    setting.value = {**(setting.value or {}), "items": items}
    db.commit()
    return {"ok": True}
