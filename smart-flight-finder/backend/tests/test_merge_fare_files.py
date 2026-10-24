"""Merging the fare files of two branches loses nothing and puts every key where the dispatcher sends it."""

from app.providers.fare_db import FareDatabase
from app.services.dispatch import owner
from scripts.merge_fare_files import merge_entries, shard, union

K1, K2, K3 = "ow|TPE|NRT|2027-04-01", "ow|TPE|KIX|2027-04-02", "rt|TPE|ICN|2027-04-03|2027-04-07"


def entry(price, at, hist=None):
    return {"price": price, "at": at, "hist": hist or [[at, price]]}


def test_the_newer_entry_wins_and_histories_are_joined():
    a = entry(5000, "2026-10-17")
    b = entry(4500, "2026-10-18")
    out = merge_entries(a, b)
    assert out["price"] == 4500 and out["at"] == "2026-10-18"
    assert out["hist"] == [["2026-10-17", 5000], ["2026-10-18", 4500]]
    assert (out["prev"], out["prev_at"]) == (5000, "2026-10-17")
    assert merge_entries(b, a) == out  # the order of the inputs does not matter


def test_union_keeps_every_key_and_a_priced_key_is_no_longer_missing():
    one = FareDatabase(
        fares={K1: entry(5000, "2026-10-17")}, missing=[K2, K3], generated_at="2026-10-17T00:00:00"
    )
    two = FareDatabase(
        fares={K2: entry(7000, "2026-10-18")}, missing=[K3], generated_at="2026-10-18T00:00:00"
    )
    out = union([one, two])
    assert set(out.fares) == {K1, K2} and out.missing == [K3]
    assert out.generated_at == "2026-10-18T00:00:00"


def test_shards_follow_the_dispatcher_and_hold_every_key_once():
    db = FareDatabase(
        fares={k: entry(1000 + i, "2026-10-18") for i, k in enumerate([K1, K2, K3])},
        missing=["ow|TPE|BKK|2027-05-01"],
    )
    parts = shard(db, 10)
    assert len(parts) == 10
    keys = [k for p in parts for k in p.fares]
    assert sorted(keys) == sorted(db.fares)
    for i, p in enumerate(parts):
        assert all(owner(k, range(10)) == i for k in [*p.fares, *p.missing])
