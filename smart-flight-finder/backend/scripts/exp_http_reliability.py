"""EXPERIMENT part 3: how reliable is plain HTTP when only the real itinerary list is read?

Parts 1 and 2 showed: fast (0.3 s), not blocked, but (a) the cheapest price must be read from the itinerary list
(``data[2][0]`` best flights and ``data[3][0]`` other flights, price at ``item[1][0][1]``) — not from every price-like
pair in the page — and (b) some responses carry no flight data at all (only four small blocks). Measure, on a bigger
sample with up to three attempts per key: how often data arrives, and how often the cheapest price equals the browser's.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

import requests

from app.providers.google_flights import url_for
from scripts.exp_http_fetch import COOKIES, HEADERS, embedded_blocks


def itinerary_prices(blocks: list) -> list[int]:
    out: list[int] = []
    for b in blocks:
        if not (isinstance(b, list) and len(b) >= 4):
            continue
        for idx in (2, 3):
            try:
                for item in b[idx][0]:
                    price = item[1][0][1]
                    if isinstance(price, int) and price > 100:
                        out.append(price)
            except (TypeError, IndexError, KeyError):
                continue
    return out


def attempt(session, key: str) -> tuple[list[int], float, int, int]:
    t0 = time.time()
    r = session.get(url_for(key), headers=HEADERS, cookies=COOKIES, timeout=30)
    blocks = embedded_blocks(r.text)
    return itinerary_prices(blocks), time.time() - t0, len(blocks), r.status_code


def sample(db: dict, kind: str, n: int) -> list[tuple[str, int]]:
    ks = sorted(k for k, e in db["fares"].items() if k.startswith(kind + "|") and e.get("price"))
    step = max(1, len(ks) // n)
    return [(k, db["fares"][k]["price"]) for k in ks[::step][:n]]


def main() -> int:
    db = json.loads(
        Path(sys.argv[1] if len(sys.argv) > 1 else "../public/fares.json").read_text(
            encoding="utf-8"
        )
    )
    session = requests.Session()
    summary = {}
    for kind, n in (("ow", 12), ("rt", 12), ("mc", 10)):
        rows = []
        for key, db_price in sample(db, kind, n):
            tries, prices, secs = 0, [], 0.0
            for tries in range(1, 4):
                prices, s, _nblocks, _status = attempt(session, key)
                secs += s
                if prices:
                    break
                time.sleep(0.4)
            got = min(prices) if prices else None
            rows.append(
                {
                    "key": key,
                    "tries": tries,
                    "got": got,
                    "db": db_price,
                    "s": secs,
                    "n": len(prices),
                }
            )
            print(
                f"{key[:50]:50} tries={tries} items={len(prices):>3} http_min={got} db={db_price} {'MATCH' if got == db_price else ('lower' if got and got < db_price else '')} {secs:.2f}s",
                flush=True,
            )
        with_data = [r for r in rows if r["got"]]
        exact = [r for r in rows if r["got"] == r["db"]]
        first_try = [r for r in rows if r["got"] and r["tries"] == 1]
        summary[kind] = (
            len(rows),
            len(with_data),
            len(first_try),
            len(exact),
            statistics.median(r["s"] for r in rows),
        )
        print(
            f"  => {kind}: data {len(with_data)}/{len(rows)} (first try {len(first_try)}), exact price match {len(exact)}/{len(rows)}, median {summary[kind][4]:.2f}s per key\n",
            flush=True,
        )

    print("SUMMARY (kind: keys, with data, data on first try, exact match, median s)")
    for k, v in summary.items():
        print(" ", k, v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
