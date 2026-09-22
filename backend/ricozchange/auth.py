"""Request identity for the MVP.

Demo mode (default): every request acts as the seeded default user, so the
product can be evaluated without setting up Clerk. Production mode: set
GATE_BY_DEMO_USER=false→true via env and provide Clerk credentials; bearer
tokens are then verified against Clerk's JWKS and mapped to seeded users by
email.
"""
from __future__ import annotations

import jwt
import requests
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .db import get_db
from .models import User

_bearer = HTTPBearer(auto_error=False)
_jwks_cache: dict | None = None


def _fetch_jwks() -> dict:
    global _jwks_cache
    if _jwks_cache is None:
        if not config.CLERK_JWKS_URL:
            raise HTTPException(status_code=500, detail="CLERK_JWKS_URL is not configured")
        resp = requests.get(config.CLERK_JWKS_URL, timeout=10)
        resp.raise_for_status()
        _jwks_cache = resp.json()
    return _jwks_cache


def _user_from_email(db: Session, email: str) -> User:
    user = db.execute(select(User).where(User.email == email.lower())).scalars().first()
    if user is None:
        raise HTTPException(status_code=403, detail=f"No RicozChange user for {email}")
    return user


def get_actor(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the acting user. Demo mode returns the default user."""
    if config.GATE_BY_DEMO_USER:
        if credentials is None:
            raise HTTPException(status_code=401, detail="Missing bearer token")
        try:
            key = jwt.algorithms.RSAAlgorithm.from_jwk(_select_jwk(credentials.credentials))
            claims = jwt.decode(
                credentials.credentials,
                key,
                algorithms=["RS256"],
                audience=config.CLERK_AUDIENCE or None,
                issuer=config.CLERK_ISSUER or None,
                options={"verify_aud": bool(config.CLERK_AUDIENCE)},
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")
        email = (claims.get("email") or "").lower()
        if not email:
            raise HTTPException(status_code=401, detail="Token has no email claim")
        return _user_from_email(db, email)

    user = db.execute(select(User).where(User.email == config.DEFAULT_USER_EMAIL)).scalars().first()
    if user is None:
        raise HTTPException(status_code=500, detail="Demo user missing; re-seed the database")
    return user


def _select_jwk(token: str) -> dict:
    jwks = _fetch_jwks()
    try:
        header = jwt.get_unverified_header(token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Malformed token: {exc}")
    for key in jwks.get("keys", []):
        if key.get("kid") == header.get("kid"):
            return key
    raise HTTPException(status_code=401, detail="No matching JWKS key")


require_actor = get_actor  # explicit alias for route dependencies


def require_role(*roles: str):
    """Dependency factory: allow only the listed roles (demo actor is admin).

    Denied attempts are audit-logged before the 403 is raised, so the trail
    records unauthorized-action attempts per the phase-2 PRD.
    """

    def dep(
        actor: User = Depends(require_actor),
        db: Session = Depends(get_db),
    ) -> User:
        if actor.role not in roles:
            from .audit import log_action

            log_action(
                db,
                "auth",
                0,
                "denied",
                actor=actor.name,
                detail=f"role '{actor.role}' not in {sorted(roles)}",
            )
            db.commit()
            raise HTTPException(
                status_code=403,
                detail=f"Requires role: {' or '.join(sorted(roles))}",
            )
        return actor

    return dep
