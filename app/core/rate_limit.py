"""
Simple in-memory rate limiter — no external dependencies required.
Uses a sliding window counter per key. Works for single-process deployments.
For multi-worker production, replace with Redis-backed slowapi.
"""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock
from typing import Tuple

_buckets: dict[str, list[float]] = defaultdict(list)
_lock = Lock()


def is_allowed(key: str, max_calls: int, window_seconds: int) -> Tuple[bool, int]:
    """
    Check if a request is allowed under the rate limit.
    Returns (allowed: bool, retry_after_seconds: int).
    Thread-safe; O(n) where n = calls in window (small in practice).
    """
    now = time.monotonic()
    cutoff = now - window_seconds

    with _lock:
        calls = _buckets[key]
        # Evict stale entries
        _buckets[key] = [t for t in calls if t > cutoff]

        if len(_buckets[key]) >= max_calls:
            oldest = min(_buckets[key])
            retry_after = int(window_seconds - (now - oldest)) + 1
            return False, retry_after

        _buckets[key].append(now)
        return True, 0
