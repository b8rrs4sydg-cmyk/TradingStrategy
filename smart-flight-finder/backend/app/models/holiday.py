"""Taiwan holiday + leave-strategy tables.

These power the 2.1 Holiday & Date Matrix Module. Rows are seeded from
``app.data.taiwan_holidays_2027`` on first boot (see
``app.services.seed_holidays``).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import HolidayType


class Holiday(Base):
    """A single official holiday / makeup workday row."""

    __tablename__ = "holidays"
    __table_args__ = (UniqueConstraint("country", "day", name="uq_holiday_country_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country: Mapped[str] = mapped_column(String(2), default="TW", index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    name_zh: Mapped[str] = mapped_column(String(64))
    name_en: Mapped[str] = mapped_column(String(64))
    kind: Mapped[HolidayType] = mapped_column(String(16))
    is_workday: Mapped[bool] = mapped_column(default=False)  # True ⇒ 補班日
    notes: Mapped[str | None] = mapped_column(String(255), default=None)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Holiday {self.day} {self.name_zh}>"


class LeaveStrategy(Base):
    """請假攻略：某個連假額外請 N 天特休可換得連續 M 天假期。

    Example: 春節 2027 — 請 2 休 11 (take 2 PTO days, get 11 days off).
    """

    __tablename__ = "leave_strategies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    holiday_key: Mapped[str] = mapped_column(String(32), index=True)
    label_zh: Mapped[str] = mapped_column(String(64))
    pto_days: Mapped[int] = mapped_column(Integer)  # 請 N 天
    total_days: Mapped[int] = mapped_column(Integer)  # 休 M 天
    window_start: Mapped[date] = mapped_column(Date)
    window_end: Mapped[date] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(String(255), default=None)

    anchor_holiday_id: Mapped[int | None] = mapped_column(
        ForeignKey("holidays.id", ondelete="SET NULL"), default=None
    )
    anchor_holiday: Mapped[Holiday | None] = relationship()
