"""Big fare-database fill, sharded across parallel GitHub jobs (``fares-fill.yml``).

The 6-hourly crawl (``build_fare_snapshot``) covers a handful of destinations.
This fills the database as widely as Google's ~11-month horizon allows:

    plan     every query the planners make for the wide config          → plan.json
    stage1   one-way / round-trip share ``i/N`` of plan.json            → part.json
    merge    stage-1 parts (+ live overlay) into the database           → merged.json
    stage2   multi-city: rank by the REAL stage-1 prices, take share i/N → part.json
    final    stage-2 parts into the database (the workflow then embeds + commits)

Keys fetched within ``--fresh-hours`` are skipped, so a re-run only fills gaps.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.providers.fare_db import FareDatabase, live_path
from app.providers.google_flights import GOOGLE_HORIZON_DAYS
from app.services.crawl_plan import (
    CrawlConfig,
    planner_queries,
    rank_multi_city,
    screen_four_leg,
    split_stages,
    with_leg_keys,
)
from scripts.build_fare_snapshot import crawl

WIDE = CrawlConfig(
    origins=["TPE"],
    destinations=["NRT", "HND", "KIX", "NGO", "FUK", "CTS", "OKA", "ICN", "PUS", "HKG", "MFM", "BKK", "CNX", "SGN", "HAN", "MNL", "CEB", "KUL", "SIN", "LHR", "CDG", "AMS", "LAX", "SFO", "SYD"],
    outer_stations=["HKG", "ICN", "BKK", "NRT", "KIX", "SGN", "SIN", "KUL"],
    holidays=["nyd", "lunar_ny", "peace228", "qingming", "labor", "duanwu"],
    flex=1,
)


def today_tpe():
    return datetime.now(ZoneInfo("Asia/Taipei")).date()


def split_csv(s: str) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip()]


def config(args) -> CrawlConfig:
    return CrawlConfig(
        origins=split_csv(args.origins),
        destinations=split_csv(args.destinations),
        outer_stations=split_csv(args.outer),
        holidays=split_csv(args.holidays),
        flex=args.flex,
    )


def shard_of(spec: str) -> tuple[int, int]:
    i, n = spec.split("/")
    return int(i), int(n)


def stale(keys: list[str], db: FareDatabase, fresh_hours: float) -> list[str]:
    """Keys the database does not hold a recent fare for."""

    cutoff = datetime.now(UTC).timestamp() - fresh_hours * 3600
    out = []
    for k in keys:
        e = db.fares.get(k)
        at = e.get("at") if e else None
        ts = datetime.fromisoformat(at).replace(tzinfo=UTC).timestamp() if at else 0
        if ts < cutoff:
            out.append(k)
    return out


def load_db(path: Path) -> FareDatabase:
    db = FareDatabase.load(path)
    db.overlay(FareDatabase.load(live_path(path)))   # fold in on-demand lookups
    return db


def write_part(path: Path, fares: dict, missing: list[str]) -> None:
    path.write_text(json.dumps({"fares": fares, "missing": missing}, ensure_ascii=False), encoding="utf-8")


def merge_parts(db: FareDatabase, parts: list[Path], cfg: CrawlConfig) -> int:
    fares: dict = {}
    missing: list[str] = []
    for p in parts:
        d = json.loads(p.read_text(encoding="utf-8"))
        fares |= d.get("fares", {})
        missing += d.get("missing", [])
    day = today_tpe()
    db.coverage = {**cfg.as_dict(), "horizon_days": GOOGLE_HORIZON_DAYS, "crawled_on": day.isoformat()}
    db.merge(fares, today=day, missing=[*db.missing, *missing])
    return len(fares)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_cfg(p) -> None:
        p.add_argument("--origins", default=",".join(WIDE.origins))
        p.add_argument("--destinations", default=",".join(WIDE.destinations))
        p.add_argument("--outer", default=",".join(WIDE.outer_stations))
        p.add_argument("--holidays", default=",".join(WIDE.holidays))
        p.add_argument("--flex", type=int, default=WIDE.flex)

    p = sub.add_parser("plan")
    add_cfg(p)
    p.add_argument("--out", type=Path, required=True)
    for name in ("stage1", "stage2"):
        p = sub.add_parser(name)
        add_cfg(p)
        p.add_argument("--plan", type=Path, required=True)
        p.add_argument("--db", type=Path, required=True)
        p.add_argument("--shard", default="0/1")
        p.add_argument("--out", type=Path, required=True)
        p.add_argument("--fresh-hours", type=float, default=20)
        p.add_argument("--concurrency", type=int, default=8)
        if name == "stage2":
            p.add_argument("--max-multi-city", type=int, default=6000)
    for name in ("merge", "final"):
        p = sub.add_parser(name)
        add_cfg(p)
        p.add_argument("--db", type=Path, required=True)
        p.add_argument("--out", type=Path, required=True)
        p.add_argument("parts", nargs="*", type=Path)
    args = ap.parse_args()
    cfg = config(args)

    if args.cmd == "plan":
        t0 = time.time()
        stage1, mc = split_stages(planner_queries(cfg, today=today_tpe()))
        stage1 = with_leg_keys(stage1, mc)  # one-way legs of the four-leg candidates: the floor that screens stage 2
        args.out.write_text(json.dumps({"stage1": stage1, "mc": mc}), encoding="utf-8")
        print(f"plan: {len(stage1)} one-way/round-trip + {len(mc)} multi-city candidates in {time.time() - t0:.0f}s")
        return

    if args.cmd in ("merge", "final"):
        db = load_db(args.db)
        n = merge_parts(db, args.parts, cfg)
        db.save(args.out)
        print(f"{args.cmd}: merged {n} fares from {len(args.parts)} parts → {len(db.fares)} in database → {args.out}")
        return

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    db = load_db(args.db)
    i, n = shard_of(args.shard)
    if args.cmd == "stage1":
        keys = stale(plan["stage1"], db, args.fresh_hours)[i::n]
        print(f"stage1 shard {i}/{n}: {len(keys)} of {len(plan['stage1'])} queries to fetch", flush=True)
        fares, missing = crawl(keys, f"s1-{i}", concurrency=args.concurrency, timeout_ms=25000)
    else:
        known = {k: e["price"] for k, e in db.fares.items()}
        mc_left, _ = screen_four_leg(plan["mc"], known, cfg, drop_unknown=True)
        ranked = rank_multi_city(mc_left, known, cfg, max_multi_city=args.max_multi_city)
        keys = stale(ranked, db, args.fresh_hours)[i::n]
        print(f"stage2 shard {i}/{n}: {len(keys)} of {len(ranked)} ranked multi-city queries "
              f"({len(plan['mc'])} candidates)", flush=True)
        fares, missing = crawl(keys, f"s2-{i}", concurrency=max(3, args.concurrency - 2), timeout_ms=40000)
    write_part(args.out, fares, missing)
    print(f"{args.cmd} shard {i}/{n}: {len(fares)} fetched, {len(missing)} missing")


if __name__ == "__main__":
    sys.exit(main())
