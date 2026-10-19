"""EXPERIMENT part 2: where do round-trip and multi-city prices live in the plain-HTTP page?

The browser path says the cheapest single ticket of ``rt|TPE|FUK|2027-04-03|2027-04-10`` is 15,383 and of a
multi-city key 55,330 or so. Find those numbers in what the HTTP page contains (JSON path + neighbours), and list the
other XHR-style endpoints named in the page, so the real parser can be written (or ruled out).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import requests

from app.providers.google_flights import url_for
from scripts.exp_http_fetch import COOKIES, HEADERS, embedded_blocks


def find_ints(node, target, path, hits, depth=0):
    if isinstance(node, bool):
        return
    if isinstance(node, int) and node == target:
        hits.append(path)
    elif isinstance(node, list):
        for i, c in enumerate(node):
            find_ints(c, target, path + [i], hits, depth + 1)
    elif isinstance(node, dict):
        for k, c in node.items():
            find_ints(c, target, path + [k], hits, depth + 1)


def at(node, path):
    for p in path:
        node = node[p]
    return node


def brief(node, depth=0):
    if isinstance(node, list):
        if depth > 2:
            return f"[…{len(node)}]"
        return (
            "["
            + ", ".join(brief(c, depth + 1) for c in node[:8])
            + (", …" if len(node) > 8 else "")
            + "]"
        )
    if isinstance(node, str):
        return json.dumps(node[:24], ensure_ascii=False)
    return json.dumps(node)


def inspect(key: str, db_price: int) -> None:
    print(f"\n===== {key}  (browser says {db_price})", flush=True)
    r = requests.get(url_for(key), headers=HEADERS, cookies=COOKIES, timeout=30)
    html = r.text
    blocks = embedded_blocks(html)
    print(f"http {r.status_code}, {len(html)} bytes, {len(blocks)} AF_initDataCallback blocks")
    for b in blocks:
        print(
            f"  block: top-level length {len(b) if isinstance(b, list) else '-'} "
            f"size {len(json.dumps(b))}"
        )
    hits = []
    for bi, b in enumerate(blocks):
        h = []
        find_ints(b, db_price, [], h)
        hits += [(bi, p) for p in h]
    print(f"the browser price {db_price} appears at {len(hits)} places in the data blocks")
    for bi, p in hits[:4]:
        parent = at(blocks[bi], p[:-2]) if len(p) >= 2 else None
        print(f"  block {bi} path {p}")
        print(f"    context: {brief(parent)}")
    raw = [m.start() for m in re.finditer(re.escape(f"{db_price:,}"), html)]
    print(
        f"formatted '{db_price:,}' occurs {len(raw)}x in the raw html"
        + (f"; e.g. ...{html[max(0, raw[0] - 90) : raw[0] + 30]!r}" if raw else "")
    )
    plain = [m.start() for m in re.finditer(rf"\b{db_price}\b", html)]
    print(f"plain {db_price} occurs {len(plain)}x in the raw html")
    for u in sorted(set(re.findall(r"/_/FlightsFrontendUi/data/[A-Za-z0-9_./]+", html)))[:6]:
        print("  endpoint named in the page:", u)
    print(
        "  'GetShoppingResults' in page:",
        "GetShoppingResults" in html,
        "| 'batchexecute' in page:",
        "batchexecute" in html,
    )


def main() -> int:
    db = json.loads(
        Path(sys.argv[1] if len(sys.argv) > 1 else "../public/fares.json").read_text(
            encoding="utf-8"
        )
    )
    for key in (
        "rt|TPE|FUK|2027-04-03|2027-04-10",
        "rt|TPE|NRT|2027-02-05|2027-04-11",
        "ow|TPE|HKG|2027-01-02",
        "mc|HKG-TPE-2027-02-06|TPE-KIX-2027-02-06|KIX-TPE-2027-02-06"
        if False
        else next(k for k in db["fares"] if k.startswith("mc|HKG-TPE-2027-02-06")),
    ):
        inspect(key, db["fares"][key]["price"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
