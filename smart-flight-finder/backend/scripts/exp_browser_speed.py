"""EXPERIMENT: how much faster is a browser lookup without images / fonts, and with a shorter settle wait?"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

from app.providers.google_flights import _ROW_LABELS, _fetch_one, cheapest_entry, parse_key, url_for

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


async def fetch_fast(ctx, key: str, timeout_ms: int):
    page = await ctx.new_page()
    try:
        await page.goto(url_for(key), wait_until="domcontentloaded", timeout=60000)
        try:
            await page.wait_for_selector(_ROW_LABELS, timeout=timeout_ms)
        except Exception:  # noqa: BLE001
            return None
        last, same = -1, 0
        for _ in range(
            10
        ):  # settle: stop when the number of rows has not grown for two polls (≤ 2.5 s)
            n = await page.eval_on_selector_all(_ROW_LABELS, "els => els.length")
            same = same + 1 if n == last else 0
            if same >= 2:
                break
            last = n
            await page.wait_for_timeout(250)
        labels = await page.eval_on_selector_all(
            _ROW_LABELS, "els => els.map(e => e.getAttribute('aria-label'))"
        )
        return cheapest_entry(labels, parse_key(key)[1])
    finally:
        await page.close()


async def run(mode: str, keys: list[str], db: dict) -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        b = await pw.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
        ctx = await b.new_context(locale="en-US", user_agent=UA)
        if mode != "baseline":
            await ctx.route(
                "**/*",
                lambda route: (
                    route.abort()
                    if route.request.resource_type in ("image", "media", "font")
                    else route.continue_()
                ),
            )
        sem = asyncio.Semaphore(6)

        async def one(k: str):
            async with sem:
                t = time.time()
                try:
                    e = await (
                        fetch_fast(ctx, k, 40000)
                        if mode == "block+fast"
                        else _fetch_one(ctx, k, 40000)
                    )
                except Exception:  # noqa: BLE001
                    e = None
                return k, e, time.time() - t

        t0 = time.time()
        res = await asyncio.gather(*(one(k) for k in keys))
        wall = time.time() - t0
        got = [(k, e) for k, e, _ in res if e]
        same = sum(
            abs(e["price"] - db["fares"][k]["price"]) <= 0.02 * db["fares"][k]["price"]
            for k, e in got
        )
        times = sorted(t for *_, t in res)
        print(
            f"{mode:11s}: wall {wall:5.1f}s for {len(keys)} keys, median {times[len(times) // 2]:.1f}s, "
            f"got {len(got)}, within 2% of database {same}"
        )
        await b.close()


async def main() -> None:
    db = json.loads(Path(sys.argv[1]).read_text())
    modes = sys.argv[2].split(",") if len(sys.argv) > 2 else ["baseline", "block", "block+fast"]
    ks = sorted(db["fares"])
    keys = []
    for kind in ("ow", "rt", "mc"):
        sub = [k for k in ks if k.startswith(kind + "|")]
        keys += sub[:: max(1, len(sub) // 6)][:6]
    for mode in modes:
        await run(mode, keys, db)


if __name__ == "__main__":
    asyncio.run(main())
