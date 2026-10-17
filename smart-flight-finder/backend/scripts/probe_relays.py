"""Which anonymous public mailbox can the page (a browser on github.io) and the daemon both use?

Runs real ``fetch`` calls from the published page's origin (so CORS is real) against
candidate services: create a record, read it, overwrite it, read again.
"""

from __future__ import annotations

import asyncio
import json
import sys

from playwright.async_api import async_playwright

JS = r"""
async () => {
  const out = {};
  const t = async (name, fn) => {
    const t0 = performance.now();
    try { out[name] = { ok: true, ...(await fn()), ms: Math.round(performance.now() - t0) }; }
    catch (e) { out[name] = { ok: false, error: String(e).slice(0, 160), ms: Math.round(performance.now() - t0) }; }
  };
  const J = { 'Content-Type': 'application/json', 'Accept': 'application/json' };

  await t('jsonblob', async () => {
    const r = await fetch('https://jsonblob.com/api/jsonBlob', { method: 'POST', headers: J, body: JSON.stringify({ n: 1 }) });
    const loc = r.headers.get('Location') || r.headers.get('location');
    const body = await r.text();
    if (!loc) return { status: r.status, note: 'no readable Location header (CORS not exposed)', body: body.slice(0, 80) };
    const id = loc.split('/').pop();
    const g1 = await (await fetch('https://jsonblob.com/api/jsonBlob/' + id, { headers: J })).json();
    const p = await fetch('https://jsonblob.com/api/jsonBlob/' + id, { method: 'PUT', headers: J, body: JSON.stringify({ n: 2 }) });
    const g2 = await (await fetch('https://jsonblob.com/api/jsonBlob/' + id, { headers: J })).json();
    return { id, g1, put: p.status, g2 };
  });

  await t('kvdb', async () => {
    const r = await fetch('https://kvdb.io/', { method: 'POST', body: 'email=probe@example.com', headers: { 'Content-Type': 'application/x-www-form-urlencoded' } });
    const bucket = (await r.text()).trim();
    if (!/^[A-Za-z0-9]{10,}$/.test(bucket)) return { status: r.status, note: 'no bucket', body: bucket.slice(0, 80) };
    const base = 'https://kvdb.io/' + bucket + '/k1';
    const p1 = await fetch(base, { method: 'POST', body: '1' });
    const g1 = await (await fetch(base)).text();
    await fetch(base, { method: 'POST', body: '2' });
    const g2 = await (await fetch(base)).text();
    return { bucket, put: p1.status, g1, g2 };
  });

  await t('restful-api', async () => {
    const r = await fetch('https://api.restful-api.dev/objects', { method: 'POST', headers: J, body: JSON.stringify({ name: 'sff', data: { n: 1 } }) });
    const o = await r.json();
    const g1 = await (await fetch('https://api.restful-api.dev/objects/' + o.id, { headers: J })).json();
    const p = await fetch('https://api.restful-api.dev/objects/' + o.id, { method: 'PUT', headers: J, body: JSON.stringify({ name: 'sff', data: { n: 2 } }) });
    const g2 = await (await fetch('https://api.restful-api.dev/objects/' + o.id, { headers: J })).json();
    return { id: o.id, g1: g1.data, put: p.status, g2: g2.data };
  });

  await t('npoint', async () => {
    const r = await fetch('https://api.npoint.io/bins', { method: 'POST', headers: J, body: JSON.stringify({ n: 1 }) });
    return { status: r.status, body: (await r.text()).slice(0, 100) };
  });

  await t('ntfy-poll', async () => {   // for reference: the relay we already use, readable with a plain GET
    const r = await fetch('https://ntfy.sh/sff-probe-' + Date.now() + '/json?poll=1');
    return { status: r.status };
  });
  return out;
}
"""


async def main(url: str) -> int:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        await page.goto(url, wait_until="load")
        res = await asyncio.wait_for(page.evaluate(JS), timeout=120)
        print(json.dumps(res, indent=1, ensure_ascii=False))
        await browser.close()
    return 0


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
