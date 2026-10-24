"""EXPERIMENT: does sending several identical multi-city requests at once (first readable answer wins) or leaving out
the streaming flag raise the share of keys the plain-HTTP reader gets?"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

from app.providers.google_http import HttpFetcher


async def main() -> None:
    db = json.loads(Path(sys.argv[1]).read_text())
    ks = sorted(k for k, e in db["fares"].items() if k.startswith("mc|") and e.get("price"))
    keys = ks[:: max(1, len(ks) // 24)][:24]
    for label, kw in (
        ("plain      ", {}),
        ("hedge x3   ", {"hedge": 3}),
        ("no rt=c    ", {"streamed": False}),
        ("hedge x3 + no rt=c", {"hedge": 3, "streamed": False}),
        ("plain      ", {}),
    ):
        f = HttpFetcher(timeout=8, attempts=2, concurrency=6, **kw)
        t = time.time()
        res = await asyncio.gather(*(f.fetch(k) for k in keys))
        ok = [(k, e) for k, e in zip(keys, res, strict=True) if e]
        close = sum(
            abs(e["price"] - db["fares"][k]["price"]) <= 0.02 * db["fares"][k]["price"]
            for k, e in ok
        )
        print(
            f"{label:18s}: {len(ok):2d}/{len(keys)} read, {close} within 2%, {time.time() - t:5.1f}s, {f.stats}"
        )
        await f.aclose()
        await asyncio.sleep(20)


if __name__ == "__main__":
    asyncio.run(main())
