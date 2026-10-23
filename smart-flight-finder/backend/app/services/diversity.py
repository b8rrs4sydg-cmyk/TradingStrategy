"""Ranking stage after scoring: completeness first, then a diverse top of the list.

* a plan whose total cost is incomplete (a needed cost is unknown) is never ranked above a complete plan — it keeps its
  place among incomplete ones, so unknown costs cannot make a plan look cheaper;
* the first ``k`` places are chosen so no more than ``per_group`` of them share a group (strategy + the metro
  destinations of the trips, roles and directions kept), filling the rest in the original score order. Nothing is
  removed from the list and no price changes; the cheapest plan of every group stays reachable.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.data.metro import route_key
from app.services.strategies.base import StrategyPlan


def group_of(plan: StrategyPlan) -> tuple:
    dests = tuple(route_key(t.legs[0].destination) for t in plan.tickets)
    origins = tuple(route_key(t.legs[-1].origin) for t in plan.tickets)
    return (plan.strategy, dests, origins)


def complete_first(plans: Sequence[StrategyPlan]) -> list[StrategyPlan]:
    return sorted(plans, key=lambda p: not p.cost_complete)  # stable: score order is kept inside each class


def diversify(plans: Sequence[StrategyPlan], *, k: int = 10, per_group: int = 2) -> list[StrategyPlan]:
    ordered = complete_first(plans)
    head: list[StrategyPlan] = []
    taken: dict[tuple, int] = {}
    rest: list[StrategyPlan] = []
    for p in ordered:
        g = group_of(p)
        if len(head) < k and taken.get(g, 0) < per_group:
            head.append(p)
            taken[g] = taken.get(g, 0) + 1
        else:
            rest.append(p)
    return head + rest
