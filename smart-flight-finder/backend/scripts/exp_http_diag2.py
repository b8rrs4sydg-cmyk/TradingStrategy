"""EXPERIMENT: where does the cheap itinerary that the page shows live, when the data request lacks it?

Per key: record every Google POST the browser makes (URL path, size), the page's own price rows, then look for the
database price (as a number) inside each response, inside the plain-GET HTML blocks, and print the path to it.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import requests

from app.providers.google_flights import url_for
from app.providers.google_http import html_payloads, rpc_payloads
from scripts.exp_mc_replay import SOCS, UA

KEYS = [
    "rt|TPE|PUS|2027-04-02|2027-04-10",
    "rt|TPE|LHR|2027-04-02|2027-04-11",
    "rt|TPE|ICN|2027-04-02|2027-06-13",
]


def find(node, want, path=()):
    """Yield the path of every list that holds the integer ``want``."""
    if isinstance(node, list):
        for i, c in enumerate(node):
            if c == want and not isinstance(c, bool):
                yield path + (i,)
            else:
                yield from find(c, want, path + (i,))


def describe(payloads, label, want):
    for pi, p in enumerate(payloads):
        hits = list(find(p, want))
        print(f"  {label} payload {pi}: size {len(json.dumps(p))}  hits for {want}: {len(hits)}")
        for h in hits[:3]:
            node = p
            for i in h[:-3]:
                node = node[i]
            print(f"    path {list(h)}")
            print(f"    around: {json.dumps(node)[:500]}")


def main() -> None:
    from playwright.sync_api import sync_playwright

    db = json.loads(Path(sys.argv[1]).read_text())
    s = requests.Session()
    s.headers["User-Agent"] = UA
    s.cookies.set("SOCS", SOCS, domain=".google.com")
    for key in KEYS:
        want = db["fares"][key]["price"]
        print(f"\n##### {key} database={want}")
        posts: list[tuple[str, int, str]] = []
        with sync_playwright() as p:
            b = p.chromium.launch()
            ctx = b.new_context(locale="en-US", user_agent=UA)
            ctx.add_cookies([{"name": "SOCS", "value": SOCS, "domain": ".google.com", "path": "/"}])
            page = ctx.new_page()

            def on(r, posts=posts):
                if r.request.method == "POST" and "google.com" in r.url:
                    try:
                        posts.append((r.url.split("?")[0].split("/")[-1], r.status, r.text()))
                    except Exception:  # noqa: BLE001
                        pass

            page.on("response", on)
            page.goto(url_for(key), wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(8000)
            labels = page.evaluate(
                "[...document.querySelectorAll('[aria-label*=\"New Taiwan dollars\"]')].map(e => e.getAttribute('aria-label'))"
            )
            html_browser = page.content()
            b.close()
        near = [lab for lab in labels if str(want) in lab.replace(",", "") or f"{want:,}" in lab]
        print(f"page rows: {len(labels)}; rows with the database price: {len(near)}")
        for lab in near[:2]:
            print("   ", lab[:300])
        print("browser POSTs:", [(n, st, len(t)) for n, st, t in posts])
        for n, st, t in posts:
            raw = t.count(str(want))
            print(f"  POST {n}: raw occurrences of {want}: {raw}")
            if n == "GetShoppingResults":
                describe(list(rpc_payloads(t)), "browser-XHR", want)
        r = s.get(url_for(key), timeout=30)
        pays = list(html_payloads(r.text))
        print(
            f"plain GET html: {len(r.text)} bytes, {len(pays)} blocks, raw occurrences of {want}: {r.text.count(str(want))}"
        )
        describe(pays, "html", want)
        print(
            f"browser DOM html: raw occurrences of {want}: {html_browser.count(str(want))}; blocks {len(list(html_payloads(html_browser)))}"
        )


if __name__ == "__main__":
    main()
