"""Operational endpoints — behind an ``APP_ADMIN_TOKEN`` bearer check."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.seed_holidays import seed_holidays

router = APIRouter(prefix="/admin", tags=["admin"])


def _require_admin_token(authorization: str | None = Header(default=None)) -> None:
    expected = os.getenv("APP_ADMIN_TOKEN")
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin endpoints disabled (set APP_ADMIN_TOKEN to enable).",
        )
    if authorization != f"Bearer {expected}":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid bearer token.",
        )


@router.post("/seed", dependencies=[Depends(_require_admin_token)])
def seed(db: Session = Depends(get_db)) -> dict[str, int]:
    """Idempotently populate the 2027 TW holiday + leave-strategy tables."""

    return seed_holidays(db)
