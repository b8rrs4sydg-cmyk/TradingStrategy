"""Crawl real Google Flights fares into the fare database (fares.json).

Runs on GitHub Actions every 6 h (the dev sandbox has no open egress)::

    pip install -e . playwright && python -m playwright install --with-deps chromium
    python -m scripts.build_fare_snapshot --db ../public/fares.json

Stages (see ``app/services/crawl_plan.py``):

1. every one-way / round-trip query the planners make (fast pages);
2. multi-city queries ranked by the real stage-1 prices, capped by
   ``--max-multi-city`` (slow pages, so only the promising ones);
3. one slower retry pass for whatever timed out.

Results are merged into the existing database: price history and the
previous price are kept per query, and a query that failed this time keeps
its last price for up to 7 days.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.providers.fare_db import FareDatabase, live_path
from app.providers.google_flights import GOOGLE_HORIZON_DAYS, scrape
from app.services.crawl_plan import (
    CrawlConfig,
    planner_queries,
    rank_multi_city,
    screen_four_leg,
    split_stages,
    with_leg_keys,
)


def _progress(label: str):
    def report(done: int, total: int, missing: int) -> None:
        if done % 25 == 0 or done == total:
            print(f"[{label}] {done}/{total} fetched, {missing} missing", flush=True)

    return report


def crawl(keys: list[str], label: str, *, concurrency: int, timeout_ms: int) -> tuple[dict, list[str]]:
    if not keys:
        return {}, []
    fares, missing = asyncio.run(
        scrape(keys, concurrency=concurrency, timeout_ms=timeout_ms, progress=_progress(label))
    )
    if missing:  # slow pages under load — one gentler pass
        more, missing = asyncio.run(
            scrape(missing, concurrency=2, timeout_ms=60000, progress=_progress(f"{label} retry"))
        )
        fares |= more
    return fares, missing


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", "--out", dest="db", type=Path, required=True)
    defaults = CrawlConfig()
    ap.add_argument("--origins", default=",".join(defaults.origins))
    ap.add_argument("--destinations", default=",".join(defaults.destinations))
    ap.add_argument("--outer", default=",".join(defaults.outer_stations))
    ap.add_argument("--holidays", default=",".join(defaults.holidays))
    ap.add_argument("--flex", type=int, default=defaults.flex)
    ap.add_argument("--max-multi-city", type=int, default=260)
    ap.add_argument("--concurrency", type=int, default=5)
    ap.add_argument("--dry-run", action="store_true", help="print the crawl plan and exit")
    args = ap.parse_args()

    def split(s: str) -> list[str]:
        return [x.strip().upper() for x in s.split(",") if x.strip()]

    cfg = CrawlConfig(
        origins=split(args.origins),
        destinations=split(args.destinations),
        outer_stations=split(args.outer),
        holidays=[x.strip() for x in args.holidays.split(",") if x.strip()],
        flex=args.flex,
    )
    today = datetime.now(ZoneInfo("Asia/Taipei")).date()
    db = FareDatabase.load(args.db)
    db.overlay(FareDatabase.load(live_path(args.db)))  # fold in on-demand lookups
    stage1, mc = split_stages(planner_queries(cfg, today=today))
    stage1 = with_leg_keys(stage1, mc)  # one-way legs of every four-leg candidate: the floor that screens stage 2
    print(f"plan: {len(stage1)} one-way/round-trip + {len(mc)} multi-city candidates", flush=True)
    if args.dry_run:
        print("\n".join(stage1 + mc))
        return

    t0 = time.time()
    fares1, missing1 = crawl(stage1, "stage1", concurrency=args.concurrency, timeout_ms=25000)
    if stage1 and len(fares1) < len(stage1) * 0.3:
        sys.exit(f"only {len(fares1)}/{len(stage1)} fares — Google may be blocking; keeping the old database")

    known = {k: e["price"] for k, e in db.fares.items()} | {k: e["price"] for k, e in fares1.items()}
    mc_left, pruned = screen_four_leg(mc, known, cfg, drop_unknown=True)
    picked = rank_multi_city(mc_left, known, cfg, max_multi_city=args.max_multi_city)
    print(
        f"stage2: {len(picked)} of {len(mc)} multi-city queries worth fetching "
        f"({pruned} four-leg combinations cannot beat round trips by their one-way floor)",
        flush=True,
    )
    fares2, missing2 = crawl(picked, "stage2", concurrency=max(2, args.concurrency - 2), timeout_ms=40000)

    db.coverage = {**cfg.as_dict(), "horizon_days": GOOGLE_HORIZON_DAYS, "crawled_on": today.isoformat()}
    db.merge(fares1 | fares2, today=today, missing=missing1 + missing2)
    db.save(args.db)
    print(
        f"done in {time.time() - t0:.0f}s: {len(fares1) + len(fares2)} fetched, "
        f"{len(db.fares)} in database, {len(db.missing)} missing → {args.db}"
    )


if __name__ == "__main__":
    main()
