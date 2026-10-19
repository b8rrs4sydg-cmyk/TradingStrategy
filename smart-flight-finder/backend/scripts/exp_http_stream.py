"""EXPERIMENT: is a missing result just a slow, streamed answer cut off by a short timeout?

For keys the plain-HTTP reader misses (mostly multi-city, long haul), post with a long timeout, stream the answer and
print when each chunk arrives, what the answer holds, and the text of an answer that holds nothing.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

from app.providers.google_flights import parse_key
from app.providers.google_http import ENDPOINT, HttpFetcher, entry_from, rpc_payloads, search_body


async def probe(f: HttpFetcher, key: str, want: int | None, rep: int) -> str:
    segs = parse_key(key)[1]
    await f._prepare()
    f.reqid += 100000
    params = {
        "f.sid": f.sid,
        "bl": f.bl,
        "hl": "en",
        "gl": "TW",
        "soc-app": "162",
        "soc-platform": "1",
        "soc-device": "1",
        "_reqid": str(f.reqid),
        "rt": "c",
    }
    t = time.time()
    chunks: list[str] = []
    marks: list[tuple[float, int]] = []
    try:
        async with f.client.stream(
            "POST",
            ENDPOINT,
            params=params,
            content=search_body(key.split("|", 1)[0], segs),
            headers={
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                "X-Same-Domain": "1",
            },
            timeout=httpx.Timeout(60.0),
        ) as r:
            async for c in r.aiter_text():
                chunks.append(c)
                marks.append((round(time.time() - t, 1), len(c)))
    except httpx.HTTPError as e:
        return f"{key[:50]} #{rep}: {type(e).__name__} after {time.time() - t:.1f}s, chunks so far {marks[:6]}"
    text = "".join(chunks)
    entry = entry_from(rpc_payloads(text), segs)
    out = (
        f"{key[:50]} #{rep}: {time.time() - t:.1f}s total, {len(text)} bytes, chunks {marks[:8]}, "
        f"price {entry and entry['price']} (db {want})"
    )
    if not entry:
        out += f"\n      EMPTY ANSWER: {text[:300]!r}"
    return out


async def main() -> None:
    db = json.loads(Path(sys.argv[1]).read_text())
    ks = sorted(db["fares"])
    lhr = [k for k in ks if k.startswith("mc|") and "TPE-LHR" in k][::97][:4]
    other = [k for k in ks if k.startswith("mc|") and "TPE-LHR" not in k][::401][:4]
    rts = [k for k in ks if k.startswith("rt|TPE|KIX|")][::7][:2] + [
        k for k in ks if k.startswith("rt|TPE|LHR|")
    ][:1]
    f = HttpFetcher()
    for rep in (1, 2):
        res = await asyncio.gather(
            *(probe(f, k, db["fares"][k].get("price"), rep) for k in lhr + other + rts)
        )
        print("\n".join(res))
        print()
    await f.aclose()


if __name__ == "__main__":
    asyncio.run(main())
