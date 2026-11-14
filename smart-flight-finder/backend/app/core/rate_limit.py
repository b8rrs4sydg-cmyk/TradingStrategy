"""Fixed-window per-IP rate limiter.

Phase 5+ guard: real flight-offer APIs cost money and enforce strict quotas,
so an unauthenticated public ``/search`` endpoint must throttle abusers before
they drain the monthly budget.

- Primary storage: Redis ``INCR`` on a per-(IP, window) key with ``EXPIRE``
  seeded on first increment. Linearizable per key, no race under scale-out.
- If Redis is down or ``REDIS_URL`` is unset we fall back to an in-process
  dict (single-pod only — Phase 5 one-container deploy's default anyway).

The limiter is intentionally not an ASGI middleware so unit tests can call it
directly without TestClient; the router wires it with ``Depends``.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = int(os.getenv("SEARCH_RATE_LIMIT", "30"))
DEFAULT_WINDOW_S = int(os.getenv("SEARCH_RATE_WINDOW_S", "60"))


@dataclass
class RateLimit:
    limit: int = DEFAULT_LIMIT
    window_s: int = DEFAULT_WINDOW_S

    def check(self, bucket: str) -> tuple[int, int]:
        """Return (count_after_increment, retry_after_seconds).

        Raises ``HTTPException(429)`` when the limit is exceeded.
        """
        count, retry_after = _increment(bucket, self.window_s)
        if count > self.limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded: {self.limit} / {self.window_s}s",
                headers={"Retry-After": str(retry_after)},
            )
        return count, retry_after


# ---------------------------------------------------------------------------
# Backends — try Redis, fall through to in-process memory
# ---------------------------------------------------------------------------
_LOCAL: dict[str, tuple[int, float]] = {}


def _increment(bucket: str, window_s: int) -> tuple[int, int]:
    now = time.time()
    window_start = int(now // window_s) * window_s
    key = f"sff:rl:v1:{bucket}:{window_start}"
    retry_after = max(1, window_start + window_s - int(now))

    client = _redis_client()
    if client is not None:
        try:
            count = client.incr(key)
            if count == 1:
                client.expire(key, window_s)
            return int(count), retry_after
        except Exception:  # pragma: no cover
            logger.warning("rate_limit_redis_fail", exc_info=True)

    # local-memory fallback
    count, expire_at = _LOCAL.get(key, (0, now + window_s))
    if expire_at < now:
        count = 0
        expire_at = now + window_s
    count += 1
    _LOCAL[key] = (count, expire_at)
    return count, retry_after


def _redis_client():
    url = os.getenv("REDIS_URL")
    if not url:
        return None
    try:
        import redis

        return redis.Redis.from_url(url, socket_timeout=1.0, socket_connect_timeout=1.0)
    except Exception:  # pragma: no cover  # noqa: BLE001 — any import/connect failure falls back to in-process
        return None


def client_bucket(request: Request) -> str:
    """IP-based bucket; later we can swap in authenticated user id."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def enforce_rate_limit(request: Request) -> None:
    """FastAPI dependency: ``Depends(enforce_rate_limit)``."""
    RateLimit().check(client_bucket(request))
