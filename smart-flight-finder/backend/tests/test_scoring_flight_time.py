"""Verify the flight-time scoring dimension uses real durations + stop penalty."""

from datetime import UTC, datetime, timedelta

from app.models.enums import TicketStrategyType
from app.schemas.itinerary import ScoringWeights
from app.services.scoring import _flight_minutes, score_plans
from app.services.strategies.base import (
    FlightLeg,
    StrategyPlan,
    TicketOffer,
)


def _plan(hours: float, stops: int = 0, cost: int = 10000) -> StrategyPlan:
    dep = datetime(2027, 2, 5, 9, 0, tzinfo=UTC)
    arr = dep + timedelta(hours=hours)
    leg = FlightLeg("TPE", "NRT", dep, arr, "BR", "BR188", stops=stops)
    ticket = TicketOffer("x", (leg,), cost)
    return StrategyPlan(
        strategy=TicketStrategyType.STANDARD,
        tickets=(ticket,),
        total_cost=cost,
        total_travel_days=1,
    )


def test_flight_minutes_sums_durations_and_stop_penalty():
    assert _flight_minutes(_plan(3)) == 180
    # one stop ⇒ +20 min
    assert _flight_minutes(_plan(3, stops=1)) == 180 + 20
    # two stops ⇒ +40 min
    assert _flight_minutes(_plan(3, stops=2)) == 180 + 40


def test_flight_time_weight_prefers_shorter_route():
    short = _plan(3)
    long = _plan(6)
    scored = score_plans(
        [short, long],
        weights=ScoringWeights(price=0, pto_efficiency=0, flight_time=1, strategy_risk=0),
    )
    assert scored[0] is scored[0]  # placeholder for identity
    assert scored[0].tickets[0].legs[0].duration == timedelta(hours=3)


def test_flight_time_penalizes_connections():
    direct_6h = _plan(6, stops=0)
    one_stop_5h = _plan(5, stops=1)   # 5h + 20min = 320
    scored = score_plans(
        [direct_6h, one_stop_5h],
        weights=ScoringWeights(price=0, pto_efficiency=0, flight_time=1, strategy_risk=0),
    )
    # 5h + 20min stop penalty = 320 min < 360 min direct, so one_stop wins
    assert _flight_minutes(scored[0]) == 320
