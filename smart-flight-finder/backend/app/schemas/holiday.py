"""Pydantic schemas for holidays & leave strategies."""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import HolidayType


class HolidayOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    country: str
    day: date
    name_zh: str
    name_en: str
    kind: HolidayType
    is_workday: bool
    notes: str | None = None


class LeaveStrategyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    year: int
    holiday_key: str
    label_zh: str = Field(description="e.g. 春節請 2 休 11")
    pto_days: int
    total_days: int
    window_start: date
    window_end: date
    description: str | None = None
