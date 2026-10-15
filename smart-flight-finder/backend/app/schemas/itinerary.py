"""Pydantic schemas for the ItineraryRequest API surface."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import CabinClass, DateWindowRole, TicketStrategyType, TripType


class ScoringWeights(BaseModel):
    """多維度評分權重 — 總和不強制為 1.0，服務層會做 min-max 正規化。"""

    price: float = Field(default=0.5, ge=0.0, le=1.0, description="絕對價格")
    pto_efficiency: float = Field(default=0.2, ge=0.0, le=1.0, description="請假效益比")
    flight_time: float = Field(default=0.15, ge=0.0, le=1.0, description="飛行與轉機時長")
    strategy_risk: float = Field(default=0.15, ge=0.0, le=1.0, description="策略複雜度/風險")


class DateWindowIn(BaseModel):
    role: DateWindowRole
    anchor_date: date
    flex_before: int = Field(default=0, ge=0, le=14)
    flex_after: int = Field(default=0, ge=0, le=14)
    allow_weekend_only: bool = False
    sequence: int = Field(default=0, ge=0)
    segment_origin: str | None = Field(default=None, max_length=8)
    segment_destination: str | None = Field(default=None, max_length=8)

    @field_validator("segment_origin", "segment_destination")
    @classmethod
    def _upper(cls, v: str | None) -> str | None:
        return v.upper() if v else v


class DateWindowOut(DateWindowIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    total_candidate_days: int


class ItineraryRequestIn(BaseModel):
    trip_type: TripType
    cabin: CabinClass = CabinClass.ECONOMY
    adults: int = Field(default=1, ge=1, le=9)
    children: int = Field(default=0, ge=0, le=8)
    infants: int = Field(default=0, ge=0, le=4)

    origins: list[str] = Field(
        default_factory=list, description="e.g. ['TPE','TSA','KHH']", min_length=1
    )
    destinations: list[str] = Field(
        default_factory=list, description="IATA 或國碼 ISO-2", min_length=1
    )
    strategies: list[TicketStrategyType] = Field(
        default_factory=lambda: [TicketStrategyType.STANDARD]
    )

    holiday_key: str | None = None
    max_total_budget: int | None = Field(default=None, ge=0, description="TWD")
    max_pto_days: int | None = Field(default=None, ge=0, le=30)
    scoring_weights: ScoringWeights | None = None

    date_windows: list[DateWindowIn] = Field(default_factory=list, min_length=1)

    @field_validator("origins", "destinations")
    @classmethod
    def _upper_list(cls, v: list[str]) -> list[str]:
        return [s.strip().upper() for s in v if s and s.strip()]

    @model_validator(mode="after")
    def _validate_windows(self) -> ItineraryRequestIn:
        roles = {w.role for w in self.date_windows}
        if self.trip_type is TripType.ROUND_TRIP and not {
            DateWindowRole.OUTBOUND,
            DateWindowRole.RETURN,
        }.issubset(roles):
            raise ValueError("round_trip 需同時提供 outbound 與 return date_window")
        if self.trip_type is TripType.MULTI_CITY and len(self.date_windows) < 2:
            raise ValueError("multi_city 至少需要兩個 date_window")
        return self


class ItineraryRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    trip_type: TripType
    cabin: CabinClass
    adults: int
    children: int
    infants: int
    origins: list[str]
    destinations: list[str]
    strategies: list[TicketStrategyType]
    holiday_key: str | None
    max_total_budget: int | None
    max_pto_days: int | None
    scoring_weights: ScoringWeights | None
    date_windows: list[DateWindowOut]
