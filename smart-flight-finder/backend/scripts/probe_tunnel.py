"""Fast probe: the deployed page talks to the crawler through its direct tunnel.

Loads the published page in a real browser (so CORS / mixed content are real),
then runs the page's own ``ntfyLookup`` over the direct transport for a few keys
and prints a timeline. Takes about a minute — the full e2e needs a quarter of an hour.
"""

from __future__ import annotations

import asyncio
import sys
import time

from playwright.async_api import async_playwright

JS = """
async (keys) => {
  const t0 = performance.now();
  const out = { steps: [] };
  const mark = s => out.steps.push(`${((performance.now() - t0) / 1000).toFixed(1)}s ${s}`);
  const url = await discoverDaemon(true);
  mark(`discovered ${url} notes=${JSON.stringify(live.daemonNotes)}`);
  if (!url) return out;
  live.transport = 'http';
  const rid = 'probe' + Date.now().toString(36);
  live.rid = rid; live.keys = keys; live.doc = { status: 'queued', total: keys.length, done: 0, found: 0 };
  const seen = [];
  const timer = setInterval(() => seen.push(`${((performance.now() - t0) / 1000).toFixed(0)}s ${live.doc.status} ${live.doc.done}/${live.doc.total} found=${live.doc.found}`), 3000);
  try { await ntfyLookup(keys, rid); mark('lookup resolved'); } catch (e) { mark('lookup failed: ' + e.message); }
  clearInterval(timer);
  out.progress = seen.slice(-12);
  out.transport = live.transport;
  return out;
}
"""


async def main(url: str) -> int:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        await page.goto(url, wait_until="load")
        await page.wait_for_function(
            "typeof ntfyLookup === 'function' && typeof FARES === 'object'", timeout=60000
        )
        keys = await page.evaluate(
            "Object.keys(FARES.fares).filter(k => k.startsWith('ow|')).slice(0, 3)"
        )
        print("keys:", keys, flush=True)
        has_poll = await page.evaluate("ntfyLookup.toString().includes('/poll/')")
        print("page uses long polling:", has_poll, flush=True)
        t0 = time.time()
        res = await asyncio.wait_for(page.evaluate(JS, keys), timeout=150)
        for s in res["steps"]:
            print(" ", s)
        for s in res.get("progress", []):
            print("   ", s)
        print("page errors:", errors[:5])
        await browser.close()
        ok = any("resolved" in s for s in res["steps"]) and has_poll
        print("PROBE", "OK" if ok else "FAILED", f"in {time.time() - t0:.0f}s")
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(
        asyncio.run(
            main(
                sys.argv[1]
                if len(sys.argv) > 1
                else "https://b8rrs4sydg-cmyk.github.io/TradingStrategy/"
            )
        )
    )
