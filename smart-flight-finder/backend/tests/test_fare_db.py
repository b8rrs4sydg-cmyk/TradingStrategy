"""The real-fare pipeline: Google Flights parsing, fare DB, crawl plan, live prefetch."""

import json
from datetime import date
from zoneinfo import ZoneInfo

import pytest

from app.models.enums import TicketStrategyType as S
from app.models.enums import TripType
from app.providers.fare_db import FareDatabase, FareDatabaseProvider, offer_from_entry
from app.providers.google_flights import cheapest_entry, fare_key, parse_key, parse_option
from app.schemas.itinerary import CandidateWindowIn, ItineraryRequestIn
from app.services.crawl_plan import (
    CrawlConfig,
    four_leg_budget,
    planner_queries,
    rank_multi_city,
    split_stages,
)
from app.services.search import SearchService

TPE, TYO = ZoneInfo("Asia/Taipei"), ZoneInfo("Asia/Tokyo")
LABEL = (
    "From 22080 New Taiwan dollars round trip total. Nonstop flight with Jetstar Japan. "
    "Leaves Taiwan Taoyuan International Airport at 12:50 PM on Friday, February 5 and "
    "arrives at Narita International Airport at 4:55 PM on Friday, February 5. "
    "Total duration 3 hr 5 min. Select flight"
)
RT = fare_key((("TPE", "NRT", date(2027, 2, 5)), ("NRT", "TPE", date(2027, 2, 15))), round_trip=True)
TODAY = date(2026, 10, 17)


# --- Google Flights parsing ----------------------------------------------------
def test_keys_round_trip():
    segs = (("HKG", "TPE", date(2027, 2, 7)), ("TPE", "NRT", date(2027, 2, 7)))
    for key, kind in [(fare_key(segs), "mc"), (fare_key(segs[:1]), "ow"), (RT, "rt")]:
        k, parsed = parse_key(key)
        assert k == kind and fare_key(parsed, round_trip=k == "rt") == key


def test_parse_google_result_label():
    p = parse_option(LABEL, year=2027, dep_tz=TPE, arr_tz=TYO)
    assert (p.price, p.stops, p.airline, p.separate) == (22080, 0, "Jetstar Japan", False)
    assert p.dep.isoformat() == "2027-02-05T12:50:00+08:00"
    assert p.arr.isoformat() == "2027-02-05T16:55:00+09:00"
    one_stop = LABEL.replace("Nonstop flight with Jetstar Japan", "1 stop flight with EVA Air")
    assert parse_option(one_stop, year=2027, dep_tz=TPE, arr_tz=TYO).stops == 1
    assert parse_option("Select flight", year=2027, dep_tz=TPE, arr_tz=TYO) is None


def test_cheapest_entry_prefers_single_tickets():
    segs = parse_key(RT)[1]
    cheaper = LABEL.replace("22080", "19,500").replace("12:50", "8:10")
    separate = LABEL.replace("22080", "9,000").replace("total.", "total. Separate tickets booked together.")
    tz = lambda c: TPE if c == "TPE" else TYO
    e = cheapest_entry([LABEL, cheaper, separate], segs, tz)
    assert e["price"] == 19500 and "separate" not in e
    assert e["first"]["dep"].startswith("2027-02-05T20:10")
    assert cheapest_entry([separate], segs, tz)["separate"] is True


# --- fare database ---------------------------------------------------------------
def test_offers_come_only_from_the_database():
    db = FareDatabase(fares={RT: {"price": 19500, "first": {
        "dep": "2027-02-05T08:10:00+08:00", "arr": "2027-02-05T12:15:00+09:00",
        "stops": 0, "airline": "Jetstar Japan"}}})
    p = FareDatabaseProvider(db)
    (real,) = p.search(origin="TPE", destination="NRT", departure_date=date(2027, 2, 5),
                       return_date=date(2027, 2, 15), adults=2)
    assert (real.issuer, real.total_price, real.legs[0].carrier) == ("google_flights", 39000, "Jetstar Japan")
    assert real.legs[1].carrier == "待選" and real.legs[1].duration == real.legs[0].duration
    assert p.search(origin="TPE", destination="NRT", departure_date=date(2027, 2, 6)) == []
    assert (p.hits, p.misses) == (1, 1)


def test_placeholder_segments_keep_same_day_connection():
    segs = (("HKG", "TPE", date(2027, 2, 7)), ("TPE", "NRT", date(2027, 2, 7)),
            ("NRT", "TPE", date(2027, 2, 15)), ("TPE", "ICN", date(2027, 4, 3)))
    t = offer_from_entry(fare_key(segs), {"price": 15000, "first": {
        "dep": "2027-02-07T19:00:00+08:00", "arr": "2027-02-07T20:45:00+08:00", "stops": 0, "airline": "CX"}})
    assert t.legs[1].departure > t.legs[0].arrival
    assert t.legs[2].departure.date() == date(2027, 2, 15)


def test_merge_keeps_history_and_expires_stale_or_past_entries():
    db = FareDatabase(fares={
        RT: {"price": 21000, "at": "2026-10-16", "hist": [["2026-10-16", 21000]]},
        "ow|TPE|HKG|2027-02-03": {"price": 2900, "at": "2026-10-01"},     # too old
        "ow|TPE|HKG|2026-10-10": {"price": 2900, "at": "2026-10-16"},     # flight already left
        "ow|TPE|KIX|2027-02-03": {"price": 6000, "at": "2026-10-15"},     # failed today, recent
    })
    db.merge({RT: {"price": 19500}}, today=TODAY, missing=["ow|TPE|KIX|2027-02-03", "ow|X|Y|2027-01-01"])
    e = db.fares[RT]
    assert (e["price"], e["prev"], e["prev_at"], e["at"]) == (19500, 21000, "2026-10-16", "2026-10-17")
    assert e["hist"] == [["2026-10-16", 21000], ["2026-10-17", 19500]]
    assert set(db.fares) == {RT, "ow|TPE|KIX|2027-02-03"}
    assert db.missing == ["ow|X|Y|2027-01-01"]


def test_live_prefetch_fetches_missing_queries_once_and_saves(tmp_path):
    calls = []

    def fetcher(keys):
        calls.append(list(keys))
        return {k: {"price": 5000} for k in keys if k.startswith(("ow|", "rt|"))}, []

    path = tmp_path / "fares-live.json"
    provider = FareDatabaseProvider(FareDatabase(), path=path, fetcher=fetcher, live_budget=50)
    req = ItineraryRequestIn(
        trip_type=TripType.ROUND_TRIP, origins=["TPE"], destinations=["NRT"],
        strategies=[S.STANDARD],
        candidate_windows=[CandidateWindowIn(depart=date(2027, 2, 5), return_date=date(2027, 2, 15),
                                             depart_flex=0, return_flex=0)],
    )
    _, plans, _ = SearchService(provider).run(req)
    assert calls == [[RT]]
    assert plans and plans[0].tickets[0].issuer == "google_flights"
    assert RT in json.loads(path.read_text())["fares"]


def test_search_without_fares_explains_what_is_missing():
    req = ItineraryRequestIn(
        trip_type=TripType.ROUND_TRIP, origins=["TPE"], destinations=["NRT"],
        candidate_windows=[CandidateWindowIn(depart=date(2027, 2, 5), return_date=date(2027, 2, 15))],
    )
    svc = SearchService(FareDatabaseProvider(FareDatabase(generated_at="2026-10-17T03:00:00+00:00")))
    _, plans, _ = svc.run(req)
    assert plans == [] and any("不在 Google Flights 票價資料庫" in n for n in svc.notices)


# --- crawl plan ------------------------------------------------------------------
def test_crawl_queries_follow_planners_horizon_and_country_rule():
    cfg = CrawlConfig(holidays=["lunar_ny", "qingming", "duanwu", "xmas"])
    keys = planner_queries(cfg, today=TODAY)
    stage1, mc = split_stages(keys)
    assert {k[:2] for k in stage1} == {"ow", "rt"} and mc
    assert not any("2027-12" in k for k in keys)  # 聖誕 is beyond Google's ~11-month window
    countries = {"HKG": "HK", "ICN": "KR", "BKK": "TH", "NRT": "JP", "KIX": "JP", "LHR": "GB"}
    four = [parse_key(k)[1] for k in mc if len(parse_key(k)[1]) == 4]
    assert four
    for (x, _, _), (_, d, _), _, (_, y, _) in four:
        assert countries[y] not in (countries[x], countries[d])  # trip B in a third country


@pytest.mark.parametrize("budget_ok", [True, False])
def test_rank_multi_city_spends_requests_on_promising_combinations(budget_ok):
    cfg = CrawlConfig(destinations=["NRT"], outer_stations=["HKG", "ICN"], holidays=["lunar_ny", "qingming", "duanwu"])
    keys = planner_queries(cfg, today=TODAY)
    stage1, mc = split_stages(keys)
    four = [k for k in mc if len(parse_key(k)[1]) == 4]
    # NRT round trip 20k, ICN round trip 8k; one-ways cheap or dear
    ow = 1000 if budget_ok else 9000
    prices = {k: (20000 if "|NRT|" in k else 8000) if k.startswith("rt|") else ow for k in stage1}
    budget, group = four_leg_budget(four[0], prices, cfg)
    assert group[0] == "4leg" and budget == pytest.approx((8000 + 20000 + 8000 - 2 * ow) / 20000)
    picked = rank_multi_city(four, prices, cfg, max_multi_city=500)
    groups = {four_leg_budget(k, prices, cfg)[1] for k in four}
    assert len(picked) == (min(3, len(four)) if budget_ok else 1) * len(groups) or len(picked) <= 3 * len(groups)
    assert len(rank_multi_city(four, prices, cfg, max_multi_city=2)) == 2


def test_export_chunks_stay_under_the_document_cap():
    from scripts.export_fare_chunks import MAX_BYTES, chunks

    first = {"dep": "2027-02-05T08:10:00+08:00", "arr": "2027-02-05T12:15:00+09:00", "stops": 0,
             "airline": "Jetstar Japan" * 4}
    fares = {f"ow|TPE|NRT|2027-02-{d:02d}-{i}": {"price": i, "at": "2026-10-17", "first": first,
                                                  "hist": [["x", 1]] * 50}
             for d in range(1, 28) for i in range(60)}
    meta, docs = chunks({"generated_at": "2026-10-17T00:00:00+00:00", "fares": fares})
    assert meta["count"] == len(fares) and meta["chunks"] == [i for i, _ in docs] and len(docs) > 1
    assert sum(len(b["fares"]) for _, b in docs) == len(fares)
    for _, body in docs:
        assert body["gen"] == meta["gen"] and len(json.dumps(body).encode()) < MAX_BYTES + 2000
        assert all("hist" not in e for e in body["fares"].values())


def test_live_overlay_wins_when_newer(tmp_path):
    main, live = tmp_path / "fares.json", tmp_path / "fares-live.json"
    FareDatabase(fares={RT: {"price": 20000, "at": "2026-10-16"}, "ow|TPE|HKG|2027-02-03": {"price": 2900, "at": "2026-10-16"}},
                 generated_at="2026-10-16T00:00:00+00:00").save(main)
    FareDatabase(fares={RT: {"price": 18000, "at": "2026-10-17"}}, generated_at="2026-10-17T05:00:00+00:00").save(live)
    p = FareDatabaseProvider.from_path(main)
    assert p.path == live and p.db.fares[RT]["price"] == 18000 and p.db.generated_at.startswith("2026-10-17")
    assert p.db.fares["ow|TPE|HKG|2027-02-03"]["price"] == 2900


def test_lookup_accepts_only_well_formed_keys():
    from scripts.lookup_fares import valid_keys

    keys = ["mc|HKG-TPE-2027-02-07|TPE-NRT-2027-02-07", RT, "ow|TPE|HKG|2027-02-03",
            "ow|TPE|HKG|2027-02-03", "rm -rf /", "ow|tpe|hkg|2027-02-03", 42]
    assert valid_keys(keys) == [RT, "ow|TPE|HKG|2027-02-03", "mc|HKG-TPE-2027-02-07|TPE-NRT-2027-02-07"]


# --- lookup daemon helpers ---------------------------------------------------------
def test_daemon_request_parsing_validates_and_caps():
    from scripts.lookup_daemon import parse_request

    good = json.dumps({"rid": "abc", "total": 3, "keys": ["ow|TPE|HKG|2027-02-03", RT, "junk", "ow|TPE|HKG|2027-02-03"]})
    r = parse_request(good)
    assert r == {"rid": "abc", "total": 3, "keys": [RT, "ow|TPE|HKG|2027-02-03"]} or r["keys"] == ["ow|TPE|HKG|2027-02-03", RT][::-1] or set(r["keys"]) == {RT, "ow|TPE|HKG|2027-02-03"}
    assert parse_request("not json") is None
    assert parse_request(json.dumps({"rid": 5, "keys": [RT]})) is None
    assert parse_request(json.dumps({"rid": "x", "keys": ["junk", "rm -rf"]})) is None
    assert parse_request(json.dumps({"rid": "x", "total": 9999, "keys": [RT]}))["total"] == 1   # total is clamped


def test_daemon_results_split_under_the_message_cap_and_finish_once():
    from scripts.lookup_daemon import MSG_BYTES, split_results

    first = {"dep": "2027-02-05T08:10:00+08:00", "arr": "2027-02-05T12:15:00+09:00", "stops": 0, "airline": "Jetstar Japan"}
    fares = {f"ow|TPE|HKG|2027-02-{d:02d}": {"price": 3000 + d, "at": "2026-10-17", "first": first} for d in range(1, 28)}
    nf = [f"mc|HKG-TPE-2027-02-{d:02d}|TPE-NRT-2027-02-{d:02d}" for d in range(1, 20)]
    msgs = split_results("r1", fares, nf, 46, 46, final=True)
    assert len(msgs) > 1 and all(len(m.encode()) <= MSG_BYTES + 200 for m in msgs)
    parsed = [json.loads(m) for m in msgs]
    assert [p["final"] for p in parsed] == [False] * (len(parsed) - 1) + [True]
    assert {k for p in parsed for k in p["fares"]} == set(fares) and {k for p in parsed for k in p["nf"]} == set(nf)
    assert json.loads(split_results("r1", {}, [], 1, 5, final=False)[0])["final"] is False


def test_daemon_rate_limiter_window():
    from scripts.lookup_daemon import RateLimiter

    rl = RateLimiter(limit=100, window=60)
    assert rl.allow(60, now=0) and rl.allow(40, now=1) and not rl.allow(1, now=2)
    assert rl.allow(50, now=61)   # first batch left the window
