"""Validation smoke tests for Phase 1 Pydantic schemas."""

from datetime import date

import pytest

from app.models.enums import DateWindowRole, TicketStrategyType, TripType
from app.schemas.itinerary import DateWindowIn, ItineraryRequestIn


def _window(role: DateWindowRole, day: date, before: int = 0, after: int = 0) -> DateWindowIn:
    return DateWindowIn(role=role, anchor_date=day, flex_before=before, flex_after=after)


def test_round_trip_requires_outbound_and_return():
    with pytest.raises(ValueError):
        ItineraryRequestIn(
            trip_type=TripType.ROUND_TRIP,
            origins=["TPE"],
            destinations=["NRT"],
            date_windows=[_window(DateWindowRole.OUTBOUND, date(2027, 2, 5))],
        )


def test_round_trip_valid_shape():
    req = ItineraryRequestIn(
        trip_type=TripType.ROUND_TRIP,
        origins=["tpe", " khh "],
        destinations=["nrt", "hnd"],
        strategies=[TicketStrategyType.STANDARD, TicketStrategyType.REVERSE],
        holiday_key="lunar_ny",
        date_windows=[
            _window(DateWindowRole.OUTBOUND, date(2027, 2, 5), before=2, after=2),
            _window(DateWindowRole.RETURN, date(2027, 2, 11), before=1, after=3),
        ],
    )
    assert req.origins == ["TPE", "KHH"]
    assert req.destinations == ["NRT", "HND"]
    assert req.date_windows[0].flex_before + req.date_windows[0].flex_after + 1 == 5


def test_multi_city_needs_two_windows():
    with pytest.raises(ValueError):
        ItineraryRequestIn(
            trip_type=TripType.MULTI_CITY,
            origins=["TPE"],
            destinations=["NRT"],
            date_windows=[_window(DateWindowRole.SEGMENT, date(2027, 2, 5))],
        )


def test_flex_bounds():
    with pytest.raises(ValueError):
        DateWindowIn(
            role=DateWindowRole.OUTBOUND,
            anchor_date=date(2027, 2, 5),
            flex_before=99,
        )
