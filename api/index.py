"""Vercel serverless entrypoint for the RicozChange FastAPI app.

Puts backend/ on sys.path so the `ricozchange` package imports, then exposes
the ASGI `app` Vercel's Python runtime expects. Static assets are served from
frontend/dist by Vercel's CDN (see vercel.json); the SPA mount inside main.py
stays dormant because backend/static is not deployed to Vercel.
"""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from ricozchange.main import app  # noqa: E402
