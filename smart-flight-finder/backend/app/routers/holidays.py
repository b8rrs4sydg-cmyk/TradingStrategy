"""Holiday + leave-strategy read endpoints.

Phase 1: 僅暴露 2027 TW 連假與請假攻略。資料來源：
- 若資料庫已 seed：回傳 DB rows。
- 若未 seed (如測試環境或剛啟動)：回退至 ``app.data.taiwan_holidays_2027``
  的靜態資料，保證 API 永遠可用。
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.data import taiwan_holidays_2027 as tw27
from app.models.holiday import Holiday, LeaveStrategy
from app.schemas.holiday import HolidayOut, LeaveStrategyOut

router = APIRouter(prefix="/holidays", tags=["holidays"])


@router.get("/2027", response_model=list[HolidayOut])
def list_tw_2027_holidays(
    kind: str | None = Query(default=None, description="HolidayType enum value"),
    db: Session = Depends(get_db),
) -> list[HolidayOut]:
    try:
        stmt = select(Holiday).where(
            Holiday.country == "TW",
            Holiday.day >= date(2027, 1, 1),
            Holiday.day <= date(2027, 12, 31),
        )
        if kind:
            stmt = stmt.where(Holiday.kind == kind)
        rows = db.scalars(stmt.order_by(Holiday.day)).all()
        if rows:
            return [HolidayOut.model_validate(r) for r in rows]
    except SQLAlchemyError:
        # DB unavailable — fall back to static data
        pass

    static_rows = tw27.HOLIDAYS
    if kind:
        static_rows = [r for r in static_rows if r.kind.value == kind]
    return [
        HolidayOut(
            id=i,
            country="TW",
            day=r.day,
            name_zh=r.name_zh,
            name_en=r.name_en,
            kind=r.kind,
            is_workday=r.is_workday,
            notes=r.notes,
        )
        for i, r in enumerate(static_rows, start=1)
    ]


@router.get("/2027/leave-strategies", response_model=list[LeaveStrategyOut])
def list_tw_2027_leave_strategies(
    db: Session = Depends(get_db),
) -> list[LeaveStrategyOut]:
    try:
        rows = db.scalars(
            select(LeaveStrategy).where(LeaveStrategy.year == 2027).order_by(LeaveStrategy.window_start)
        ).all()
        if rows:
            return [LeaveStrategyOut.model_validate(r) for r in rows]
    except SQLAlchemyError:
        pass

    return [
        LeaveStrategyOut(
            id=i,
            year=2027,
            holiday_key=r.holiday_key,
            label_zh=r.label_zh,
            pto_days=r.pto_days,
            total_days=r.total_days,
            window_start=r.window_start,
            window_end=r.window_end,
            description=r.description,
        )
        for i, r in enumerate(tw27.LEAVE_STRATEGIES, start=1)
    ]


@router.get("/2027/{holiday_key}", response_model=list[LeaveStrategyOut])
def leave_strategies_for_holiday(holiday_key: str) -> list[LeaveStrategyOut]:
    matches = [r for r in tw27.LEAVE_STRATEGIES if r.holiday_key == holiday_key]
    if not matches:
        raise HTTPException(status_code=404, detail=f"Unknown holiday_key: {holiday_key}")
    return [
        LeaveStrategyOut(
            id=i,
            year=2027,
            holiday_key=r.holiday_key,
            label_zh=r.label_zh,
            pto_days=r.pto_days,
            total_days=r.total_days,
            window_start=r.window_start,
            window_end=r.window_end,
            description=r.description,
        )
        for i, r in enumerate(matches, start=1)
    ]
