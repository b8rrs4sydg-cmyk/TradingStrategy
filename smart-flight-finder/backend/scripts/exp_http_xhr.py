"""EXPERIMENT: price one-way / round-trip / multi-city keys through the GetShoppingResults request only.

For each kind a request is captured from the browser (to learn the body layout), then 20 keys of that kind are
posted from plain HTTP with three variants of the f.sid parameter, and judged with the production parser.
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

from app.providers.google_flights import parse_key, url_for
from app.providers.google_http import entry_from, rpc_payloads
from scripts.exp_mc_build import ENDPOINT
from scripts.exp_mc_replay import SOCS, UA, capture, decode

TIMEOUT = 8


def legs_of(segments):
    return [
        [
            [[[o, 0]]],
            [[[d, 0]]],
            None,
            0,
            None,
            None,
            day.isoformat(),
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            3,
        ]
        for o, d, day in segments
    ]


def body_from(tmpl_inner, segments) -> str:
    inner = json.loads(json.dumps(tmpl_inner))
    inner[0][3] = None
    inner[1][13] = legs_of(segments)
    flat = json.dumps(inner, separators=(",", ":"))
    return "f.req=" + quote(json.dumps([None, flat], separators=(",", ":")), safe="") + "&"


def main() -> None:
    db = json.loads(Path(sys.argv[1]).read_text())
    s = requests.Session()
    s.headers["User-Agent"] = UA
    s.cookies.set("SOCS", SOCS, domain=".google.com")
    g = s.get(url_for("ow|TPE|NRT|2027-04-01"), timeout=30)
    scraped = re.search(r'"FdrFJe":"(-?\d+)"', g.text).group(1)
    bl = re.search(r'"cfb2h":"([^"]+)"', g.text).group(1)
    print("cookies", sorted(s.cookies.keys()), "scraped sid", scraped)
    hdr = {"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "X-Same-Domain": "1"}
    for kind in ("ow", "rt", "mc"):
        ks = sorted(
            k for k, e in db["fares"].items() if k.startswith(kind + "|") and e.get("price")
        )
        step = max(1, len(ks) // 20)
        sample = ks[::step][:20]
        cap = capture(sample[0])
        if "body" not in cap:
            print(kind, "no XHR captured")
            continue
        _, tmpl = decode(cap["body"])
        print(f"\n=== {kind}: template inner = {json.dumps(tmpl)[:700]}")
        from urllib.parse import parse_qs, urlsplit

        capq = {k: v[0] for k, v in parse_qs(urlsplit(cap["url"]).query).items()}
        for label, sid in (
            ("no-sid", None),
            ("scraped-sid", scraped),
            ("browser-sid", capq["f.sid"]),
        ):
            params = {**capq, "bl": bl}
            params.pop("f.sid", None)
            if sid:
                params["f.sid"] = sid

            def one(k, params=params):
                segs = parse_key(k)[1]
                t = time.time()
                try:
                    r = s.post(
                        ENDPOINT,
                        params=params,
                        data=body_from(tmpl, segs),
                        headers=hdr,
                        timeout=TIMEOUT,
                    )
                except requests.RequestException:
                    return k, None, time.time() - t
                return k, entry_from(rpc_payloads(r.text), segs), time.time() - t

            t0 = time.time()
            with ThreadPoolExecutor(10) as ex:
                res = list(ex.map(one, sample))
            got = [(k, e) for k, e, _ in res if e]
            exact = sum(e["price"] == db["fares"][k]["price"] for k, e in got)
            close = sum(
                abs(e["price"] - db["fares"][k]["price"]) <= 0.02 * db["fares"][k]["price"]
                for k, e in got
            )
            higher = [
                (k[:40], e["price"], db["fares"][k]["price"])
                for k, e in got
                if e["price"] > 1.02 * db["fares"][k]["price"]
            ]
            lower = [
                (k[:40], e["price"], db["fares"][k]["price"])
                for k, e in got
                if e["price"] < 0.98 * db["fares"][k]["price"]
            ]
            print(
                f"{kind} {label:12s} data {len(got)}/{len(sample)} exact {exact} within2% {close} "
                f"higher {len(higher)} lower {len(lower)}  total {time.time() - t0:.1f}s median {sorted(t for *_, t in res)[len(res) // 2]:.2f}s"
            )
            for h in higher[:3]:
                print("   higher", h)
            for h in lower[:3]:
                print("   lower ", h)


if __name__ == "__main__":
    main()
