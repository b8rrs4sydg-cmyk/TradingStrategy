"""Seed service: idempotently populate the 2027 Taiwan holiday tables."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data.taiwan_holidays_2027 import (
    HOLIDAYS,
    LEAVE_STRATEGIES,
    HolidayRecord,
    LeaveStrategyRecord,
)
from app.models.holiday import Holiday, LeaveStrategy


def seed_holidays(session: Session, *, country: str = "TW", year: int = 2027) -> dict[str, int]:
    """Upsert the 2027 static TW holiday + leave-strategy data.

    Returns a count summary ``{"holidays": N, "leave_strategies": M}``.
    Idempotent — safe to re-run on container restart.
    """

    holidays_added = _upsert_holidays(session, country, HOLIDAYS)
    strategies_added = _upsert_strategies(session, year, LEAVE_STRATEGIES)
    session.commit()
    return {"holidays": holidays_added, "leave_strategies": strategies_added}


def _upsert_holidays(session: Session, country: str, rows: list[HolidayRecord]) -> int:
    added = 0
    for row in rows:
        existing = session.scalar(
            select(Holiday).where(Holiday.country == country, Holiday.day == row.day)
        )
        if existing:
            existing.name_zh = row.name_zh
            existing.name_en = row.name_en
            existing.kind = row.kind
            existing.is_workday = row.is_workday
            existing.notes = row.notes
            continue
        session.add(
            Holiday(
                country=country,
                day=row.day,
                name_zh=row.name_zh,
                name_en=row.name_en,
                kind=row.kind,
                is_workday=row.is_workday,
                notes=row.notes,
            )
        )
        added += 1
    return added


def _upsert_strategies(session: Session, year: int, rows: list[LeaveStrategyRecord]) -> int:
    added = 0
    for row in rows:
        existing = session.scalar(
            select(LeaveStrategy).where(
                LeaveStrategy.year == year,
                LeaveStrategy.holiday_key == row.holiday_key,
                LeaveStrategy.label_zh == row.label_zh,
            )
        )
        if existing:
            existing.pto_days = row.pto_days
            existing.total_days = row.total_days
            existing.window_start = row.window_start
            existing.window_end = row.window_end
            existing.description = row.description
            continue
        session.add(
            LeaveStrategy(
                year=year,
                holiday_key=row.holiday_key,
                label_zh=row.label_zh,
                pto_days=row.pto_days,
                total_days=row.total_days,
                window_start=row.window_start,
                window_end=row.window_end,
                description=row.description,
            )
        )
        added += 1
    return added
