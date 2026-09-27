"""Lightweight in-process rate limiting for public endpoints.

A sliding-window counter keyed by (bucket, client-ip). Single-process friendly
(uvicorn on Render runs one worker) and dependency-free by design — swap for a
Redis-backed limiter only when the deployment scales past one process.

Enabled by default; RATE_LIMIT_DISABLED=1 turns it off (tests, local tools).
"""
from __future__ import annotations

import os
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


class SlidingWindowLimiter:
    def __init__(self, max_events: int, window_seconds: float) -> None:
        self.max_events = max_events
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> bool:
        """True when the event is allowed; records it otherwise returns False."""
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.max_events:
            return False
        q.append(now)
        if not q:  # deque emptied by prune; safe re-append
            self._hits[key].append(now)
        return True

    def retry_after(self, key: str) -> int:
        q = self._hits.get(key)
        if not q:
            return 0
        return max(1, int(self.window - (time.monotonic() - q[0])) + 1)


_DISABLED = os.getenv("RATE_LIMIT_DISABLED", "") == "1"

# Public, unauthenticated attack surface:
webhook_limiter = SlidingWindowLimiter(max_events=60, window_seconds=60.0)     # Slack interactions + email inbound
simulate_limiter = SlidingWindowLimiter(max_events=20, window_seconds=60.0)    # demo simulator (authenticated)
sweep_limiter = SlidingWindowLimiter(max_events=6, window_seconds=60.0)        # sweep trigger (authenticated)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(limiter: SlidingWindowLimiter, bucket: str):
    """FastAPI dependency factory: 429 with Retry-After when the bucket is full."""

    async def dep(request: Request) -> None:
        if _DISABLED:
            return
        key = f"{bucket}:{_client_ip(request)}"
        if not limiter.check(key):
            raise HTTPException(
                status_code=429,
                detail="too many requests — slow down",
                headers={"Retry-After": str(limiter.retry_after(key))},
            )

    return dep
