"""Search-algorithm checks: ground truth against brute force, validation, completeness and diversity."""

from datetime import date, timedelta
from itertools import product

from app.models.enums import DateWindowRole, TicketStrategyType
from app.services.diversity import complete_first, diversify, group_of
from app.services.strategies import OpenJawPlanner
from app.services.strategies.base import FlightLeg, StrategyPlan, TicketOffer


def _expanded():
    from app.services.date_matrix import ExpandedWindow

    out = tuple(date(2027, 2, 5) + timedelta(days=i) for i in range(3))
    ret = tuple(date(2027, 2, 12) + timedelta(days=i) for i in range(3))
    return [
        ExpandedWindow(
            role=DateWindowRole.OUTBOUND, sequence=0, anchor_date=out[0], candidates=out
        ),
        ExpandedWindow(role=DateWindowRole.RETURN, sequence=1, anchor_date=ret[0], candidates=ret),
    ]


class _Fares:
    """One-ways cost 1500 + 100 x day-of-month, round trips 12000: open jaws win, and the minimum is easy to know."""

    name = "fixture"

    def _offer(self, o, d, day, price, ret=None):
        from datetime import UTC, datetime

        dep = datetime(day.year, day.month, day.day, 9, tzinfo=UTC)
        legs = [FlightLeg(o, d, dep, dep + timedelta(hours=3), "XX", "XX1")]
        if ret:
            back = datetime(ret.year, ret.month, ret.day, 9, tzinfo=UTC)
            legs.append(FlightLeg(d, o, back, back + timedelta(hours=3), "XX", "XX2"))
        return TicketOffer(f"{o}{d}{day}{ret}", tuple(legs), price)

    def search(self, *, origin, destination, departure_date, return_date=None, adults=1):
        price = 12000 if return_date else 1500 + 100 * departure_date.day
        return [self._offer(origin, destination, departure_date, price, return_date)]

    def search_multi_city(self, *, segments, adults=1):
        return []


def test_open_jaw_best_plan_equals_brute_force_over_the_same_fares():
    """Ground truth: on a tiny search space the planner's cheapest plan is the true minimum found by full enumeration."""

    from app.data.metro import transfer

    provider = _Fares()
    ex = _expanded()
    plans = OpenJawPlanner(provider).plan(
        expanded=ex, origins=["TPE"], destinations=["HND", "NRT", "KIX"], max_results=1000
    )
    assert plans
    out_dates, ret_dates = ex[0].candidates, ex[1].candidates
    best = min(
        provider.search(origin="TPE", destination=a, departure_date=od)[0].total_price
        + provider.search(origin=b, destination="TPE", departure_date=rd)[0].total_price
        + (transfer(a, b).cost_twd or 0)
        for a, b in [
            ("HND", "NRT"),
            ("NRT", "HND"),
            ("HND", "KIX"),
            ("KIX", "HND"),
            ("NRT", "KIX"),
            ("KIX", "NRT"),
        ]
        for od, rd in product(out_dates, ret_dates)
    )
    assert min(p.total_cost for p in plans) == best
    assert all(p.cost_complete for p in plans)


def _plan(strategy, dest, cost, complete=True):
    t = datetime_ticket(dest)
    return StrategyPlan(strategy=strategy, tickets=(t,), total_cost=cost, cost_complete=complete)


def datetime_ticket(dest):
    from datetime import UTC, datetime

    dep = datetime(2027, 2, 5, 8, tzinfo=UTC)
    leg = FlightLeg("TPE", dest, dep, dep + timedelta(hours=3), "XX", "XX1")
    return TicketOffer(offer_id=f"t-{dest}", legs=(leg,), total_price=1)


def test_incomplete_cost_never_outranks_a_complete_plan():
    cheap_unknown = _plan(TicketStrategyType.OPEN_JAW, "KIX", 5000, complete=False)
    dear_complete = _plan(TicketStrategyType.OPEN_JAW, "NRT", 9000)
    assert complete_first([cheap_unknown, dear_complete])[0] is dear_complete


def test_diversify_limits_a_group_in_the_top_but_loses_nothing():
    plans = [_plan(TicketStrategyType.STANDARD, "KIX", 1000 + i) for i in range(5)]
    plans += [
        _plan(TicketStrategyType.STANDARD, "NRT", 2000),
        _plan(TicketStrategyType.OPEN_JAW, "KIX", 2100),
    ]
    out = diversify(plans, k=4, per_group=2)
    assert sorted(id(p) for p in out) == sorted(id(p) for p in plans)
    assert (
        sum(group_of(p) == group_of(plans[0]) for p in out[:4]) == 2
    )  # the cheap KIX plans do not fill the top
    assert out[0] is plans[0]  # the cheapest stays first


def test_four_leg_validator_rejects_a_ticket_that_is_not_the_intended_itinerary():
    from app.services.strategies.back_to_back import _four_leg_matches

    d = [date(2027, 2, 8), date(2027, 4, 3), date(2027, 4, 9), date(2027, 12, 23)]
    segs = (("HKG", "TPE", d[0]), ("TPE", "NRT", d[1]), ("NRT", "TPE", d[2]), ("TPE", "ICN", d[3]))
    from datetime import UTC, datetime

    def leg(o, dd, day):
        dep = datetime(day.year, day.month, day.day, 9, tzinfo=UTC)
        return FlightLeg(o, dd, dep, dep + timedelta(hours=3), "XX", "XX1")

    good = TicketOffer(
        "g", tuple(leg(o, dd, day) for o, dd, day in segs), 1, searched_segments=segs
    )
    assert _four_leg_matches(good, "HKG", "NRT", "ICN", *d)
    wrong_order = TicketOffer(
        "w", good.legs[:2] + (leg("TPE", "NRT", d[2]), good.legs[3]), 1, searched_segments=segs
    )
    assert not _four_leg_matches(wrong_order, "HKG", "NRT", "ICN", *d)
    other = TicketOffer("o", good.legs, 1, searched_segments=(*segs[:3], ("TPE", "BKK", d[3])))
    assert not _four_leg_matches(other, "HKG", "NRT", "ICN", *d)
