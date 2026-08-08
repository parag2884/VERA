"""Lightweight guards for published public chat surfaces."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from app.config import get_settings

_lock = Lock()
_hits: dict[str, deque[float]] = defaultdict(deque)


def origin_ok(allowed: str, origin: str | None) -> bool:
    settings = get_settings()
    if settings.vera_public_require_origin and not origin:
        return False
    if not allowed or allowed.strip() == "*":
        return True
    if not origin:
        # When require_origin is off, missing Origin is allowed (curl / server callers)
        return True
    allowed_set = {o.strip() for o in allowed.split(",") if o.strip()}
    return origin.rstrip("/") in {a.rstrip("/") for a in allowed_set}


def rate_limit_ok(key: str) -> bool:
    """Simple in-process sliding window per embed_key (or IP+key)."""
    settings = get_settings()
    limit = int(settings.vera_public_rate_limit_per_min or 0)
    if limit <= 0:
        return True
    now = time.time()
    window = 60.0
    with _lock:
        q = _hits[key]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True
