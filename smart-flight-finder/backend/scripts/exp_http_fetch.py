"""EXPERIMENT (not used by the product): can Google Flights prices be read with plain HTTP, no browser?

For a sample of keys that the fare database already prices (through the headless browser) this
  1. requests the same ``tfs`` search URL with an HTTP client,
  2. looks for the flight data embedded in the page (``AF_initDataCallback``),
  3. extracts the cheapest price and compares it with the database,
  4. measures latency, then hammers it with parallel requests to see when Google starts refusing.
Run from a GitHub runner (the daemon's network), because that is where it would have to work.
"""

from __future__ import annotations

import json
import re
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.providers.google_flights import url_for

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
# a pre-accepted consent cookie, so an EU-style consent wall is not served
COOKIES = {
    "SOCS": "CAESHAgBEhJnd3NfMjAyMzA4MTAtMF9SQzIaAmVuIAEaBgiAo_CmBg",
    "CONSENT": "PENDING+987",
}


def pick_keys(db: dict, n_each: int = 5) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for kind in ("ow", "rt", "mc"):
        ks = [k for k, e in db["fares"].items() if k.startswith(kind + "|") and e.get("price")]
        ks.sort()
        step = max(1, len(ks) // n_each)
        out += [(k, db["fares"][k]["price"]) for k in ks[::step][:n_each]]
    return out


def embedded_blocks(html: str) -> list[object]:
    """JSON payloads of every ``AF_initDataCallback({... data: [...] ...})`` in the page."""

    blocks = []
    for m in re.finditer(r"AF_initDataCallback\(\{key: 'ds:\d+', hash: '[^']*', data:", html):
        start = m.end()
        depth, i, in_str, esc = 0, start, False, False
        while i < len(html):
            c = html[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c in "[{":
                depth += 1
            elif c in "]}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        try:
            blocks.append(json.loads(html[start : i + 1]))
        except ValueError:
            pass
    return blocks


def prices_in(node: object, out: list[int]) -> None:
    """Every ``[[None, price], token]`` pair — how Google lists an itinerary's price."""

    if isinstance(node, list):
        if (
            len(node) >= 1
            and isinstance(node[0], list)
            and len(node[0]) == 2
            and node[0][0] is None
            and isinstance(node[0][1], int)
            and 100 < node[0][1] < 2_000_000
        ):
            out.append(node[0][1])
        for child in node:
            prices_in(child, out)


def fetch(session, key: str) -> dict:
    t0 = time.time()
    try:
        r = session.get(
            url_for(key), headers=HEADERS, cookies=COOKIES, timeout=30, allow_redirects=True
        )
    except Exception as e:  # noqa: BLE001
        return {
            "key": key,
            "ok": False,
            "error": f"{type(e).__name__}: {str(e)[:80]}",
            "s": time.time() - t0,
        }
    html = r.text
    res = {
        "key": key,
        "status": r.status_code,
        "bytes": len(html),
        "s": round(time.time() - t0, 2),
        "url": str(r.url)[:70],
    }
    res["consent_wall"] = "consent.google" in str(r.url) or "Before you continue" in html[:5000]
    res["captcha"] = "unusual traffic" in html or "/sorry/" in str(r.url)
    prices: list[int] = []
    for b in embedded_blocks(html):
        prices_in(b, prices)
    res["n_prices"] = len(prices)
    res["min_price"] = min(prices) if prices else None
    # the aria-labels the browser path reads may also be in the server-rendered HTML
    res["aria_prices"] = [
        int(x.replace(",", "")) for x in re.findall(r"([\d,]+) New Taiwan dollars", html)
    ][:5]
    res["ok"] = bool(prices or res["aria_prices"])
    return res


def main() -> int:
    import requests

    db_path = Path(sys.argv[1] if len(sys.argv) > 1 else "../public/fares.json")
    db = json.loads(db_path.read_text(encoding="utf-8"))
    sample = pick_keys(db)
    print(f"sample: {len(sample)} keys that the browser crawl priced", flush=True)

    s = requests.Session()
    rows = []
    print("\n--- sequential, one at a time ---", flush=True)
    for key, db_price in sample:
        r = fetch(s, key)
        r["db_price"] = db_price
        rows.append(r)
        got = r.get("min_price") or (min(r["aria_prices"]) if r.get("aria_prices") else None)
        print(
            f"{key[:44]:44} http={r.get('status')} {r.get('bytes', 0):>7}B {r['s']:>5}s "
            f"consent={r.get('consent_wall')} captcha={r.get('captcha')} prices={r.get('n_prices')} "
            f"http_min={got} db={db_price} {'MATCH' if got == db_price else ''}",
            flush=True,
        )
    ok = [r for r in rows if r.get("ok")]
    match = [r for r in ok if (r.get("min_price") or min(r["aria_prices"] or [0])) == r["db_price"]]
    print(
        f"\nanswered with data: {len(ok)}/{len(rows)}; same cheapest price as the browser: {len(match)}/{len(rows)}"
    )
    if ok:
        print(
            f"latency of answered requests: median {statistics.median(r['s'] for r in ok):.2f}s, max {max(r['s'] for r in ok):.2f}s"
        )

    print("\n--- 24 requests in parallel (8 at a time) ---", flush=True)
    t0 = time.time()
    keys = [k for k, _ in sample] * 2
    with ThreadPoolExecutor(8) as pool:
        par = list(pool.map(lambda k: fetch(requests.Session(), k), keys[:24]))
    statuses = {}
    for r in par:
        statuses[r.get("status", r.get("error"))] = (
            statuses.get(r.get("status", r.get("error")), 0) + 1
        )
    print(
        f"done in {time.time() - t0:.1f}s; statuses={statuses}; with data {sum(1 for r in par if r.get('ok'))}/24; "
        f"captcha={sum(1 for r in par if r.get('captcha'))} consent={sum(1 for r in par if r.get('consent_wall'))}"
    )

    verdict = len(ok) >= 0.8 * len(rows) and len(match) >= 0.6 * len(rows)
    print("\nVERDICT:", "FEASIBLE" if verdict else "NOT FEASIBLE (as is)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
