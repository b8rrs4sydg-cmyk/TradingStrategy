"""EXPERIMENT: how many plain-HTTP requests at once does Google tolerate from one IP?

Runs the same kind of sample (10 one-way, 10 round-trip, 10 multi-city keys) at concurrency 3, 6 and 10, with a pause
between rounds so one round's throttling does not spill into the next, and reports per round what came back.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

from app.providers.google_http import HttpFetcher


def sample(db: dict, n: int, offset: int) -> list[str]:
    out: list[str] = []
    for kind in ("ow", "rt", "mc"):
        ks = sorted(
            k for k, e in db["fares"].items() if k.startswith(kind + "|") and e.get("price")
        )
        step = max(1, len(ks) // n)
        out += ks[offset::step][:n]
    return out


async def main() -> None:
    db = json.loads(Path(sys.argv[1]).read_text())
    for i, conc in enumerate((3, 6, 10)):
        keys = sample(db, 10, 3 + i * 7)
        f = HttpFetcher(concurrency=conc)
        t = time.time()
        res = await asyncio.gather(*(f.fetch(k) for k in keys))
        took = time.time() - t
        kinds: dict[str, list[int]] = {}
        for k, e in zip(keys, res, strict=True):
            s = kinds.setdefault(k.split("|")[0], [0, 0, 0])
            s[0] += 1
            if e:
                s[1] += 1
                s[2] += abs(e["price"] - db["fares"][k]["price"]) <= 0.02 * db["fares"][k]["price"]
        print(
            f"concurrency {conc:2d}: {took:5.1f}s for {len(keys)} keys; stats {f.stats}; "
            f"per kind (keys, got, within 2%) {kinds}"
        )
        await f.aclose()
        await asyncio.sleep(45)


if __name__ == "__main__":
    asyncio.run(main())
