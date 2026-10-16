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
        if trip_type is TripType.MULTI_CITY:
            return self._plan_multi_city(expanded, adults=adults, max_results=max_results)
        return self._plan_round_trip(
            expanded,
            origins=origins,
            destinations=destinations,
            trip_type=trip_type,
            adults=adults,
            max_results=max_results,
        )

    # ------------------------------------------------------------------
    def _plan_round_trip(
        self,
        expanded: list[ExpandedWindow],
        *,
        origins: Iterable[str],
        destinations: Iterable[str],
        trip_type: TripType,
        adults: int,
        max_results: int,
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

    # ------------------------------------------------------------------
    def _plan_multi_city(
        self,
        expanded: list[ExpandedWindow],
        *,
        adults: int,
        max_results: int,
    ) -> list[StrategyPlan]:
        """Build N-leg one-way bundles for every pruned date combination."""

        segments = sorted(
            [w for w in expanded if w.role is DateWindowRole.SEGMENT],
            key=lambda w: w.sequence,
        )
        if len(segments) < 2:
            return []
        if any(not w.segment_origin or not w.segment_destination for w in segments):
            return []  # multi-city requires per-segment OD; nothing to search

        plans: list[StrategyPlan] = []
        for combo in iter_date_combos(segments, trip_type=TripType.MULTI_CITY):
            tickets = []
            total = 0
            currency = "TWD"
            for seg, day in zip(segments, combo):
                offers = self.provider.search(
                    origin=seg.segment_origin,  # type: ignore[arg-type]
                    destination=seg.segment_destination,  # type: ignore[arg-type]
                    departure_date=day,
                    return_date=None,
                    adults=adults,
                )
                if not offers:
                    tickets = None
                    break
                cheapest = min(offers, key=lambda o: o.total_price)
                tickets.append(cheapest)
                total += cheapest.total_price
                currency = cheapest.currency
            if not tickets:
                continue

            path = " → ".join(seg.segment_origin for seg in segments) + f" → {segments[-1].segment_destination}"
            travel_days = (combo[-1] - combo[0]).days + 1
            plans.append(
                StrategyPlan(
                    strategy=self.strategy,
                    tickets=tuple(tickets),
                    total_cost=total,
                    currency=currency,
                    total_travel_days=travel_days,
                    explain=f"Multi-city：{path} ({combo[0]} → {combo[-1]})",
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
