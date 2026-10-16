from datetime import date

from app.models.enums import DateWindowRole, TicketStrategyType, TripType
from app.providers.stub import StubFlightProvider
from app.schemas.itinerary import DateWindowIn, ItineraryRequestIn
from app.services.search import SearchService


def _req() -> ItineraryRequestIn:
    return ItineraryRequestIn(
        trip_type=TripType.ROUND_TRIP,
        origins=["TPE"],
        destinations=["NRT", "KIX"],
        strategies=[TicketStrategyType.OPEN_JAW],
        date_windows=[
            DateWindowIn(role=DateWindowRole.OUTBOUND, anchor_date=date(2027, 2, 5),
                         flex_before=0, flex_after=1),
            DateWindowIn(role=DateWindowRole.RETURN, anchor_date=date(2027, 2, 11),
                         flex_before=0, flex_after=1),
        ],
    )


def test_open_jaw_requires_two_destinations():
    req = _req()
    req_single = req.model_copy(update={"destinations": ["NRT"]})
    _, plans, _ = SearchService(StubFlightProvider()).run(req_single)
    assert plans == []


def test_open_jaw_pairs_distinct_destinations():
    _, plans, _ = SearchService(StubFlightProvider()).run(_req())
    for p in plans:
        assert p.strategy is TicketStrategyType.OPEN_JAW
        assert len(p.tickets) == 2
        a_dest = p.tickets[0].final_destination
        b_origin = p.tickets[1].origin
        assert a_dest != b_origin, f"open-jaw should enter {a_dest} and leave from a different city"
