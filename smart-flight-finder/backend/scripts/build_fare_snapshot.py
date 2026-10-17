"""Fetch real Google Flights fares for the planners' queries → fares.json.

Runs on GitHub Actions (the dev sandbox has no open egress)::

    pip install playwright && playwright install --with-deps chromium
    python -m scripts.build_fare_snapshot --out ../public/fares.json

Each query is the Google Flights search ``booking_links`` already builds
(``tfs`` protobuf); the cheapest total on the results page is recorded with
its first-segment times. Queries that fail or show no result are listed
under ``missing`` and fall back to 示意價 in the planners.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from app.data.airports import TIMEZONES
from app.models.enums import CabinClass
from app.providers.snapshot import parse_key
from app.services.booking_links import google_flights_tfs
from app.services.fare_snapshot import SnapshotConfig, cheapest_entry, collect_queries

_TRIP = {"ow": 2, "rt": 1, "mc": 3}
_ROW_LABELS = "li div[aria-label*='New Taiwan dollars']"


def tz_of(code: str) -> ZoneInfo:
    return ZoneInfo(TIMEZONES.get(code, "UTC"))


def url_for(key: str) -> str:
    kind, segs = parse_key(key)
    tfs = google_flights_tfs(segs, adults=1, cabin=CabinClass.ECONOMY, trip=_TRIP[kind])
    return f"https://www.google.com/travel/flights?tfs={quote(tfs, safe='')}&hl=en&gl=TW&curr=TWD"


async def fetch(ctx, key: str, timeout_ms: int) -> dict | None:
    page = await ctx.new_page()
    try:
        await page.goto(url_for(key), wait_until="domcontentloaded", timeout=60000)
        try:
            await page.wait_for_selector(_ROW_LABELS, timeout=timeout_ms)
        except Exception:  # noqa: BLE001 — no results / blocked → missing
            return None
        await page.wait_for_timeout(1500)  # let the "other flights" list render too
        labels = await page.eval_on_selector_all(
            _ROW_LABELS, "els => els.map(e => e.getAttribute('aria-label'))"
        )
        return cheapest_entry(labels, parse_key(key)[1], tz_of)
    finally:
        await page.close()


async def scrape(keys: list[str], *, concurrency: int, timeout_ms: int) -> tuple[dict, list[str]]:
    from playwright.async_api import async_playwright

    fares: dict[str, dict] = {}
    missing: list[str] = []
    sem = asyncio.Semaphore(concurrency)
    done = 0
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
        ctx = await browser.new_context(
            locale="en-US",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
            ),
        )

        async def one(key: str) -> None:
            nonlocal done
            async with sem:
                await asyncio.sleep(random.uniform(0.3, 1.2))  # be gentle
                entry = None
                for _ in range(2):
                    try:
                        entry = await fetch(ctx, key, timeout_ms)
                        break
                    except Exception as e:  # noqa: BLE001
                        print(f"retry {key}: {e}", file=sys.stderr)
                (fares.__setitem__(key, entry) if entry else missing.append(key))
                done += 1
                if done % 20 == 0:
                    print(f"{done}/{len(keys)} fetched, {len(missing)} missing", flush=True)

        await asyncio.gather(*(one(k) for k in keys))
        await browser.close()
    return fares, missing


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--origins", default="TPE")
    ap.add_argument("--destinations", default="NRT,KIX,LHR")
    ap.add_argument("--outer", default="HKG")
    ap.add_argument("--holidays", default="lunar_ny,qingming")
    ap.add_argument("--flex", type=int, default=1)
    ap.add_argument("--outer-stay", type=int, default=2)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--timeout-ms", type=int, default=35000)
    ap.add_argument("--limit", type=int, default=0, help="only the first N queries (debug)")
    ap.add_argument("--dry-run", action="store_true", help="print the query list and exit")
    args = ap.parse_args()

    split = lambda s: [x.strip().upper() for x in s.split(",") if x.strip()]
    cfg = SnapshotConfig(
        origins=split(args.origins),
        destinations=split(args.destinations),
        outer_stations=split(args.outer),
        holidays=[x.strip() for x in args.holidays.split(",") if x.strip()],
        flex=args.flex,
        outer_stay_days=args.outer_stay,
    )
    keys = collect_queries(cfg, today=datetime.now(ZoneInfo("Asia/Taipei")).date())
    if args.limit:
        keys = keys[: args.limit]
    print(f"{len(keys)} queries", flush=True)
    if args.dry_run:
        print("\n".join(keys))
        return

    t0 = time.time()
    fares, missing = asyncio.run(
        scrape(keys, concurrency=args.concurrency, timeout_ms=args.timeout_ms)
    )
    snapshot = {
        "source": "google_flights",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "currency": "TWD",
        "adults": 1,
        "config": {
            "origins": cfg.origins,
            "destinations": cfg.destinations,
            "outer_stations": cfg.outer_stations,
            "holidays": cfg.holidays,
            "flex": cfg.flex,
            "outer_stay_days": cfg.outer_stay_days,
        },
        "fares": dict(sorted(fares.items())),
        "missing": sorted(missing),
    }
    if keys and len(fares) < len(keys) * 0.3:
        sys.exit(f"only {len(fares)}/{len(keys)} fares — Google may be blocking; keeping the old snapshot")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"done in {time.time() - t0:.0f}s: {len(fares)} fares, {len(missing)} missing → {args.out}")


if __name__ == "__main__":
    main()
