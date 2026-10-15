"""Pydantic schemas for API I/O (kept separate from SQLAlchemy ORM)."""

from app.schemas.holiday import HolidayOut, LeaveStrategyOut
from app.schemas.itinerary import (
    DateWindowIn,
    DateWindowOut,
    ItineraryRequestIn,
    ItineraryRequestOut,
    ScoringWeights,
)
from app.schemas.plan import (
    FlightLegOut,
    RiskWarningOut,
    SearchResult,
    StrategyPlanOut,
    TicketOfferOut,
)

__all__ = [
    "DateWindowIn",
    "DateWindowOut",
    "FlightLegOut",
    "HolidayOut",
    "ItineraryRequestIn",
    "ItineraryRequestOut",
    "LeaveStrategyOut",
    "RiskWarningOut",
    "ScoringWeights",
    "SearchResult",
    "StrategyPlanOut",
    "TicketOfferOut",
]
