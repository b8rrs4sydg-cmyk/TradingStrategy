"""Review follow-ups: open-jaw geography, Redis capability forwarding."""

from app.data.metro import Tier, transfer
from app.providers.redis_cache import RedisCachingProvider
from app.services.strategies.open_jaw import _distinct_pairs


def test_transfer_tiers():
    assert transfer("HND", "NRT").tier is Tier.SAME_METRO
    assert transfer("KIX", "UKB").tier is Tier.SAME_METRO
    t = transfer("HND", "KIX")
    assert t.tier is Tier.GROUND and t.cost_twd and t.minutes
    assert transfer("KIX", "OKA").tier is Tier.SEPARATE
    assert transfer("KIX", "CTS").tier is Tier.SEPARATE
    assert transfer("KIX", "HIJ").tier is Tier.UNKNOWN


def test_open_jaw_pairs_need_a_real_transfer():
    pairs = set(_distinct_pairs(["KIX", "OKA", "HND", "NRT", "HIJ", "ICN"]))
    assert ("HND", "KIX") in pairs and ("NRT", "HND") in pairs
    assert ("KIX", "OKA") not in pairs and ("OKA", "KIX") not in pairs  # island hop
    assert not any("HIJ" in p for p in pairs)  # no metro data: unverified
    assert not any("ICN" in p and p != ("ICN", "ICN") for p in pairs)  # other country alone
    assert ("KIX", "OKA") in set(_distinct_pairs(["KIX", "OKA"], allow_separate=True))


class _Live:
    def __init__(self):
        self.got = None

    def prefetch(self, keys):
        self.got = list(keys)
        return len(self.got)


class _Plain:
    pass


def test_redis_wrapper_forwards_prefetch_only_when_the_source_has_it():
    live = _Live()
    wrapped = RedisCachingProvider(live, client=None)
    assert (
        hasattr(wrapped, "prefetch")
        and wrapped.prefetch(["a", "b"]) == 2
        and live.got == ["a", "b"]
    )
    assert not hasattr(RedisCachingProvider(_Plain(), client=None), "prefetch")


def test_four_leg_outer_station_pattern_is_configurable():
    from datetime import date

    from app.services.strategies.back_to_back import FourLegPlanner
    from app.services.strategies.two_trip import TripSlot
    from tests.fake_fares import FakeFareProvider

    def slot(label, d, r):
        return TripSlot(label=label, departs=[date(2027, *d)], returns=[date(2027, *r)])

    p, q, r = slot("P", (2, 5), (2, 15)), slot("Q", (4, 3), (4, 11)), slot("R", (12, 23), (12, 27))

    def run(pattern, outer):
        return FourLegPlanner(FakeFareProvider(), pattern=pattern).plan(
            trip_p=p, trip_q=q, trip_r=r, outer_stations=outer, destinations=["LHR"]
        )

    def ends(plans):
        return {(pl.tickets[1].legs[0].origin, pl.tickets[1].legs[-1].destination) for pl in plans}

    assert run("different", ["NRT", "KIX"]) == []  # same country ends: excluded
    assert ends(run("same", ["NRT", "KIX"]))  # ... allowed with the profile
    assert ends(run("any", ["HKG", "ICN"]))


def test_date_combos_pruned_early_match_the_filtered_cartesian_product():
    from datetime import date, timedelta
    from itertools import product

    from app.models.enums import DateWindowRole, TripType
    from app.services.date_matrix import ExpandedWindow, iter_date_combos

    def win(start, n, role, seq):
        days = tuple(start + timedelta(days=i) for i in range(n))
        return ExpandedWindow(role=role, sequence=seq, anchor_date=days[0], candidates=days)

    wins = [
        win(date(2027, 2, 1), 9, DateWindowRole.OUTBOUND, 0),
        win(date(2027, 2, 3), 9, DateWindowRole.RETURN, 1),
    ]
    got = list(
        iter_date_combos(wins, trip_type=TripType.ROUND_TRIP, min_days_abroad=3, max_days_abroad=6)
    )
    want = [c for c in product(*(w.candidates for w in wins)) if 3 <= (c[1] - c[0]).days <= 6]
    assert got == want and got


def test_page_metro_table_matches_python():
    import json
    import re
    from pathlib import Path

    from app.data.metro import GROUND, METRO_OF, SAME_METRO_TRANSFER

    html = (Path(__file__).resolve().parents[2] / "public" / "index.html").read_text(
        encoding="utf-8"
    )
    block = html[html.index("// BEGIN-METRO") : html.index("// END-METRO")]
    metro = dict(re.findall(r"(\w+):'(\w+)'", block.split("const GROUND")[0]))
    assert metro == METRO_OF
    ground = {
        k: tuple(v)
        for k, v in json.loads(
            re.search(r"const GROUND = (\{.*?\});", block).group(1).replace("'", '"')
        ).items()
    }
    assert ground == {"|".join(sorted(k)): v for k, v in GROUND.items()}
    assert SAME_METRO_TRANSFER == (75, 400)  # hard-coded in ojTransfer


def test_fare_status_policy():
    from app.providers.fare_status import FareStatus, is_failure, may_mark_unavailable, retry_after

    assert may_mark_unavailable(FareStatus.NO_RESULT)
    assert not any(may_mark_unavailable(s) for s in FareStatus if s is not FareStatus.NO_RESULT)
    assert all(
        is_failure(s) for s in (FareStatus.TIMEOUT, FareStatus.BLOCKED, FareStatus.PARSE_ERROR)
    )
    assert (
        retry_after(FareStatus.TIMEOUT, 1)
        < retry_after(FareStatus.TIMEOUT, 3)
        <= retry_after(FareStatus.TIMEOUT, 99)
    )
    assert retry_after(FareStatus.BLOCKED) > retry_after(FareStatus.TIMEOUT)
    assert retry_after(FareStatus.NOT_QUERIED) == 0


def test_outstation_pattern_reaches_the_crawl_plan(monkeypatch):
    """OUTSTATION_PATTERN widens the crawl too, because the crawl plan runs the same planner."""

    from datetime import date

    from app.services.crawl_plan import CrawlConfig, planner_queries

    cfg = CrawlConfig(
        destinations=["LHR"],
        outer_stations=["NRT", "KIX", "HKG"],
        holidays=["lunar_ny", "qingming", "duanwu"],
    )

    monkeypatch.setenv("OUTSTATION_PATTERN", "different")
    base = set(planner_queries(cfg, today=date(2026, 10, 17)))
    monkeypatch.setenv("OUTSTATION_PATTERN", "any")
    wide = set(planner_queries(cfg, today=date(2026, 10, 17)))
    assert base < wide  # strictly more queries once same-country ends (NRT … KIX) are allowed


def test_failures_are_recorded_counted_and_cleared_when_priced(tmp_path):
    from datetime import UTC, datetime

    from app.providers.fare_db import FareDatabase

    path = tmp_path / "fares-live.json"
    today = datetime.now(UTC).date()
    key = "ow|TPE|NRT|2099-04-01"
    for expected in (1, 2):
        db = FareDatabase.merge_into_file(path, {}, today=today, failures={key: "timeout"})
        assert db.status[key]["n"] == expected and key not in db.missing
    assert FareDatabase.load(path).status[key]["status"] == "timeout"  # persisted, optional field
    db = FareDatabase.merge_into_file(path, {key: {"price": 5000}}, today=today)
    assert key not in db.status and key in db.fares  # priced: the failure is forgotten


def test_http_reader_remembers_why_it_gave_no_price():
    import asyncio

    from app.providers.google_http import HttpFetcher

    f = HttpFetcher(timeout=1, attempts=1)

    async def blocked(key, segments):
        raise PermissionError("429")

    f._answer = blocked
    out = asyncio.run(f.fetch("ow|TPE|NRT|2027-04-01"))
    assert out is None and f.why["ow|TPE|NRT|2027-04-01"] == "blocked"


def test_default_pattern_allows_same_country_ends_but_not_d_in_their_country():
    from datetime import date

    from app.services.strategies.back_to_back import FourLegPlanner
    from app.services.strategies.two_trip import TripSlot
    from tests.fake_fares import FakeFareProvider

    def slot(label, d, r):
        return TripSlot(label=label, departs=[date(2027, *d)], returns=[date(2027, *r)])

    plans = FourLegPlanner(FakeFareProvider()).plan(
        trip_p=slot("P", (2, 5), (2, 15)),
        trip_q=slot("Q", (4, 3), (4, 11)),
        trip_r=slot("R", (12, 23), (12, 27)),
        outer_stations=["NRT", "KIX"],
        destinations=["LHR", "HND"],
    )
    ends = {(p.tickets[1].legs[0].origin, p.tickets[1].legs[3].destination) for p in plans}
    assert ends
    assert all(
        p.tickets[1].legs[1].destination == "LHR" for p in plans
    )  # HND shares Japan with both ends: excluded
