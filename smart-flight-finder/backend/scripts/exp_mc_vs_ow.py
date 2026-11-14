"""EXPERIMENT: is a multi-city price about the sum of its one-way legs? (then one-way prices can screen multi-city keys)

For multi-city keys already in the database, price every leg as a one-way over plain HTTP (fast, reliable) and print
mc / sum(ow legs): if it never falls far below 1, the one-way sum is a usable lower bound for deciding which multi-city
keys are worth a browser lookup at all.
"""

from __future__ import annotations

import asyncio
import json
import statistics as st
import sys
from pathlib import Path

from app.providers.google_http import HttpFetcher


def legs(key: str) -> list[str]:
    return [
        "ow|" + "|".join(p.split("-", 2)[:2]) + "|" + p.split("-", 2)[2] for p in key.split("|")[1:]
    ]


async def main() -> None:
    db = json.loads(Path(sys.argv[1]).read_text())
    mc = sorted(k for k, e in db["fares"].items() if k.startswith("mc|") and e.get("price"))
    four = [k for k in mc if k.count("|") == 4][
        :: max(1, len([k for k in mc if k.count("|") == 4]) // 45)
    ][:45]
    two = [k for k in mc if k.count("|") == 2][
        :: max(1, len([k for k in mc if k.count("|") == 2]) // 25)
    ][:25]
    f = HttpFetcher(timeout=8, attempts=4, concurrency=8)
    ow_keys = sorted({o for k in four + two for o in legs(k)})
    print(
        f"{len(four)} four-leg + {len(two)} two-leg keys need {len(ow_keys)} distinct one-way prices"
    )
    res = dict(zip(ow_keys, await asyncio.gather(*(f.fetch(k) for k in ow_keys)), strict=True))
    print("one-way legs read:", sum(1 for v in res.values() if v), "/", len(ow_keys), f.stats)
    for name, keys in (("four-leg", four), ("two-leg", two)):
        ratios = []
        for k in keys:
            parts = [res.get(o) for o in legs(k)]
            if all(parts):
                ratios.append((db["fares"][k]["price"] / sum(p["price"] for p in parts), k))
        if not ratios:
            print(name, "no complete keys")
            continue
        rs = sorted(r for r, _ in ratios)
        print(
            f"{name}: {len(rs)} keys with all legs; mc/sum(ow): min {rs[0]:.2f} p10 {rs[len(rs) // 10]:.2f} "
            f"median {st.median(rs):.2f} p90 {rs[-1 - len(rs) // 10]:.2f} max {rs[-1]:.2f}"
        )
        for r, k in sorted(ratios)[:4]:
            print(f"   lowest {r:.2f}  {k[:90]}")
    await f.aclose()


if __name__ == "__main__":
    asyncio.run(main())
