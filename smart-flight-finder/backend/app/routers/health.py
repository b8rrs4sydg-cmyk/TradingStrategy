"""Liveness + readiness probes."""

from __future__ import annotations

import os

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app import __version__
from app.core.database import SessionLocal

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness — always returns 200 if the process is alive."""
    return {"status": "ok", "version": __version__}


@router.get("/health/ready")
def readiness(response: Response) -> dict[str, object]:
    """Readiness — DB and (optional) Redis must respond."""

    checks: dict[str, object] = {}

    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as e:  # noqa: BLE001 — all DB errors mean "not ready"
        checks["db"] = f"error: {e.__class__.__name__}"

    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        try:
            import redis

            client = redis.Redis.from_url(redis_url, socket_timeout=1.0, socket_connect_timeout=1.0)
            client.ping()
            checks["redis"] = "ok"
        except Exception as e:  # noqa: BLE001
            checks["redis"] = f"error: {e.__class__.__name__}"
    else:
        checks["redis"] = "not configured"

    all_ok = all(v == "ok" or v == "not configured" for v in checks.values())
    if not all_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if all_ok else "degraded", "checks": checks}
