"""策略引擎共用型別。

這些是 pure dataclass，不依賴 ORM — 便於測試與序列化。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from app.models.enums import CabinClass, TicketStrategyType


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class RiskWarning:
    level: RiskLevel
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class FlightLeg:
    origin: str                 # IATA 3-letter airport code
    destination: str
    departure: datetime
    arrival: datetime
    carrier: str                # 2-letter airline code
    flight_number: str
    cabin: CabinClass = CabinClass.ECONOMY
    stops: int = 0              # 轉機次數 (0 == 直飛)

    @property
    def duration(self) -> timedelta:
        return self.arrival - self.departure


@dataclass(frozen=True, slots=True)
class TicketOffer:
    """A single airline-issued ticket — may itself contain multiple legs."""

    offer_id: str
    legs: tuple[FlightLeg, ...]
    total_price: int            # minor currency unit (TWD = whole TWD)
    currency: str = "TWD"
    fare_class: str | None = None
    baggage_through_checked: bool = True
    issuer: str | None = None

    def first_leg(self) -> FlightLeg:
        return self.legs[0]

    def last_leg(self) -> FlightLeg:
        return self.legs[-1]

    @property
    def origin(self) -> str:
        return self.first_leg().origin

    @property
    def final_destination(self) -> str:
        return self.last_leg().destination

    @property
    def total_duration(self) -> timedelta:
        return self.last_leg().arrival - self.first_leg().departure


@dataclass(frozen=True, slots=True)
class StrategyPlan:
    """A concrete recommendation produced by one strategy engine."""

    strategy: TicketStrategyType
    tickets: tuple[TicketOffer, ...]
    total_cost: int
    currency: str = "TWD"
    pto_days: int = 0
    total_travel_days: int = 0
    warnings: tuple[RiskWarning, ...] = field(default_factory=tuple)
    score: float | None = None       # populated by scoring engine
    explain: str | None = None       # human-readable one-liner

    @property
    def ticket_count(self) -> int:
        return len(self.tickets)
