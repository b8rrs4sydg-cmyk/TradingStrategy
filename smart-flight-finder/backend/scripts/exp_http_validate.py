"""Check the production plain-HTTP reader (app.providers.google_http) against the fare database.

For a sample of ow / rt / mc keys: fetch them all in parallel with HttpFetcher, then compare the price with
the database (made by the browser) and the first-slice details, and report the speed.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

from app.providers.google_http import HttpFetcher


def sample(db: dict, n: int) -> list[str]:
    out: list[str] = []
    for kind in ("ow", "rt", "mc"):
        ks = sorted(
            k for k, e in db["fares"].items() if k.startswith(kind + "|") and e.get("price")
        )
        step = max(1, len(ks) // n)
        out += ks[::step][:n]
    return out


async def main() -> None:
    db = json.loads(Path(sys.argv[1]).read_text())
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    keys = sample(db, n)
    f = HttpFetcher()
    t = time.time()
    res = await asyncio.gather(*(f.fetch(k) for k in keys))
    took = time.time() - t
    stat: dict[str, list[int]] = {}
    for k, e in zip(keys, res, strict=True):
        kind, want = k.split("|")[0], db["fares"][k]
        s = stat.setdefault(
            kind, [0, 0, 0, 0, 0, 0]
        )  # keys, got, exact, within2%, first ok, first equal
        s[0] += 1
        if not e:
            print(f"MISS  {k[:70]}")
            continue
        s[1] += 1
        s[2] += e["price"] == want["price"]
        s[3] += abs(e["price"] - want["price"]) <= 0.02 * want["price"]
        wf, gf = want.get("first"), e.get("first")
        s[4] += bool(gf)
        same = bool(
            gf
            and wf
            and gf["dep"] == wf["dep"]
            and gf["arr"] == wf["arr"]
            and gf["stops"] == wf["stops"]
        )
        s[5] += same
        if e["price"] != want["price"] or (wf and not same):
            print(
                f"DIFF  {k[:60]} http={e['price']} db={want['price']}\n      http first={gf}\n      db   first={wf}"
            )
    print(f"\n{len(keys)} keys in parallel: {took:.1f}s total; stats {f.stats}")
    print("kind: keys, got, exact price, within 2%, first parsed, first equals db")
    for kind, s in stat.items():
        print(f"  {kind}: {s}")
    await f.aclose()


if __name__ == "__main__":
    asyncio.run(main())
