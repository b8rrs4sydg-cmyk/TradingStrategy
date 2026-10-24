"""EXPERIMENT (not used by the product): why does Google Flights give no price for some multi-city keys?

Each key is asked twice — plain HTTP (``HttpFetcher``, with its reason) and a real browser page whose visible text,
row count and result-list state are printed — next to control keys that are known to price. Run by ``exp-mc-missing.yml``.
"""

from __future__ import annotations

import asyncio
import sys
import time

from app.providers.google_flights import _ROW_LABELS, _UA, cheapest_entry, parse_key, url_for
from app.providers.google_http import HttpFetcher

KEYS = [
    ("MISSING 4-leg ICN start", "mc|ICN-TPE-2026-11-06|TPE-CDG-2026-12-29|CDG-TPE-2027-01-08|TPE-ICN-2027-01-16"),
    ("same, 3 legs (no leg 4)", "mc|ICN-TPE-2026-11-06|TPE-CDG-2026-12-29|CDG-TPE-2027-01-08"),
    ("same, TPE start (2 legs)", "mc|TPE-CDG-2026-12-29|CDG-TPE-2027-01-08"),
    ("later dates 4-leg", "mc|ICN-TPE-2027-02-16|TPE-CDG-2027-04-04|CDG-TPE-2027-04-12|TPE-ICN-2027-06-08"),
    ("CONTROL priced before (LHR)", "mc|ICN-TPE-2027-02-16|TPE-LHR-2027-04-04|LHR-TPE-2027-04-12|TPE-HKG-2027-06-08"),
    ("CONTROL ow", "ow|TPE|ICN|2027-01-16"),
]
BODY_JS = "() => document.body.innerText.slice(0, 1200)"


async def browser_probe(ctx, key: str) -> str:
    page = await ctx.new_page()
    t0 = time.time()
    try:
        await page.goto(url_for(key), wait_until="domcontentloaded", timeout=60000)
        try:
            await page.wait_for_selector(_ROW_LABELS, timeout=40000)
            found = "rows appeared"
        except Exception:  # noqa: BLE001
            found = "NO rows within 40 s"
        await page.wait_for_timeout(1500)
        labels = await page.eval_on_selector_all(_ROW_LABELS, "els => els.map(e => e.getAttribute('aria-label'))")
        entry = cheapest_entry(labels, parse_key(key)[1]) if labels else None
        body = (await page.evaluate(BODY_JS)).replace("\n", " | ")
        return f"{found} ({time.time() - t0:.0f}s) rows={len(labels)} entry={entry}\n      page: {body[:700]}"
    finally:
        await page.close()


async def main() -> None:
    from playwright.async_api import async_playwright

    http = HttpFetcher(attempts=3)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
        ctx = await browser.new_context(locale="en-US", user_agent=_UA)
        for label, key in KEYS:
            print(f"\n== {label}\n   {key}")
            e = await http.fetch(key)
            print(f"   HTTP    : {e and e.get('price')} airline={e and (e.get('first') or {}).get('airline')} why={http.why.get(key)}")
            print(f"   BROWSER : {await browser_probe(ctx, key)}")
            sys.stdout.flush()
        await browser.close()
    await http.aclose()


asyncio.run(main())
