"""EXPERIMENT: why does the plain-HTTP data request sometimes miss data or return a price that is too high?

For keys where HTTP was wrong, record the browser's own request/response and compare, per variant and 4 repeats:
  browser   the response the browser got for that request
  captured  the browser's exact body (with its per-search token) replayed over HTTP
  null      body rebuilt from the key, token left empty
  scraped   body rebuilt, token taken from the plain-GET page if one is in there
and show how many itinerary rows / response rows each gives and the cheapest price (database price = truth).
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import requests

from app.providers.google_flights import parse_key, url_for
from app.providers.google_http import itineraries, rpc_payloads
from scripts.exp_http_xhr import body_from
from scripts.exp_mc_build import ENDPOINT
from scripts.exp_mc_replay import SOCS, UA, decode

KEYS = [
    "rt|TPE|PUS|2027-04-02|2027-04-10",
    "rt|TPE|ICN|2027-04-02|2027-06-13",
    "rt|TPE|LHR|2027-04-02|2027-04-11",
    "rt|TPE|NRT|2027-02-04|2027-04-12",
    "ow|TPE|ICN|2027-02-28",
    "rt|TPE|SIN|2027-04-04|2027-04-11",
]
TOKEN = re.compile(r"[A-Za-z0-9_-]{16,}-{6,}[A-Za-z0-9_-]{12,}")


def stats(text: str) -> str:
    rows = list(rpc_payloads(text))
    its = [r for p in rows for r in itineraries(p)]
    prices = sorted(r[1][0][1] for r in its)
    return f"rows={len(rows)} itins={len(its)} min={prices[0] if prices else None} len={len(text)}"


def browser_capture(key: str) -> dict:
    from playwright.sync_api import sync_playwright

    out: dict = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(locale="en-US", user_agent=UA)
        ctx.add_cookies([{"name": "SOCS", "value": SOCS, "domain": ".google.com", "path": "/"}])
        page = ctx.new_page()
        calls: list[dict] = []

        def on_resp(r):
            if "GetShoppingResults" in r.url:
                try:
                    calls.append(
                        {"url": r.url, "body": r.request.post_data or "", "text": r.text()}
                    )
                except Exception:  # noqa: BLE001, S110 — a response without a body is skipped
                    pass

        page.on("response", on_resp)
        page.goto(url_for(key), wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(7000)
        dom = page.evaluate(
            '[...document.querySelectorAll(\'li div[aria-label*="New Taiwan dollars"], [aria-label*="New Taiwan dollars"]\')]'
            ".map(e => e.getAttribute('aria-label'))"
        )
        prices = sorted(
            {
                int(m.replace(",", ""))
                for lab in dom
                for m in re.findall(r"([\d,]+) New Taiwan dollars", lab or "")
            }
        )
        out = {"calls": calls, "dom_min": prices[0] if prices else None}
        b.close()
    return out


def main() -> None:
    db = json.loads(Path(sys.argv[1]).read_text())
    s = requests.Session()
    s.headers["User-Agent"] = UA
    s.cookies.set("SOCS", SOCS, domain=".google.com")
    hdr = {"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "X-Same-Domain": "1"}
    for key in KEYS:
        truth = db["fares"].get(key, {}).get("price")
        print(f"\n##### {key}  database={truth}")
        cap = browser_capture(key)
        print(f"browser: {len(cap['calls'])} data request(s); page shows min {cap['dom_min']}")
        for i, c in enumerate(cap["calls"]):
            print(f"  call {i}: {stats(c['text'])}")
        if not cap["calls"]:
            continue
        c0 = cap["calls"][0]
        params = {k: v[0] for k, v in parse_qs(urlsplit(c0["url"]).query).items()}
        _, tmpl = decode(c0["body"])
        segs = parse_key(key)[1]
        page = s.get(url_for(key), timeout=30)
        scraped = TOKEN.findall(page.text)
        print(
            f"  token-like strings in the plain page: {len(scraped)} (browser token: {tmpl[0][3]!r})"
        )

        def with_token(tok):
            inner = json.loads(json.dumps(tmpl))  # noqa: B023 — called inside the loop it belongs to
            inner[0][3] = tok
            body = body_from(inner, segs)  # noqa: B023
            return (
                body
                if tok is None
                else body.replace(
                    "null%2Cnull%2Cnull%2Cnull%5D", "null%2Cnull%2Cnull%2C%22" + tok + "%22%5D", 1
                )
            )

        variants = {"captured": c0["body"], "null": body_from(tmpl, segs)}
        for variant, body in variants.items():
            res = []
            for _ in range(4):
                t = time.time()
                try:
                    r = s.post(ENDPOINT, params=params, data=body, headers=hdr, timeout=10)
                    res.append(f"{stats(r.text)} {time.time() - t:.1f}s")
                except requests.RequestException as e:
                    res.append(type(e).__name__)
                time.sleep(0.5)
            print(f"  {variant:9s}: " + " | ".join(res))


if __name__ == "__main__":
    main()
