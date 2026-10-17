"""End-to-end search service tests (stub provider, no network)."""

from datetime import date

from fastapi.testclient import TestClient

from app.main import app
from app.models.enums import (
    CabinClass,
    DateWindowRole,
    TicketStrategyType,
    TripType,
)
from app.providers.stub import StubFlightProvider
from app.schemas.itinerary import DateWindowIn, ItineraryRequestIn
from app.services.search import SearchService

client = TestClient(app)


def _round_trip_request(**overrides) -> dict:
    base = {
        "trip_type": TripType.ROUND_TRIP.value,
        "cabin": CabinClass.ECONOMY.value,
        "adults": 1,
        "origins": ["TPE"],
        "destinations": ["NRT"],
        "strategies": [TicketStrategyType.STANDARD.value],
        "date_windows": [
            {
                "role": DateWindowRole.OUTBOUND.value,
                "anchor_date": "2027-02-05",
                "flex_before": 1,
                "flex_after": 1,
            },
            {
                "role": DateWindowRole.RETURN.value,
                "anchor_date": "2027-02-11",
                "flex_before": 1,
                "flex_after": 1,
            },
        ],
    }
    base.update(overrides)
    return base


def test_search_standard_returns_plans_sorted_by_score():
    resp = client.post("/search", json=_round_trip_request())
    assert resp.status_code == 200
    body = resp.json()
    assert body["date_matrix_size"] == 9
    plans = body["plans"]
    assert plans
    assert all(p["strategy"] == TicketStrategyType.STANDARD.value for p in plans)
    scores = [p["score"] for p in plans if p["score"] is not None]
    assert scores == sorted(scores, reverse=True)


def test_single_window_pair_strategies_explain_why_empty():
    req = ItineraryRequestIn(
        trip_type=TripType.ROUND_TRIP,
        origins=["TPE"],
        destinations=["NRT"],
        strategies=[TicketStrategyType.BACK_TO_BACK_4LEG, TicketStrategyType.REVERSE],
        back_to_back_outer_stations=["HKG"],
        date_windows=[
            DateWindowIn(role=DateWindowRole.OUTBOUND, anchor_date=date(2027, 2, 5)),
            DateWindowIn(role=DateWindowRole.RETURN, anchor_date=date(2027, 2, 11)),
        ],
    )
    service = SearchService(StubFlightProvider())
    _, plans, _ = service.run(req)
    assert plans == []
    assert service.notices and "兩個" in service.notices[0]


def test_budget_filter():
    req_dict = _round_trip_request(max_total_budget=100)
    resp = client.post("/search", json=req_dict)
    assert resp.status_code == 200
    assert resp.json()["plans"] == []
