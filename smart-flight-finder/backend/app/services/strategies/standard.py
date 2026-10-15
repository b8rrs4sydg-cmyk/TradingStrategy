"""Standard point-to-point round-trip planner.

Loops the pruned date-combo matrix × origin × destination and asks the provider
for offers, then wraps the single cheapest offer per combo as a ``StrategyPlan``.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from app.models.enums import DateWindowRole, TicketStrategyType, TripType
from app.providers.base import FlightOfferProvider
from app.services.date_matrix import ExpandedWindow, iter_date_combos
from app.services.strategies.base import StrategyPlan


class StandardPlanner:
    strategy = TicketStrategyType.STANDARD

    def __init__(self, provider: FlightOfferProvider) -> None:
        self.provider = provider

    def plan(
        self,
        *,
        expanded: list[ExpandedWindow],
        origins: Iterable[str],
        destinations: Iterable[str],
        trip_type: TripType,
        adults: int = 1,
        max_results: int = 50,
    ) -> list[StrategyPlan]:
        plans: list[StrategyPlan] = []
        out_dates, ret_dates = _split_round_trip_candidates(expanded)
        if not out_dates:
            return plans

        for origin in origins:
            for destination in destinations:
                for out_date, ret_date in _pair_dates(out_dates, ret_dates, trip_type):
                    offers = self.provider.search(
                        origin=origin,
                        destination=destination,
                        departure_date=out_date,
                        return_date=ret_date,
                        adults=adults,
                    )
                    if not offers:
                        continue
                    cheapest = min(offers, key=lambda o: o.total_price)
                    travel_days = ((ret_date - out_date).days + 1) if ret_date else 1
                    plans.append(
                        StrategyPlan(
                            strategy=self.strategy,
                            tickets=(cheapest,),
                            total_cost=cheapest.total_price,
                            currency=cheapest.currency,
                            total_travel_days=travel_days,
                            explain=(
                                f"直購：{origin}→{destination} "
                                f"{out_date}"
                                + (f" / 回程 {ret_date}" if ret_date else "")
                            ),
                        )
                    )
        plans.sort(key=lambda p: p.total_cost)
        return plans[:max_results]


def _split_round_trip_candidates(
    expanded: list[ExpandedWindow],
) -> tuple[list[date], list[date]]:
    out, ret = [], []
    for w in expanded:
        if w.role is DateWindowRole.OUTBOUND:
            out.extend(w.candidates)
        elif w.role is DateWindowRole.RETURN:
            ret.extend(w.candidates)
    return sorted(set(out)), sorted(set(ret))


def _pair_dates(
    out_dates: list[date],
    ret_dates: list[date],
    trip_type: TripType,
    *,
    min_days_abroad: int = 1,
):
    if trip_type is TripType.ONE_WAY or not ret_dates:
        for d in out_dates:
            yield d, None
        return
    for o in out_dates:
        for r in ret_dates:
            if (r - o).days >= min_days_abroad:
                yield o, r


# Re-export iter_date_combos so callers can pre-prune using it; the planner
# above uses a flatter cartesian pairing for round-trip clarity.
__all__ = ["StandardPlanner", "iter_date_combos"]
