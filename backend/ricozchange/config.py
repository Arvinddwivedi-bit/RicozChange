"""Configuration. Everything is env-driven with demo-friendly defaults."""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _normalize_database_url(raw: str) -> str:
    """Accept the URL shapes platforms hand us and map them to installed drivers.

    - Render/Heroku/Neon hand out postgres:// or postgresql:// (SQLAlchemy would
      default to psycopg2, which is not installed) -> rewrite to psycopg 3.
    - postgresql+psycopg:// already explicit -> keep as-is.
    """
    if raw.startswith("postgres://"):
        raw = "postgresql+psycopg://" + raw[len("postgres://"):]
    elif raw.startswith("postgresql://"):
        raw = "postgresql+psycopg://" + raw[len("postgresql://"):]
    return raw


DATABASE_URL = _normalize_database_url(
    os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'Ricozchange.db'}")
)

# Seeding: creates demo data on first boot (skipped automatically if data exists)
AUTO_SEED = _bool("AUTO_SEED", True)

# Demo auth: when False, every request acts as DEFAULT_USER_EMAIL (MVP/demo mode).
# When True, requires a Clerk bearer token verified against CLERK_JWKS_URL.
GATE_BY_DEMO_USER = _bool("GATE_BY_DEMO_USER", False)
DEFAULT_USER_EMAIL = os.getenv("DEFAULT_USER_EMAIL", "priya@Ricozchange.dev")

# Clerk (production auth). Leave empty in demo mode.
CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY", "")
CLERK_JWKS_URL = os.getenv("CLERK_JWKS_URL", "")
CLERK_ISSUER = os.getenv("CLERK_ISSUER", "")
CLERK_AUDIENCE = os.getenv("CLERK_AUDIENCE", "")

# Slack integration (phase 2). Env vars bootstrap; DB settings (set via OAuth
# install) take precedence. Leave empty to stay in demo-outbox mode.
SLACK_CLIENT_ID = os.getenv("SLACK_CLIENT_ID", "")
SLACK_CLIENT_SECRET = os.getenv("SLACK_CLIENT_SECRET", "")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")
SLACK_REDIRECT_URI = os.getenv("SLACK_REDIRECT_URI", "")  # e.g. https://<host>/api/integrations/slack/oauth/callback
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://ricozchange-1y64.onrender.com")

# Claude API for AI drafting. Without a key, template-based drafting is used.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5")
AI_MAX_OUTPUT_TOKENS = int(os.getenv("AI_MAX_OUTPUT_TOKENS", "1500"))

CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
