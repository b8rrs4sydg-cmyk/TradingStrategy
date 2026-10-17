"""The stub's fare model must reproduce the market effects the strategies rely on."""

from datetime import date

from app.providers.cache import CachingProvider
from app.providers.stub import OUTSTATION_MULTI_CITY_FACTOR, StubFlightProvider, market_factor

LNY_DAY = date(2027, 2, 5)   # 春節 window start
QUIET_DAY = date(2027, 3, 17)


def test_holiday_surge_only_for_journeys_starting_in_taiwan():
    assert market_factor("TPE", LNY_DAY) > 1
    assert market_factor("NRT", LNY_DAY) == 1
    assert market_factor("TPE", QUIET_DAY) == 1


def test_taiwan_origin_round_trip_costs_more_than_reverse_in_holiday():
    p = StubFlightProvider()
    tw = p.search(origin="TPE", destination="NRT", departure_date=LNY_DAY, return_date=date(2027, 2, 14))[0]
    jp = p.search(origin="NRT", destination="TPE", departure_date=LNY_DAY, return_date=date(2027, 2, 14))[0]
    assert tw.total_price > jp.total_price * 1.15


def test_outstation_four_leg_is_one_ticket_priced_below_sum_of_one_ways():
    p = StubFlightProvider()
    segs = [("HKG", "TPE", date(2027, 2, 7)), ("TPE", "LHR", date(2027, 2, 7)),
            ("LHR", "TPE", date(2027, 2, 15)), ("TPE", "HKG", date(2027, 12, 23))]
    (ticket,) = p.search_multi_city(segments=segs)
    assert [(leg.origin, leg.destination) for leg in ticket.legs] == [(o, d) for o, d, _ in segs]
    one_ways = sum(p.search(origin=o, destination=d, departure_date=day)[0].total_price for o, d, day in segs)
    assert ticket.total_price < one_ways * (OUTSTATION_MULTI_CITY_FACTOR + 0.15)
    # leg1 → leg2 is a same-day connection at TPE on the same ticket
    gap = ticket.legs[1].departure - ticket.legs[0].arrival
    assert 0 < gap.total_seconds() < 24 * 3600


def test_caching_provider_memoizes_multi_city():
    c = CachingProvider(StubFlightProvider())
    segs = [("TPE", "NRT", LNY_DAY), ("KIX", "TPE", date(2027, 2, 14))]
    a = c.search_multi_city(segments=segs)
    b = c.search_multi_city(segments=segs)
    assert a is b and c.stats()["hits"] == 1
