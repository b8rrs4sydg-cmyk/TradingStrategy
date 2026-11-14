"""The fare database under concurrent writers: no torn files, no lost updates, no duplicate crawling."""

import asyncio
import json
import multiprocessing as mp
import threading
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from app.providers import atomic_io
from app.providers.atomic_io import atomic_write_text
from app.providers.fare_db import FareDatabase
from scripts.lookup_daemon import Daemon, Persister

DAY = (datetime.now(UTC).date().replace(year=datetime.now(UTC).year + 1)).isoformat()


def fare_key(n: int) -> str:
    # distinct valid one-way keys: vary the destination and the day
    dest = ["NRT", "KIX", "ICN", "BKK", "SIN", "HKG", "FUK", "CTS", "OKA", "MNL"][n % 10]
    year = date.fromisoformat(DAY).year
    return f"ow|TPE|{dest}|{year}-{(n // 280) % 12 + 1:02d}-{(n // 10) % 28 + 1:02d}"


def entry(price: int) -> dict:
    return {"price": price, "first": {"dep": "x", "arr": "y", "stops": 0, "airline": "A"}}


def test_atomic_write_leaves_old_file_when_the_write_fails(tmp_path, monkeypatch):
    p = tmp_path / "f.json"
    p.write_text("old")

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(atomic_io.os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write_text(p, "new")
    assert p.read_text() == "old"
    assert [f.name for f in tmp_path.iterdir()] == ["f.json"]  # the temp file is cleaned up


def test_readers_never_see_a_torn_file(tmp_path):
    p = tmp_path / "f.json"
    atomic_write_text(p, json.dumps({"n": 0}))
    stop, bad = threading.Event(), []

    def reader():
        while not stop.is_set():
            try:
                json.loads(p.read_text())
            except ValueError as e:
                bad.append(e)

    t = threading.Thread(target=reader)
    t.start()
    for n in range(300):
        atomic_write_text(p, json.dumps({"n": n, "pad": "x" * 20000}))
    stop.set()
    t.join()
    assert not bad


def _writer(args):
    path, lo, hi = args
    for n in range(lo, hi):
        FareDatabase.merge_into_file(
            path, {fare_key(n): entry(10000 + n)}, today=datetime.now(UTC).date()
        )


def test_processes_writing_the_same_file_lose_nothing(tmp_path):
    path = tmp_path / "fares-live.json"
    with mp.get_context("spawn").Pool(4) as pool:
        pool.map(_writer, [(str(path), i * 15, i * 15 + 15) for i in range(4)])
    assert len(FareDatabase.load(path).fares) == 60


def test_persister_flushes_from_many_threads_without_loss(tmp_path):
    persist = Persister(tmp_path / "fares-live.json")
    errors = []

    def work(base):
        try:
            for n in range(base, base + 20):
                persist.add({fare_key(n): entry(10000 + n)}, [])
                persist.flush(push=False)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=work, args=(b * 20,)) for b in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    persist.flush(push=False)
    assert not errors
    assert len(FareDatabase.load(persist.path).fares) == 120
    assert not persist.pending


def test_a_key_asked_twice_at_once_is_fetched_once():
    d = Daemon.__new__(Daemon)
    d.cache, d.inflight, calls = {}, {}, []

    async def price(k, ctx, sem, seq):
        calls.append(k)
        await asyncio.sleep(0.05)
        return entry(12345), False

    d.price = price

    async def go():
        return await asyncio.gather(
            *(d.priced("ow|TPE|NRT|2027-04-01", None, None, 1) for _ in range(8))
        )

    out = asyncio.run(go())
    assert len(calls) == 1 and all(o == (entry(12345), False) for o in out)
    assert d.inflight == {}
    assert asyncio.run(d.priced("ow|TPE|NRT|2027-04-01", None, None, 1)) == (
        entry(12345),
        False,
    )  # now cached
    assert len(calls) == 1


def test_a_crashed_lookup_is_shared_but_not_cached():
    d = Daemon.__new__(Daemon)
    d.cache, d.inflight, calls = {}, {}, []

    async def price(k, ctx, sem, seq):
        calls.append(k)
        await asyncio.sleep(0.02)
        return None, True

    d.price = price

    async def go():
        return await asyncio.gather(
            *(d.priced("ow|TPE|NRT|2027-04-01", None, None, 1) for _ in range(3))
        )

    assert asyncio.run(go()) == [(None, True)] * 3
    assert d.cache == {} and len(calls) == 1


def test_page_instances_match_the_workflow_matrix():
    root = Path(__file__).resolve().parents[3]
    wf = (root / ".github/workflows/fare-daemon.yml").read_text(encoding="utf-8")
    matrix = json.loads(
        next(l for l in wf.splitlines() if "instance:" in l).split("instance:")[1].strip()
    )
    page = (root / "smart-flight-finder/public/index.html").read_text(encoding="utf-8")
    n = int(
        next(l for l in page.splitlines() if l.startswith("const INSTANCES ="))
        .split("=")[1]
        .split(";")[0]
    )
    assert matrix == list(range(n))
