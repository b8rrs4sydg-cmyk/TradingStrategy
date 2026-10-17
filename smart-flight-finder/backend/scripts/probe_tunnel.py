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
async (allKeys) => {
  const t0 = performance.now();
  const out = { steps: [] };
  const mark = s => out.steps.push(`${((performance.now() - t0) / 1000).toFixed(1)}s ${s}`);
  const url = await discoverDaemon(true);
  mark(`discovered ${url} alternatives=${JSON.stringify(live.daemonAlt || [])} notes=${JSON.stringify(live.daemonNotes)}`);
  if (!url) return out;
  try {   // peer to peer first: no tunnel at all
    const c = await rtcEnsure();
    live.transport = 'rtc';
    const rid = 'probertc' + Date.now().toString(36), keys = allKeys.slice(6, 9);
    live.rid = rid; live.keys = keys; live.doc = { status: 'queued', total: keys.length, done: 0, found: 0 };
    await ntfyLookup(keys, rid);
    mark(`peer to peer (${c.sid}): lookup resolved found=${live.doc.found}`);
    out.rtc = true;
  } catch (e) { mark('peer to peer failed: ' + e.message); out.rtc = false; }
  const tunnels = [url, ...(live.daemonAlt || [])];
  out.tunnels = tunnels.length;
  out.resolved = 0;
  for (const [i, u] of tunnels.entries()) {   // every announced tunnel must carry a lookup on its own
    const keys = allKeys.slice(i * 3, i * 3 + 3);
    live.transport = 'http'; live.daemonUrl = u;
    const rid = 'probe' + i + Date.now().toString(36);
    live.rid = rid; live.keys = keys; live.doc = { status: 'queued', total: keys.length, done: 0, found: 0 };
    try { await ntfyLookup(keys, rid); mark(`${u}: lookup resolved found=${live.doc.found}`); out.resolved++; }
    catch (e) { mark(`${u}: lookup failed: ${e.message}`); }
  }
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
            "Object.keys(FARES.fares).filter(k => k.startsWith('ow|')).slice(0, 9)"
        )
        print("keys:", keys, flush=True)
        has_poll = await page.evaluate("ntfyLookup.toString().includes('/poll/')")
        print("page uses long polling:", has_poll, flush=True)
        t0 = time.time()
        res = await asyncio.wait_for(page.evaluate(JS, keys), timeout=150)
        for s in res["steps"]:
            print(" ", s)
        print("page errors:", errors[:5])
        await browser.close()
        print("peer to peer (no tunnel):", res.get("rtc"))
        ok = res.get("resolved", 0) >= 1 and has_poll and res.get("rtc") is True
        print("tunnels announced:", res.get("tunnels"), "carrying a lookup:", res.get("resolved"))
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
