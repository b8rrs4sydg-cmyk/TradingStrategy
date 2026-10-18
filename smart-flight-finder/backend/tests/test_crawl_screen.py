"""One-way screening of 四腿票 in the backend crawl plan."""

from datetime import date

import pytest

from app.providers.google_flights import parse_key
from app.services.crawl_plan import (
    CrawlConfig,
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
    kept, pruned = screen_four_leg(four, cheap, CFG, drop_unknown=True)
    assert pruned == 0 and set(kept) == set(four)
    dear = prices_for(stage1, four, ow=1000, leg=9000)  # floor 0.95 x 36000 > room (36000 - 2000)
    kept, pruned = screen_four_leg(four, dear, CFG, drop_unknown=True, audit=3)
    assert pruned == len(four) and len(kept) == 3  # only the audit sample is still fetched


def test_unknown_legs_are_kept_unless_asked_to_drop_them(plan):
    stage1, _, four = plan
    prices = {k: (20000 if "|NRT|" in k else 8000) if k.startswith("rt|") else 1000 for k in stage1}
    kept, pruned = screen_four_leg(four, prices, CFG)
    assert kept == list(four) and pruned == 0
    kept, _ = screen_four_leg(four, prices, CFG, drop_unknown=True)
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
    kept, pruned = screen_four_leg(two, {}, CFG, drop_unknown=True)
    assert kept == two and pruned == 0
