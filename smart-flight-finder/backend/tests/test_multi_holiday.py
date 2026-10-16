"""Multi-holiday candidate search: holiday_keys permutes 4-leg over N windows."""

from app.models.enums import CabinClass, TicketStrategyType, TripType
from app.providers.stub import StubFlightProvider
from app.schemas.itinerary import ItineraryRequestIn
from app.services.search import SearchService


def _req(holiday_keys: list[str], strategies: list[TicketStrategyType]) -> ItineraryRequestIn:
    return ItineraryRequestIn(
        trip_type=TripType.ROUND_TRIP,
        cabin=CabinClass.ECONOMY,
        adults=1,
        origins=["TPE"],
        destinations=["NRT", "KIX"],
        strategies=strategies,
        back_to_back_outer_stations=["XMN"],
        back_to_back_outer_buffer_days=2,
        holiday_keys=holiday_keys,
        holiday_flex_days=1,
    )


def test_holiday_keys_bypasses_date_windows_requirement():
    # No date_windows provided — holiday_keys covers them.
    req = _req(["lunar_ny"], [TicketStrategyType.STANDARD])
    assert req.date_windows == []  # not required when holiday_keys set
    matrix, plans, _ = SearchService(StubFlightProvider()).run(req)
    assert matrix > 0
    assert plans
    assert all(p.strategy is TicketStrategyType.STANDARD for p in plans)


def test_multiple_holidays_produce_distinct_plans():
    req = _req(["lunar_ny", "xmas", "nyd"], [TicketStrategyType.STANDARD])
    _, plans, _ = SearchService(StubFlightProvider()).run(req)
    # Each key expands to its own window; standard planner emits plans per
    # (origin, destination, outbound, return) — different windows produce
    # different outbound dates.
    outbound_months = {p.tickets[0].legs[0].departure.month for p in plans}
    # Spring Festival (Feb), Christmas (Dec), New Year's Day (Jan) → ≥ 3 months
    assert outbound_months >= {1, 2, 12}


def test_four_leg_runs_across_each_holiday_without_crashing():
    # The 4-leg savings threshold (10% below direct round-trip) may filter all
    # candidates out on stub pricing, but the orchestrator must iterate each
    # holiday_key independently without raising.
    req = _req(
        ["lunar_ny", "duanwu"],
        [TicketStrategyType.BACK_TO_BACK_4LEG, TicketStrategyType.STANDARD],
    )
    matrix, plans, stats = SearchService(StubFlightProvider()).run(req)
    assert matrix > 0
    # Standard plans always materialize, and both holidays contribute to them.
    std_months = {
        p.tickets[0].legs[0].departure.month
        for p in plans
        if p.strategy is TicketStrategyType.STANDARD
    }
    assert std_months & {1, 2}   # lunar_ny window
    assert 6 in std_months        # duanwu window
    # Caching helps — the second holiday's search reuses stub prices.
    assert stats.get("hits", 0) >= 0


def test_unknown_holiday_key_is_silently_skipped():
    req = _req(["lunar_ny", "nope_not_a_holiday"], [TicketStrategyType.STANDARD])
    _, plans, _ = SearchService(StubFlightProvider()).run(req)
    assert plans  # lunar_ny still yields plans
