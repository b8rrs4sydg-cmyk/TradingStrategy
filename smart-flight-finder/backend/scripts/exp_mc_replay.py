"""EXPERIMENT (not used by the product): rebuild the multi-city GetShoppingResults request without a browser.

Round 2 showed the request the page itself sends can be replayed over plain HTTP (0.6 s) when it
carries the browser's cookies, not with the consent cookie alone. This round finds out
  1. what the request body looks like (decoded) for two itineraries that differ in one date,
  2. which cookie is the one that matters and whether a plain GET of the page hands it out,
  3. whether a body rewritten for another itinerary is answered with that itinerary's price.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import requests

from app.providers.google_flights import url_for

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
SOCS = "CAESHAgBEhJnd3NfMjAyMzA4MTAtMF9SQzIaAmVuIAEaBgiAo_CmBg"


def mc_keys(db: dict) -> list[tuple[str, int]]:
    ks = sorted(k for k, e in db["fares"].items() if k.startswith("mc|") and e.get("price"))
    a = next(k for k in ks if "TPE-KIX" in k)
    stem, last = a.rsplit("-", 1)
    b = next((k for k in ks if k.startswith(stem.rsplit("-", 2)[0]) and k != a), ks[1])
    return [(a, db["fares"][a]["price"]), (b, db["fares"][b]["price"])]


def capture(key: str) -> dict:
    from playwright.sync_api import sync_playwright

    out: dict = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(locale="en-US", user_agent=UA)
        ctx.add_cookies([{"name": "SOCS", "value": SOCS, "domain": ".google.com", "path": "/"}])
        page = ctx.new_page()

        def on_req(r):
            if "GetShoppingResults" in r.url and r.method == "POST":
                out["url"] = r.url
                out["body"] = r.post_data or ""
                out["headers"] = dict(r.headers)

        page.on("request", on_req)
        page.goto(url_for(key), wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(6000)
        out["cookies"] = {c["name"]: c["value"] for c in ctx.cookies()}
        b.close()
    return out


def decode(body: str) -> object:
    freq = parse_qs(body)["f.req"][0]
    outer = json.loads(freq)
    return outer, json.loads(outer[1])


def prices(text: str) -> list[int]:
    return sorted({int(n) for n in re.findall(r"\[null,(\d{4,6})\]", text)})


def main() -> None:
    db = json.loads(Path(sys.argv[1]).read_text())
    (ka, pa), (kb, pb) = mc_keys(db)
    print(f"A={ka} db={pa}\nB={kb} db={pb}")
    ca, cb = capture(ka), capture(kb)
    print("\ncookies seen in browser:", sorted(ca["cookies"]))
    print("url params:", {k: v[0][:60] for k, v in parse_qs(urlsplit(ca["url"]).query).items()})
    oa, ia = decode(ca["body"])
    ob, ib = decode(cb["body"])
    print("\nouter A:", json.dumps(oa)[:100], "... tail:", json.dumps(oa)[-120:])
    print("\ninner A:", json.dumps(ia))
    print("\ninner B:", json.dumps(ib))
    print("\nbody tail (raw):", unquote(ca["body"])[-200:])

    url = ca["url"]
    hdr = {
        "User-Agent": UA,
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "X-Same-Domain": "1",
    }

    def post(body: str, cookies: dict, label: str, want: int) -> None:
        t = time.time()
        r = requests.post(url, data=body, headers=hdr, cookies=cookies, timeout=30)
        ps = prices(r.text)
        print(
            f"  {label}: HTTP {r.status_code} len={len(r.text)} {time.time() - t:.2f}s prices={ps[:5]} match={want in ps}"
        )

    print("\n-- which cookies matter (body A)")
    post(ca["body"], ca["cookies"], "all browser cookies", pa)
    for name in ca["cookies"]:
        rest = {k: v for k, v in ca["cookies"].items() if k != name}
        post(ca["body"], rest, f"without {name}", pa)

    print("\n-- cookies from a plain GET of the page")
    s = requests.Session()
    s.headers["User-Agent"] = UA
    s.cookies.set("SOCS", SOCS, domain=".google.com")
    g = s.get(url_for(ka), timeout=30)
    print("  GET", g.status_code, "cookies:", sorted(s.cookies.keys()))
    post(ca["body"], s.cookies.get_dict(), "plain-GET cookies", pa)

    print("\n-- body B replayed with the cookies of A (B's own captured body)")
    post(cb["body"], ca["cookies"], "B body", pb)

    print("\n-- body A string-rewritten into B")
    ra = json.dumps(ia, separators=(",", ":"))
    rb = json.dumps(ib, separators=(",", ":"))
    print("  inner A == inner B apart from dates?", ra != rb, len(ra), len(rb))
    Path("/tmp/mc_bodies.json").write_text(json.dumps({"a": ia, "b": ib}))


if __name__ == "__main__":
    main()
