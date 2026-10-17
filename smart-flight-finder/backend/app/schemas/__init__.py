"""Pydantic schemas for API I/O (kept separate from SQLAlchemy ORM)."""

from app.schemas.holiday import HolidayOut, LeaveStrategyOut
from app.schemas.itinerary import (
    CandidateWindowIn,
    DateWindowIn,
    DateWindowOut,
    ItineraryRequestIn,
    ItineraryRequestOut,
    ScoringWeights,
)
from app.schemas.plan import (
    BookingLinkOut,
    FlightLegOut,
    RiskWarningOut,
    SearchResult,
    StrategyPlanOut,
    TicketOfferOut,
)

__all__ = [
    "BookingLinkOut",
    "CandidateWindowIn",
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
