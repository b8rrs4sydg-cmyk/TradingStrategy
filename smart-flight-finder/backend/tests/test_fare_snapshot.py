from datetime import date
from zoneinfo import ZoneInfo

from app.providers.snapshot import SnapshotFareProvider, fare_key, parse_key
from app.services.fare_snapshot import (
    SnapshotConfig,
    cheapest_entry,
    collect_queries,
    parse_option,
)

TPE, TYO = ZoneInfo("Asia/Taipei"), ZoneInfo("Asia/Tokyo")
LABEL = (
    "From 22080 New Taiwan dollars round trip total. Nonstop flight with Jetstar Japan. "
    "Leaves Taiwan Taoyuan International Airport at 12:50 PM on Friday, February 5 and "
    "arrives at Narita International Airport at 4:55 PM on Friday, February 5. "
    "Total duration 3 hr 5 min. Select flight"
)


def test_keys_round_trip():
    segs = (("HKG", "TPE", date(2027, 2, 7)), ("TPE", "NRT", date(2027, 2, 7)))
    for key, kind in [
        (fare_key(segs), "mc"),
        (fare_key(segs[:1]), "ow"),
        (fare_key((("TPE", "NRT", date(2027, 2, 5)), ("NRT", "TPE", date(2027, 2, 15))), round_trip=True), "rt"),
    ]:
        k, parsed = parse_key(key)
        assert k == kind and fare_key(parsed, round_trip=k == "rt") == key


def test_parse_google_result_label():
    p = parse_option(LABEL, year=2027, dep_tz=TPE, arr_tz=TYO)
    assert (p.price, p.stops, p.airline) == (22080, 0, "Jetstar Japan")
    assert p.dep.isoformat() == "2027-02-05T12:50:00+08:00"
    assert p.arr.isoformat() == "2027-02-05T16:55:00+09:00"
    one_stop = LABEL.replace("Nonstop flight with Jetstar Japan", "1 stop flight with EVA Air")
    assert parse_option(one_stop, year=2027, dep_tz=TPE, arr_tz=TYO).stops == 1
    assert parse_option("Select flight", year=2027, dep_tz=TPE, arr_tz=TYO) is None


def test_cheapest_entry_keeps_lowest_total_and_its_first_segment():
    cheaper = LABEL.replace("22080", "19,500").replace("12:50", "8:10")
    segs = (("TPE", "NRT", date(2027, 2, 5)), ("NRT", "TPE", date(2027, 2, 15)))
    e = cheapest_entry([LABEL, cheaper], segs, lambda c: TPE if c == "TPE" else TYO)
    assert e["price"] == 19500 and e["first"]["dep"].startswith("2027-02-05T20:10")


def test_snapshot_provider_uses_real_fare_and_falls_back_to_stub():
    key = fare_key((("TPE", "NRT", date(2027, 2, 5)), ("NRT", "TPE", date(2027, 2, 15))), round_trip=True)
    snap = {"fares": {key: {"price": 19500, "first": {
        "dep": "2027-02-05T08:10:00+08:00", "arr": "2027-02-05T12:15:00+09:00",
        "stops": 0, "airline": "Jetstar Japan"}}}}
    p = SnapshotFareProvider(snap)
    (real,) = p.search(origin="TPE", destination="NRT", departure_date=date(2027, 2, 5),
                       return_date=date(2027, 2, 15), adults=2)
    assert (real.issuer, real.total_price, real.legs[0].carrier) == ("google_flights", 39000, "Jetstar Japan")
    assert len(real.legs) == 2
    (stub,) = p.search(origin="TPE", destination="NRT", departure_date=date(2027, 2, 6))
    assert stub.issuer == "stub" and (p.hits, p.misses) == (1, 1)


def test_snapshot_keeps_same_day_connection_after_real_first_flight():
    segs = (("HKG", "TPE", date(2027, 2, 7)), ("TPE", "NRT", date(2027, 2, 7)),
            ("NRT", "TPE", date(2027, 2, 15)), ("TPE", "HKG", date(2027, 4, 3)))
    snap = {"fares": {fare_key(segs): {"price": 15000, "first": {
        "dep": "2027-02-07T19:00:00+08:00", "arr": "2027-02-07T20:45:00+08:00", "stops": 0, "airline": "CX"}}}}
    (t,) = SnapshotFareProvider(snap).search_multi_city(segments=segs)
    assert t.legs[1].departure > t.legs[0].arrival
    assert t.legs[2].departure.date() == date(2027, 2, 15)


def test_query_list_follows_planners_and_google_horizon():
    keys = collect_queries(SnapshotConfig(holidays=["lunar_ny", "qingming", "xmas"]), today=date(2026, 10, 17))
    kinds = {k.split("|")[0] for k in keys}
    assert kinds == {"ow", "rt", "mc"}
    assert not any("2027-12" in k for k in keys)  # 聖誕 is beyond Google's ~11-month window
    assert any(k.startswith("mc|HKG-TPE-") for k in keys)  # 四腿票
    assert any(k.startswith("rt|TPE|NRT|2027-02") for k in keys)


def test_resolver_uses_snapshot_from_env(tmp_path, monkeypatch):
    import json

    from app.services.search import resolve_default_provider

    path = tmp_path / "fares.json"
    path.write_text(json.dumps({"fares": {}, "generated_at": "2026-10-17T00:00:00+00:00"}))
    monkeypatch.setenv("FARE_SNAPSHOT_PATH", str(path))
    monkeypatch.delenv("REDIS_URL", raising=False)
    assert isinstance(resolve_default_provider(), SnapshotFareProvider)
    monkeypatch.setenv("FARE_SNAPSHOT_PATH", str(tmp_path / "missing.json"))
    assert not isinstance(resolve_default_provider(), SnapshotFareProvider)


def test_embed_snapshot_into_demo_page():
    from pathlib import Path

    from scripts.embed_fare_snapshot import embed

    html = Path(__file__).resolve().parents[2].joinpath("public/index.html").read_text(encoding="utf-8")
    out = embed({"fares": {"ow|TPE|HKG|2027-02-03": {"price": 2850}}, "note": "</script>"}, html)
    assert '"price":2850' in out and "<\\/script>" in out
    assert embed({"fares": {}}, out).count('id="fare-snapshot"') == 1  # re-embedding replaces
