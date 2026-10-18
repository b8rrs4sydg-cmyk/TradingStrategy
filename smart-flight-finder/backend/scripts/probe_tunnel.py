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
  // 1. each instance on its own: tunnels announced and healthy?
  out.tunnels = {};
  for (let i = 0; i < INSTANCES; i++) {
    const url = await instanceTunnel(i, true);
    out.tunnels[i] = { url, alt: live.tunnels[i].alt, notes: live.tunnels[i].notes };
    mark(`instance ${i}: tunnel ${url} alt=${JSON.stringify(live.tunnels[i].alt)}`);
  }
  // 2. all instances at once, the way a search uses them
  live.peerMap = new Map(); live.peersAt = 0; live.rtcFail = {}; live.tunnelFail = {};
  const peers = await connectPeers();
  out.peers = peers.map(p => `${p.i}:${p.kind}`);
  mark(`peers: ${out.peers.join(' ')}`);
  live.peerList = peers; live.transport = 'peers';
  const keys = allKeys.slice(0, 9);
  const rid = 'probe' + Date.now().toString(36);
  live.rid = rid; live.keys = keys; live.doc = { status: 'queued', total: keys.length, done: 0, found: 0 };
  try { await ntfyLookup(keys, rid); mark(`parallel lookup resolved found=${live.doc.found} done=${live.doc.done}/${live.doc.total}`); out.resolved = true; }
  catch (e) { mark(`parallel lookup failed: ${e.message} failed=${JSON.stringify(e.failedPeers)}`); out.resolved = false; }
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
        has_poll = await page.evaluate("peersLookup.toString().includes('/poll/')")
        print("page uses long polling:", has_poll, flush=True)
        t0 = time.time()
        res = await asyncio.wait_for(page.evaluate(JS, keys), timeout=150)
        for s in res["steps"]:
            print(" ", s)
        print("page errors:", errors[:5])
        await browser.close()
        print("peers (instance:kind):", res.get("peers"))
        ok = res.get("resolved") is True and len(res.get("peers", [])) >= 1 and has_poll
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
