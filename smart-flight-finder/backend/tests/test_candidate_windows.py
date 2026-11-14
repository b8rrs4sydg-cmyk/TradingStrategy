"""備選時段: user-adjusted (depart, return, ± flex) slots searched together."""

from datetime import date

import pytest
from pydantic import ValidationError

from app.models.enums import CabinClass, TicketStrategyType, TripType
from app.schemas.itinerary import CandidateWindowIn, ItineraryRequestIn
from app.services.search import SearchService
from tests.fake_fares import FakeFareProvider


def _req(windows: list[CandidateWindowIn], strategies=(TicketStrategyType.STANDARD,), **kw):
    return ItineraryRequestIn(
        trip_type=kw.pop("trip_type", TripType.ROUND_TRIP),
        cabin=CabinClass.ECONOMY,
        origins=["TPE"],
        destinations=["NRT"],
        strategies=list(strategies),
        back_to_back_outer_stations=["XMN"],
        candidate_windows=windows,
        **kw,
    )


def _slot(depart, ret, flex=0, **kw):
    return CandidateWindowIn(depart=depart, return_date=ret, depart_flex=flex, return_flex=flex, **kw)


def _run(req):
    return SearchService(FakeFareProvider()).run(req)


def test_candidate_windows_replace_date_windows_requirement():
    req = _req([_slot(date(2027, 2, 5), date(2027, 2, 15))])
    assert req.date_windows == []
    matrix, plans, _ = _run(req)
    assert matrix == 1
    assert plans


def test_each_slot_uses_its_own_adjusted_dates_and_flex():
    # User trimmed 春節 to 2/6–2/13 with ±0, and widened 聖誕 to ±2.
    req = _req([
        _slot(date(2027, 2, 6), date(2027, 2, 13), flex=0, holiday_key="lunar_ny"),
        _slot(date(2027, 12, 23), date(2027, 12, 27), flex=2, holiday_key="xmas"),
    ])
    matrix, plans, _ = _run(req)
    assert matrix == 1 + 5 * 5
    feb = [p for p in plans if p.tickets[0].legs[0].departure.month == 2]
    assert {p.tickets[0].legs[0].departure.date() for p in feb} == {date(2027, 2, 6)}
    dec_departs = {
        p.tickets[0].legs[0].departure.date()
        for p in plans
        if p.tickets[0].legs[0].departure.month == 12
    }
    assert dec_departs == {date(2027, 12, d) for d in range(21, 26)}


def test_plans_are_labelled_by_slot():
    req = _req([
        _slot(date(2027, 2, 5), date(2027, 2, 15), holiday_key="lunar_ny"),
        _slot(date(2027, 7, 1), date(2027, 7, 5), label="暑假自訂"),
        _slot(date(2027, 8, 1), date(2027, 8, 4)),
    ])
    _, plans, _ = _run(req)
    assert {p.window_label for p in plans} == {"春節請 2 休 11", "暑假自訂", "08/01–08/04"}


def test_overlapping_slots_do_not_duplicate_plans():
    same = _slot(date(2027, 12, 24), date(2027, 12, 27), flex=1)
    _, once, _ = _run(_req([same]))
    _, twice, _ = _run(_req([same, _slot(date(2027, 12, 24), date(2027, 12, 27), flex=1, label="dup")]))
    assert len(twice) == len(once)


def test_round_trip_slot_needs_return_date():
    with pytest.raises(ValidationError):
        _req([CandidateWindowIn(depart=date(2027, 2, 5))])


def test_return_before_depart_rejected():
    with pytest.raises(ValidationError):
        _slot(date(2027, 2, 10), date(2027, 2, 5))


def test_one_way_slot_ignores_return():
    req = _req([CandidateWindowIn(depart=date(2027, 2, 5), depart_flex=1)], trip_type=TripType.ONE_WAY)
    matrix, plans, _ = _run(req)
    assert matrix == 3
    assert all(len(p.tickets[0].legs) == 1 for p in plans)


def test_pair_strategies_only_pair_non_overlapping_slots():
    from app.services.search import _slot_pairs

    req = _req(
        [
            _slot(date(2027, 2, 5), date(2027, 2, 15), flex=1, holiday_key="lunar_ny"),
            _slot(date(2027, 2, 12), date(2027, 2, 20), flex=1, label="overlaps LNY"),
            _slot(date(2027, 12, 23), date(2027, 12, 27), flex=1, holiday_key="xmas"),
        ],
        strategies=(TicketStrategyType.REVERSE,),
    )
    pairs = [(a.label, b.label) for a, b in _slot_pairs(req)]
    assert ("春節請 2 休 11", "聖誕請 2 休 5") in pairs
    assert ("overlaps LNY", "聖誕請 2 休 5") in pairs
    assert all("overlaps LNY" not in (a, b) or "聖誕請 2 休 5" in (a, b) for a, b in pairs)
    assert ("聖誕請 2 休 5", "春節請 2 休 11") not in pairs  # B must come after A
