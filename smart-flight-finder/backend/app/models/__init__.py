"""SQLAlchemy ORM models.

Importing this package registers every model class on the shared
``Base.metadata`` used by Alembic's autogenerate.
"""

from app.models.enums import (
    CabinClass,
    DateWindowRole,
    HolidayType,
    TicketStrategyType,
    TripType,
)
from app.models.holiday import Holiday, LeaveStrategy
from app.models.itinerary import DateWindow, ItineraryRequest

__all__ = [
    "CabinClass",
    "DateWindow",
    "DateWindowRole",
    "Holiday",
    "HolidayType",
    "ItineraryRequest",
    "LeaveStrategy",
    "TicketStrategyType",
    "TripType",
]
