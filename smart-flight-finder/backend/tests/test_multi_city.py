from datetime import date

from app.models.enums import DateWindowRole, TicketStrategyType, TripType
from app.providers.stub import StubFlightProvider
from app.schemas.itinerary import DateWindowIn, ItineraryRequestIn
from app.services.search import SearchService


def _multi_city_request() -> ItineraryRequestIn:
    return ItineraryRequestIn(
        trip_type=TripType.MULTI_CITY,
        origins=["TPE"],
        destinations=["NRT", "KIX"],
        strategies=[TicketStrategyType.STANDARD],
        date_windows=[
            DateWindowIn(
                role=DateWindowRole.SEGMENT,
                sequence=0,
                anchor_date=date(2027, 2, 5),
                flex_before=0,
                flex_after=1,
                segment_origin="TPE",
                segment_destination="NRT",
            ),
            DateWindowIn(
                role=DateWindowRole.SEGMENT,
                sequence=1,
                anchor_date=date(2027, 2, 8),
                flex_before=0,
                flex_after=1,
                segment_origin="KIX",
                segment_destination="TPE",
            ),
        ],
    )


def test_multi_city_builds_bundles_with_strict_order():
    _, plans, _ = SearchService(StubFlightProvider()).run(_multi_city_request())
    assert plans, "multi-city search should return at least one bundle"
    for p in plans:
        assert p.strategy is TicketStrategyType.STANDARD
        assert len(p.tickets) == 2
        # strict chronological order
        assert p.tickets[0].first_leg().departure < p.tickets[1].first_leg().departure
        assert p.tickets[0].origin == "TPE"
        assert p.tickets[0].final_destination == "NRT"
        assert p.tickets[1].origin == "KIX"
        assert p.tickets[1].final_destination == "TPE"


def test_multi_city_requires_per_segment_od():
    req = _multi_city_request()
    broken = req.model_copy(
        update={
            "date_windows": [
                w.model_copy(update={"segment_origin": None, "segment_destination": None})
                for w in req.date_windows
            ],
        }
    )
    _, plans, _ = SearchService(StubFlightProvider()).run(broken)
    assert plans == []
