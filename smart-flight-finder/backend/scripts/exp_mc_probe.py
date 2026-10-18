"""EXPERIMENT (not used by the product): can a multi-city fare be priced without the browser?

Part A  records what the browser itself requests for a multi-city Google Flights search (the page
        HTML carries no prices for it, so the prices must arrive through a data request) and replays
        that request with plain HTTP.
Part B  asks other fare sites (Trip.com, Skyscanner, Kayak, ...) for the same itinerary over plain
        HTTP and reports whether they answer or put up a bot wall.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import requests

from app.providers.google_flights import url_for

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
HDR = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}


def pick_mc(db: dict) -> tuple[str, int]:
    ks = sorted(k for k, e in db["fares"].items() if k.startswith("mc|") and e.get("price"))
    k = next((k for k in ks if "TPE-KIX" in k), ks[0])
    return k, db["fares"][k]["price"]


def part_a(key: str, price: int) -> None:
    from playwright.sync_api import sync_playwright

    print(f"\n== A. Google Flights multi-city data request  key={key} db={price}")
    seen: list[dict] = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(locale="en-US", user_agent=UA)
        ctx.add_cookies(
            [
                {
                    "name": "SOCS",
                    "value": "CAESHAgBEhJnd3NfMjAyMzA4MTAtMF9SQzIaAmVuIAEaBgiAo_CmBg",
                    "domain": ".google.com",
                    "path": "/",
                }
            ]
        )
        page = ctx.new_page()

        def on_resp(r):
            u = r.url
            if "google.com" in u and r.request.method == "POST":
                try:
                    body = r.text()
                except Exception:  # noqa: BLE001
                    body = ""
                seen.append(
                    {
                        "url": u,
                        "req": r.request.post_data or "",
                        "hdr": r.request.headers,
                        "status": r.status,
                        "len": len(body),
                        "body": body,
                    }
                )

        page.on("response", on_resp)
        t = time.time()
        page.goto(url_for(key), wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(8000)
        print(f"browser load {time.time() - t:.1f}s, POST responses: {len(seen)}")
        html = page.content()
        m = re.findall(r"([\d,]+) New Taiwan dollars", html)
        print("browser prices:", sorted({int(x.replace(",", "")) for x in m})[:8])
        cookies = {c["name"]: c["value"] for c in ctx.cookies()}
        b.close()
    for s in seen:
        print(f"- {s['status']} len={s['len']} {s['url'][:150]}")
        print(f"  req[:300]={s['req'][:300]!r}")
        print(f"  resp[:200]={s['body'][:200]!r}")
    big = [s for s in seen if s["len"] > 5000]
    if not big:
        print("no large data response captured")
        return
    s = max(big, key=lambda x: x["len"])
    print("\nreplaying the biggest response over plain HTTP ...")
    h = {
        k: v
        for k, v in s["hdr"].items()
        if k.lower() in ("content-type", "x-goog-ext-259736195-jspb", "x-same-domain")
    }
    h["User-Agent"] = UA
    for label, ck in (
        ("with browser cookies", cookies),
        ("with SOCS only", {"SOCS": "CAESHAgBEhJnd3NfMjAyMzA4MTAtMF9SQzIaAmVuIAEaBgiAo_CmBg"}),
    ):
        t = time.time()
        r = requests.post(s["url"], data=s["req"], headers=h, cookies=ck, timeout=30)
        nums = re.findall(r"\[null,(\d{4,6})\]", r.text)
        print(
            f"  {label}: HTTP {r.status_code} len={len(r.text)} {time.time() - t:.2f}s "
            f"price-like={sorted({int(n) for n in nums})[:6]} match_db={str(price) in nums}"
        )
    Path("/tmp/mc_capture.json").write_text(json.dumps({"url": s["url"], "req": s["req"]})[:200000])


def part_b(key: str) -> None:
    print("\n== B. other providers over plain HTTP (same itinerary class)")
    legs = key.split("|")[1:]
    # key: mc|A-B-day|C-D-day|E-F-day
    parts = [x.split("-") for x in legs]
    d = [f"{p[2]}-{p[3]}-{p[4]}" for p in parts]  # YYYY-MM-DD
    o = [(p[0], p[1]) for p in parts]
    ck = lambda i: o[i][0].lower()
    tests = {
        "skyscanner.com.tw": f"https://www.skyscanner.com.tw/transport/flights/{ck(0)}/{o[0][1].lower()}/{d[0][2:].replace('-', '')}/",
        "skyscanner.net(api)": "https://www.skyscanner.net/g/radar/api/v2/web-unified-search/",
        "trip.com search": f"https://tw.trip.com/flights/{ck(0)}-to-{o[0][1].lower()}/tickets-{ck(0)}-{o[0][1].lower()}?dcity={ck(0)}&acity={o[0][1].lower()}&ddate={d[0]}&triptype=ow&class=y&quantity=1",
        "trip.com api": "https://tw.trip.com/restapi/soa2/27015/FlightListSearch",
        "kayak multi": "https://www.kayak.com.tw/flights/"
        + "/".join(f"{a}-{b}/{dd}" for (a, b), dd in zip(o, d))
        + "?sort=price_a",
        "momondo": "https://www.momondo.com/flight-search/"
        + "/".join(f"{a}-{b}/{dd}" for (a, b), dd in zip(o, d)),
        "expedia": f"https://www.expedia.com.tw/Flights-Search?flight-type=on&mode=search&trip=multi&leg1=from:{o[0][0]},to:{o[0][1]},departure:{d[0].replace('-', '/')}TANYT&passengers=adults:1",
        "skiplagged": f"https://skiplagged.com/flights/{o[0][0]}/{o[0][1]}/{d[0]}",
        "wego": f"https://www.wego.com.tw/flights/searches/{o[0][0]}-{o[0][1]}/{d[0]}",
    }
    for name, u in tests.items():
        try:
            t = time.time()
            r = requests.get(
                u, headers={**HDR, "Accept": "text/html,*/*"}, timeout=20, allow_redirects=True
            )
            low = r.text.lower()
            wall = [
                w
                for w in (
                    "captcha",
                    "are you a person",
                    "access denied",
                    "px-captcha",
                    "cf-chl",
                    "just a moment",
                    "robot",
                    "unusual traffic",
                )
                if w in low
            ]
            price = re.findall(r"(?:NT\$|TWD|\$)\s?[\d,]{4,7}", r.text)[:4]
            print(
                f"- {name:20s} HTTP {r.status_code} len={len(r.text):7d} {time.time() - t:.1f}s walls={wall} prices={price}"
            )
        except Exception as e:  # noqa: BLE001
            print(f"- {name:20s} ERROR {type(e).__name__}: {str(e)[:100]}")


def main() -> None:
    db = json.loads(Path(sys.argv[1]).read_text())
    key, price = pick_mc(db)
    part_a(key, price)
    part_b(key)


if __name__ == "__main__":
    main()
