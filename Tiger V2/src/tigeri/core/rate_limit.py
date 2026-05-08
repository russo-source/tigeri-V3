"""Process-local rate limiter for auth endpoints.

This is intentionally minimal — no Redis, no slowapi dep. A single uvicorn
worker on the EC2 box doesn't need cross-process state; if/when we scale to
multiple workers, swap the storage for Redis without changing the public
``hit`` API.

Used by /auth/sign-in and /auth/sign-up to slow down credential-stuffing
and account-enumeration probes. Limits are per-(ip, identifier) so a single
attacker hammering one email is throttled even if they rotate which user
they target.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque


@dataclass(slots=True)
class _Bucket:
    hits: Deque[float]


class RateLimiter:
    """Sliding-window counter. Permits ``max_hits`` events per ``window_seconds``."""

    def __init__(self, *, max_hits: int, window_seconds: float) -> None:
        if max_hits <= 0 or window_seconds <= 0:
            raise ValueError("max_hits and window_seconds must be positive")
        self._max = max_hits
        self._window = window_seconds
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def _key(self, *parts: str | None) -> str:
        return "|".join((p or "?").lower() for p in parts)

    def hit(self, *parts: str | None) -> tuple[bool, int]:
        """Record an attempt. Returns ``(allowed, retry_after_seconds)``.

        When the bucket is full ``allowed=False`` and ``retry_after`` is the
        seconds until the oldest hit ages out. Caller maps this to a 429.
        """
        key = self._key(*parts)
        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(hits=deque())
                self._buckets[key] = bucket
            # Evict expired hits.
            while bucket.hits and bucket.hits[0] <= cutoff:
                bucket.hits.popleft()
            if len(bucket.hits) >= self._max:
                retry = max(1, int(bucket.hits[0] + self._window - now) + 1)
                return False, retry
            bucket.hits.append(now)
            # Periodically prune empty buckets to bound memory.
            if len(self._buckets) > 4096:
                self._gc(cutoff)
            return True, 0

    def reset(self, *parts: str | None) -> None:
        """Clear a bucket — call on successful sign-in so a legitimate user
        whose previous typos pushed them near the limit gets a clean slate."""
        with self._lock:
            self._buckets.pop(self._key(*parts), None)

    def _gc(self, cutoff: float) -> None:
        # Caller already holds the lock.
        empty = [k for k, b in self._buckets.items() if not b.hits or b.hits[-1] < cutoff]
        for k in empty:
            self._buckets.pop(k, None)


# Public limiters tuned per the threat model:
#   - sign_in: 8 attempts per (ip, email) per 5 minutes
#   - sign_up: 5 attempts per (ip) per 10 minutes (slug enumeration)
sign_in_limiter = RateLimiter(max_hits=8, window_seconds=300)
sign_up_limiter = RateLimiter(max_hits=5, window_seconds=600)
