"""Pydantic schemas that mirror the dataclass StrategyPlan tree for API egress."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import CabinClass, TicketStrategyType
from app.services.booking_links import booking_links
from app.services.strategies.base import (
    FlightLeg,
    RiskLevel,
    RiskWarning,
    StrategyPlan,
    TicketOffer,
)


class FlightLegOut(BaseModel):
    origin: str
    destination: str
    departure: datetime
    arrival: datetime
    carrier: str
    flight_number: str
    cabin: CabinClass = CabinClass.ECONOMY
    stops: int = 0

    @classmethod
    def of(cls, leg: FlightLeg) -> FlightLegOut:
        return cls(
            origin=leg.origin,
            destination=leg.destination,
            departure=leg.departure,
            arrival=leg.arrival,
            carrier=leg.carrier,
            flight_number=leg.flight_number,
            cabin=leg.cabin,
            stops=leg.stops,
        )


class BookingLinkOut(BaseModel):
    source: str
    label: str
    url: str


class TicketOfferOut(BaseModel):
    offer_id: str
    legs: list[FlightLegOut]
    total_price: int
    currency: str = "TWD"
    fare_class: str | None = None
    baggage_through_checked: bool = True
    issuer: str | None = None
    booking_links: list[BookingLinkOut] = Field(default_factory=list)

    @classmethod
    def of(
        cls, t: TicketOffer, *, adults: int = 1, cabin: CabinClass = CabinClass.ECONOMY
    ) -> TicketOfferOut:
        return cls(
            offer_id=t.offer_id,
            legs=[FlightLegOut.of(l) for l in t.legs],
            total_price=t.total_price,
            currency=t.currency,
            fare_class=t.fare_class,
            baggage_through_checked=t.baggage_through_checked,
            issuer=t.issuer,
            booking_links=[
                BookingLinkOut(source=b.source, label=b.label, url=b.url)
                for b in booking_links(t, adults=adults, cabin=cabin)
            ],
        )


class RiskWarningOut(BaseModel):
    level: RiskLevel
    code: str
    message: str

    @classmethod
    def of(cls, w: RiskWarning) -> RiskWarningOut:
        return cls(level=w.level, code=w.code, message=w.message)


class StrategyPlanOut(BaseModel):
    strategy: TicketStrategyType
    tickets: list[TicketOfferOut]
    total_cost: int
    currency: str = "TWD"
    pto_days: int = 0
    total_travel_days: int = 0
    warnings: list[RiskWarningOut] = Field(default_factory=list)
    score: float | None = None
    explain: str | None = None
    window_label: str | None = None

    @classmethod
    def of(
        cls, p: StrategyPlan, *, adults: int = 1, cabin: CabinClass = CabinClass.ECONOMY
    ) -> StrategyPlanOut:
        return cls(
            strategy=p.strategy,
            tickets=[TicketOfferOut.of(t, adults=adults, cabin=cabin) for t in p.tickets],
            total_cost=p.total_cost,
            currency=p.currency,
            pto_days=p.pto_days,
            total_travel_days=p.total_travel_days,
            warnings=[RiskWarningOut.of(w) for w in p.warnings],
            score=p.score,
            explain=p.explain,
            window_label=p.window_label,
        )


class SearchResult(BaseModel):
    request_echo: dict
    date_matrix_size: int
    plans: list[StrategyPlanOut]
    provider_cache: dict[str, int] = Field(default_factory=dict)
