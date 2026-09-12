"""Shared in-memory sliding-window rate limiter (no extra dependencies).

Budgets are generous: normal users and E2E never trip them; only bursts
(credential-stuffing, LLM-cost DoS) get 429. State is per-process; for a
multi-worker deployment replace with Redis.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict

from fastapi import Depends, HTTPException, Request

from core.deps import get_current_user

_hits: dict[tuple[str, str], list[float]] = defaultdict(list)


def _enabled() -> bool:
    return os.getenv("ARIA_RATE_LIMIT", "on").lower() not in ("off", "0", "false")


def check_limit(bucket: str, key: str, max_calls: int, window_s: int) -> None:
    if not _enabled():
        return
    now = time.monotonic()
    k = (bucket, key)
    hits = [t for t in _hits[k] if now - t < window_s]
    if len(hits) >= max_calls:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Slow down and try again shortly.",
        )
    hits.append(now)
    _hits[k] = hits


def limit(bucket: str, max_calls: int, window_s: int = 60):
    """FastAPI dependency: throttle an endpoint per authenticated user."""

    def _dep(request: Request, user: dict = Depends(get_current_user)) -> dict:
        ident = str(user.get("user_id", "?"))
        ip = request.client.host if request.client else "unknown"
        check_limit(f"{bucket}:u", ident, max_calls, window_s)
        check_limit(f"{bucket}:ip", ip, max_calls * 4, window_s)
        return user

    return _dep


# Presets: expensive LLM/data endpoints get tighter budgets.
limit_llm = lambda: limit("llm", int(os.getenv("ARIA_RL_LLM_MAX", "30")), 60)  # noqa: E731
limit_heavy = lambda: limit("heavy", int(os.getenv("ARIA_RL_HEAVY_MAX", "60")), 60)  # noqa: E731
