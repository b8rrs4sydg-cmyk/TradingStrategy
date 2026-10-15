from app.models.enums import TicketStrategyType
from app.schemas.itinerary import ScoringWeights
from app.services.scoring import score_plans
from app.services.strategies.base import (
    FlightLeg,
    RiskLevel,
    RiskWarning,
    StrategyPlan,
    TicketOffer,
)
from datetime import datetime, timedelta, timezone


def _leg(hour: int):
    base = datetime(2027, 2, 5, hour, 0, tzinfo=timezone.utc)
    return FlightLeg("TPE", "NRT", base, base + timedelta(hours=3), "BR", "BR188")


def _ticket(price: int, n_legs: int) -> TicketOffer:
    return TicketOffer("x", tuple(_leg(h) for h in range(n_legs or 1)), price)


def _plan(strategy: TicketStrategyType, cost: int, legs: int = 1, risks: tuple[RiskLevel, ...] = ()) -> StrategyPlan:
    return StrategyPlan(
        strategy=strategy,
        tickets=(_ticket(cost, legs),),
        total_cost=cost,
        total_travel_days=5,
        warnings=tuple(RiskWarning(level=r, code="x", message="y") for r in risks),
    )


def test_score_prefers_cheapest_when_price_weight_only():
    plans = [
        _plan(TicketStrategyType.STANDARD, 20000),
        _plan(TicketStrategyType.STANDARD, 10000),
        _plan(TicketStrategyType.STANDARD, 15000),
    ]
    scored = score_plans(
        plans,
        weights=ScoringWeights(price=1, pto_efficiency=0, flight_time=0, strategy_risk=0),
    )
    assert scored[0].total_cost == 10000
    assert scored[-1].total_cost == 20000


def test_high_risk_lowers_score_when_risk_weighted():
    cheap_but_risky = _plan(
        TicketStrategyType.BACK_TO_BACK_4LEG,
        10000,
        legs=1,
        risks=(RiskLevel.HIGH, RiskLevel.MEDIUM),
    )
    pricier_safe = _plan(TicketStrategyType.STANDARD, 11000, legs=1, risks=())
    scored = score_plans(
        [cheap_but_risky, pricier_safe],
        weights=ScoringWeights(price=0.2, pto_efficiency=0, flight_time=0, strategy_risk=0.8),
    )
    assert scored[0].strategy is TicketStrategyType.STANDARD


def test_empty_input_returns_empty():
    assert score_plans([]) == []
