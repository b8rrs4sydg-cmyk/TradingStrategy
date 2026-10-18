"""EXPERIMENT (not used by the product): price multi-city keys with a request built from scratch.

Takes one request captured from the browser as a template, then for other keys swaps in the
airports/dates, with and without the per-search token, using only cookies a plain GET hands out.
"""

from __future__ import annotations

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

import requests

from app.providers.google_flights import url_for
from scripts.exp_mc_replay import SOCS, UA, capture, decode, mc_keys, prices

ENDPOINT = "https://www.google.com/_/FlightsFrontendUi/data/travel.frontend.flights.FlightsFrontendService/GetShoppingResults"


def leg(a: str, b: str, day: str) -> list:
    return [
        [[[a, 0]]],
        [[[b, 0]]],
        None,
        0,
        None,
        None,
        day,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        3,
    ]


def build_body(template_inner: list, key: str, token: str | None) -> str:
    inner = json.loads(json.dumps(template_inner))
    legs = []
    for seg in key.split("|")[1:]:
        o, d, y, m, dd = seg.split("-")
        legs.append(leg(o, d, f"{y}-{m}-{dd}"))
    inner[0][3] = token
    inner[1][13] = legs
    flat = json.dumps(inner, separators=(",", ":"))
    return "f.req=" + quote(json.dumps([None, flat], separators=(",", ":")), safe="") + "&"


def session() -> tuple[requests.Session, dict]:
    s = requests.Session()
    s.headers["User-Agent"] = UA
    s.cookies.set("SOCS", SOCS, domain=".google.com")
    g = s.get(url_for("mc|TPE-NRT-2027-04-01|NRT-TPE-2027-04-05"), params={}, timeout=30)
    sid = re.search(r'"FdrFJe":"(-?\d+)"', g.text)
    bl = re.search(r'"cfb2h":"([^"]+)"', g.text)
    return s, {"sid": sid.group(1) if sid else None, "bl": bl.group(1) if bl else None}


def main() -> None:
    db = json.loads(Path(sys.argv[1]).read_text())
    (ka, pa), _ = mc_keys(db)
    cap = capture(ka)
    _, tmpl = decode(cap["body"])
    token = tmpl[0][3]
    mc = sorted(k for k, e in db["fares"].items() if k.startswith("mc|") and e.get("price"))
    step = max(1, len(mc) // 10)
    sample = [(k, db["fares"][k]["price"]) for k in mc[::step][:10]]
    s, info = session()
    print("scraped from page:", info, "cookies:", sorted(s.cookies.keys()))
    params = {
        "f.sid": info["sid"] or "",
        "bl": info["bl"] or "",
        "hl": "en",
        "gl": "TW",
        "soc-app": "162",
        "soc-platform": "1",
        "soc-device": "1",
        "_reqid": "100001",
        "rt": "c",
    }
    hdr = {"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "X-Same-Domain": "1"}

    def one(item: tuple[str, int], tok: str | None, label: str) -> str:
        k, want = item
        body = build_body(tmpl, k, tok)
        t = time.time()
        try:
            r = s.post(ENDPOINT, params=params, data=body, headers=hdr, timeout=12)
        except requests.RequestException as e:
            return f"{label:10s} {type(e).__name__} after {time.time()-t:.1f}s  {k[3:60]}"
        ps = prices(r.text)
        got = ps[0] if ps else None
        return f"{label:10s} HTTP {r.status_code} len={len(r.text):6d} {time.time() - t:.2f}s min={got} db={want} {'MATCH' if got == want else ''}  {k[3:60]}"

    print("\n-- captured URL params + captured body, plain-GET cookies")
    r0 = s.post(ENDPOINT, params=cap_params, data=cap["body"], headers=hdr, timeout=12)
    print("  ", r0.status_code, len(r0.text), prices(r0.text)[:4])
    print("-- captured URL params + rebuilt body")
    r1 = s.post(ENDPOINT, params=cap_params, data=rebuilt, headers=hdr, timeout=12)
    print("  ", r1.status_code, len(r1.text), prices(r1.text)[:4])
    params = cap_params
    for label, tok in (("with-token", token), ("null-token", None)):
        print(f"\n-- sequential, {label}")
        res = [one(it, tok, label) for it in sample]
        print("\n".join(res))
        print("  matches:", sum("MATCH" in r for r in res), "/", len(res))
    print("\n-- 10 in parallel, null token")
    with ThreadPoolExecutor(10) as ex:
        res = list(ex.map(lambda it: one(it, None, "parallel"), sample))
    print("\n".join(res))
    print("  matches:", sum("MATCH" in r for r in res), "/", len(res))


if __name__ == "__main__":
    main()
