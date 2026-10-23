"""One-way screening of 四腿票 in the backend crawl plan."""

from datetime import date

import pytest

from app.providers.google_flights import parse_key
from app.services.crawl_plan import (
    CrawlConfig,
    four_leg_room,
    leg_keys,
    one_way_floor,
    planner_queries,
    screen_four_leg,
    split_stages,
    with_leg_keys,
)

TODAY = date(2026, 10, 17)
CFG = CrawlConfig(
    destinations=["NRT"], outer_stations=["HKG", "ICN"], holidays=["lunar_ny", "qingming", "duanwu"]
)


@pytest.fixture(scope="module")
def plan():
    stage1, mc = split_stages(planner_queries(CFG, today=TODAY))
    return stage1, mc, [k for k in mc if len(parse_key(k)[1]) == 4]


def prices_for(stage1, four, *, rt_nrt=20000, rt_other=8000, ow=1000, leg=None):
    """Stage-1 prices plus a price for every one-way leg (``leg`` overrides ``ow``)."""

    prices = {
        k: (rt_nrt if "|NRT|" in k else rt_other) if k.startswith("rt|") else ow for k in stage1
    }
    for key in four:
        for lk in leg_keys(key):
            prices.setdefault(lk, ow if leg is None else leg)
    return prices


def test_leg_keys_are_the_one_way_query_of_every_segment(plan):
    _, _, four = plan
    legs = leg_keys(four[0])
    assert len(legs) == 4 and all(k.startswith("ow|") for k in legs)
    (x, _, c1), _, _, (_, y, c4) = parse_key(four[0])[1]
    assert legs[0] == f"ow|{x}|TPE|{c1}" and legs[3] == f"ow|TPE|{y}|{c4}"


def test_with_leg_keys_adds_each_leg_once(plan):
    stage1, _, four = plan
    out = with_leg_keys(stage1, four)
    assert out[: len(stage1)] == stage1
    assert len(out) == len(set(out)) and len(out) > len(stage1)
    assert all(k.startswith("ow|") for k in out[len(stage1) :])


def test_cheap_legs_keep_the_combinations_dear_legs_prune_them(plan):
    stage1, _, four = plan
    cheap = prices_for(stage1, four, ow=500, leg=500)  # floor 0.95 x 2000 << room
    kept, audit, pruned = screen_four_leg(four, cheap, CFG, drop_unknown=True, enabled=True)
    assert pruned == 0 and audit == [] and set(kept) == set(four)
    dear = prices_for(stage1, four, ow=1000, leg=9000)  # floor 0.95 x 36000 > room (36000 - 2000)
    kept, audit, pruned = screen_four_leg(four, dear, CFG, drop_unknown=True, audit=3, enabled=True)
    assert kept == [] and len(audit) == 3 and pruned == len(four) - 3  # only the audit sample is still fetched


def test_unknown_legs_are_kept_unless_asked_to_drop_them(plan):
    stage1, _, four = plan
    prices = {k: (20000 if "|NRT|" in k else 8000) if k.startswith("rt|") else 1000 for k in stage1}
    kept, _, pruned = screen_four_leg(four, prices, CFG, enabled=True)
    assert kept == list(four) and pruned == 0
    kept, _, _ = screen_four_leg(four, prices, CFG, drop_unknown=True, enabled=True)
    assert (
        kept == []
    )  # the legs were asked for but Google has no flight: the itinerary cannot exist


def test_the_floor_is_a_discount_on_the_sum_of_the_legs(plan):
    stage1, _, four = plan
    prices = prices_for(stage1, four, leg=2000)
    assert one_way_floor(four[0], prices) == pytest.approx(0.95 * 8000)
    assert one_way_floor(four[0], {}) is None


def test_two_segment_keys_are_not_screened(plan):
    _, mc, _ = plan
    two = [k for k in mc if len(parse_key(k)[1]) == 2]
    if not two:
        pytest.skip("this scenario makes no open-jaw queries")
    kept, _, pruned = screen_four_leg(two, {}, CFG, drop_unknown=True, enabled=True)
    assert kept == two and pruned == 0


def test_audit_keys_survive_ranking_when_the_caller_appends_them(plan):
    """rank_multi_city keeps one key per group: audit keys would never be fetched if they went through it."""

    from app.services.crawl_plan import rank_multi_city

    stage1, mc, four = plan
    dear = prices_for(stage1, four, ow=1000, leg=9000)
    kept, audit, _ = screen_four_leg(mc, dear, CFG, audit=5, enabled=True)
    assert len(audit) == 5
    ranked = rank_multi_city(kept, dear, CFG, max_multi_city=260)
    assert not set(audit) & set(ranked)  # ranking alone loses them ...
    ranked += [k for k in audit if k not in ranked]
    assert set(audit) <= set(ranked)  # ... appending them afterwards keeps them


def test_screening_is_off_by_default_and_keeps_every_key(plan):
    _, _, four = plan
    prices = prices_for(plan[0], four, ow=1000, leg=9000)  # dear legs: the old screen would prune them all
    kept, audit, pruned = screen_four_leg(four, prices, CFG)
    assert kept == list(four) and audit == [] and pruned == 0


def test_four_leg_hits_counts_tickets_cheaper_than_their_saving_room(plan):
    from app.services.crawl_plan import four_leg_hits

    stage1, _, four = plan
    prices = prices_for(stage1, four)
    key = four[0]
    room = four_leg_room(key, prices, CFG)[0]
    assert room
    cheap = {key: {"price": int(room) - 1}}
    dear = {key: {"price": int(room) + 1}}
    assert four_leg_hits(cheap, prices, CFG) == (1, 1)
    assert four_leg_hits(dear, prices, CFG) == (0, 1)


def test_carrier_network_knows_which_airline_flies_every_leg():
    from app.services.crawl_plan import NETWORK_BONUS, CarrierNetwork

    fares = {
        "ow|TPE|ICN|2027-01-09": {"price": 4800, "by_airline": {"EVA Air": 5200, "Scoot": 4800}},
        "rt|TPE|CDG|2026-12-29|2027-01-08": {"price": 32455, "by_airline": {"EVA Air": 41000, "Cathay Pacific": 32455}},
        "ow|TPE|BKK|2027-02-01": {"price": 3000, "by_airline": {"Thai": 3000}},
    }
    net = CarrierNetwork.from_fares(fares)
    four = "mc|ICN-TPE-2026-11-06|TPE-CDG-2026-12-29|CDG-TPE-2027-01-08|TPE-ICN-2027-01-09"
    assert net.common([("ICN", "TPE"), ("TPE", "CDG")]) == {"EVA Air"}  # direction-free
    assert net.bonus(four) == NETWORK_BONUS
    other = "mc|BKK-TPE-2026-11-06|TPE-CDG-2026-12-29|CDG-TPE-2027-01-08|TPE-ICN-2027-01-09"
    assert net.bonus(other) == 0.0  # Thai flies BKK only, nobody known on all legs
    assert net.common([("TPE", "XXX")]) is None  # no data is unknown, not "no airline"


def test_by_airline_is_kept_per_single_airline_row():
    from app.providers.google_flights import cheapest_entry
    from app.providers.google_flights import parse_key as pk

    label = lambda price, airline: (
        f"From {price} New Taiwan dollars round trip total. Nonstop flight with {airline}. "
        "Leaves Taipei at 10:00 AM on Friday, January 8 and arrives at Seoul at 1:30 PM on Friday, January 8."
    )
    entry = cheapest_entry(
        [label(5200, "EVA Air"), label(4800, "Scoot"), label(6000, "EVA Air and ANA")], pk("ow|TPE|ICN|2027-01-08")[1]
    )
    assert entry["price"] == 4800 and entry["by_airline"] == {"Scoot": 4800, "EVA Air": 5200}
