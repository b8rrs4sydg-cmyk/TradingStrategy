"""Fold several fare databases into one and hand every key to the crawler instance that owns it.

Used when two branches both collected fares (each branch has its own ``fares.json`` snapshot and ``fares-live[-i].json``
overlays): the union keeps, per key, the entry fetched most recently and the union of both price histories. The live
overlay is then written back as ``fares-live.json`` (instance 0) and ``fares-live-<i>.json`` so that each key sits in the
file of the instance the dispatcher (``app.services.dispatch.owner``) sends it to.

    python -m scripts.merge_fare_files --public ../public --other <dir with the other branch's files> --instances 10
"""

from __future__ import annotations

import argparse
import glob
from datetime import UTC, datetime
from pathlib import Path

from app.providers.atomic_io import file_lock
from app.providers.fare_db import HISTORY_POINTS, FareDatabase
from app.services.dispatch import owner


def merge_entries(a: dict, b: dict) -> dict:
    """The more recently fetched of two entries for one key, with both price histories folded in."""

    new, old = (a, b) if (a.get("at") or "") >= (b.get("at") or "") else (b, a)
    hist: dict[str, int] = {}
    for h in (*old.get("hist", []), *new.get("hist", [])):
        hist[h[0]] = h[1]
    out = dict(new)
    if hist:
        points = sorted(hist.items())[-HISTORY_POINTS:]
        out["hist"] = [[d, p] for d, p in points]
        if len(points) >= 2:
            out["prev"], out["prev_at"] = points[-2][1], points[-2][0]
    return out


def union(dbs: list[FareDatabase]) -> FareDatabase:
    out = FareDatabase()
    for db in dbs:
        for key, entry in db.fares.items():
            out.fares[key] = merge_entries(out.fares[key], entry) if key in out.fares else entry
        out.missing += db.missing
        if db.generated_at and (out.generated_at or "") < db.generated_at:
            out.generated_at = db.generated_at
            out.coverage = db.coverage or out.coverage
    out.missing = sorted(set(out.missing) - set(out.fares))
    return out


def shard(db: FareDatabase, instances: int) -> list[FareDatabase]:
    """One database per instance, each key (priced or missing) in the file of the instance that owns it."""

    ids = list(range(instances))
    parts = [FareDatabase(generated_at=db.generated_at, coverage=db.coverage) for _ in ids]
    for key, entry in db.fares.items():
        parts[owner(key, ids)].fares[key] = entry
    for key in db.missing:
        parts[owner(key, ids)].missing.append(key)
    return parts


def load_all(directory: Path, pattern: str) -> list[FareDatabase]:
    return [FareDatabase.load(p) for p in sorted(glob.glob(str(directory / pattern)))]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--public", type=Path, required=True, help="the public/ directory to write")
    ap.add_argument(
        "--other", type=Path, required=True, help="directory holding the other branch's files"
    )
    ap.add_argument("--instances", type=int, default=10)
    args = ap.parse_args()

    live = union(
        [*load_all(args.public, "fares-live*.json"), *load_all(args.other, "fares-live*.json")]
    )
    snapshot = union(
        [
            FareDatabase.load(args.public / "fares.json"),
            FareDatabase.load(args.other / "fares.json"),
        ]
    )
    live.generated_at = datetime.now(UTC).isoformat(timespec="seconds")
    for i, part in enumerate(shard(live, args.instances)):
        path = args.public / ("fares-live.json" if i == 0 else f"fares-live-{i}.json")
        with file_lock(path):
            part.save(path)
    with file_lock(args.public / "fares.json"):
        snapshot.save(args.public / "fares.json")
    print(
        f"live overlay: {len(live.fares)} fares over {args.instances} files; snapshot: {len(snapshot.fares)} fares"
    )


if __name__ == "__main__":
    main()
