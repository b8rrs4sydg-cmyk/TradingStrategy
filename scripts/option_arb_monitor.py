#!/usr/bin/env python3
"""
Live scan of Binance European options for the no-arbitrage violations tested in
research/option_arb.py and research/option_arb2.py, using PUBLIC endpoints only (no API key):

    parity vs spot, vertical monotonicity / width, butterfly convexity, calendar,
    synthetic forward vs the quarterly USDT-M delivery future

Executable prices only (buy at ask, sell at bid) and Binance fees.  The ticker endpoint has no
sizes: before acting on a hit, check the size at the touch in the order book (UI or
`/eapi/v1/depth?symbol=...`) - in the backtest it was usually 0.01-0.1 BTC.  Nothing here places orders.

    python scripts/option_arb_monitor.py                    # one scan, BTC + ETH
    python scripts/option_arb_monitor.py --loop 300         # every 5 minutes, append to a CSV log

The research found these hits rare, small (0.01-0.1 BTC at the touch) and mostly gone within an
hour, so treat the log as a forward paper test: if it shows real, fillable size, it is worth more
work; if not, it confirms the backtest.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "research"))
import option_arb2 as oa2  # noqa: E402

EAPI = "https://eapi.binance.com/eapi/v1"
FAPI = "https://fapi.binance.com/fapi/v1"
SPOT_API = "https://api.binance.com/api/v3"


def get(url: str):
    with urlopen(Request(url, headers={"User-Agent": "option-arb-monitor"}), timeout=20) as r:
        return json.loads(r.read())


def snapshot(under: str) -> pd.DataFrame:
    """Live quotes in the same layout as the EOH archive used by the research scripts."""
    info = pd.DataFrame(get(f"{EAPI}/exchangeInfo")["optionSymbols"])
    info = info[info["underlying"] == under]
    tick = pd.DataFrame(get(f"{EAPI}/ticker"))
    d = info.merge(tick[["symbol", "bidPrice", "askPrice"]], on="symbol", how="inner")
    now = pd.Timestamp.now(tz="UTC").floor("min")
    S = float(get(f"{SPOT_API}/ticker/price?symbol={under}")["price"])
    d = pd.DataFrame({
        "symbol": d["symbol"], "ts": now, "S": S,
        "type": d["side"].map({"CALL": "C", "PUT": "P"}),
        "K": d["strikePrice"].astype(float),
        "expiry": pd.to_datetime(d["expiryDate"].astype("int64"), unit="ms", utc=True),
        "best_bid_price": d["bidPrice"].astype(float), "best_ask_price": d["askPrice"].astype(float),
        "best_bid_qty": 1.0, "best_ask_qty": 1.0,          # unknown from the ticker
    })
    d["tau_y"] = (d["expiry"] - now).dt.total_seconds() / (365 * 86400)
    return d[d["tau_y"] > 1 / 365]


def quarterly_futures(coin: str, expiries) -> pd.DataFrame:
    book = {b["symbol"]: b for b in get(f"{FAPI}/ticker/bookTicker")}
    rows = []
    for e in sorted(set(expiries)):
        b = book.get(f"{coin}USDT_{e:%y%m%d}")
        if b:
            rows.append(dict(expiry=e, F_bid=float(b["bidPrice"]), F_ask=float(b["askPrice"])))
    return pd.DataFrame(rows)


def synth_live(d: pd.DataFrame, fut: pd.DataFrame) -> pd.DataFrame:
    if fut.empty:
        return pd.DataFrame()
    d = oa2._book(d)
    c = d[d["type"] == "C"].set_index(["expiry", "K"])
    p = d[d["type"] == "P"].set_index(["expiry", "K"])
    j = c.join(p, lsuffix="_c", rsuffix="_p", how="inner").reset_index().merge(fut, on="expiry")
    S, K = j["S_c"], j["K"]
    F = (j["F_bid"] + j["F_ask"]) / 2
    fee = oa2.opt_fee(S, j["bid_c"].fillna(0)) + oa2.opt_fee(S, j["ask_p"].fillna(0)) + oa2.F_EX * S + 2 * oa2.F_FUT * F
    out = [
        pd.DataFrame(dict(check="B sell synth + long fut", expiry=j["expiry"], legs=K.map(lambda k: f"K{k:.0f}"),
                          edge=K + j["bid_c"] - j["ask_p"] - j["F_ask"] - fee, S=S)),
        pd.DataFrame(dict(check="B buy synth + short fut", expiry=j["expiry"], legs=K.map(lambda k: f"K{k:.0f}"),
                          edge=j["F_bid"] - (K + j["ask_c"] - j["bid_p"]) - fee, S=S)),
    ]
    return pd.concat(out)


def scan(under: str) -> pd.DataFrame:
    coin = under.removesuffix("USDT")
    d = snapshot(under)
    hits = pd.concat([oa2.static_bounds(d), oa2.calendars(d),
                      synth_live(d, quarterly_futures(coin, d["expiry"]))], ignore_index=True)
    hits = hits[hits["edge"] > 0].copy()
    hits["coin"] = coin
    hits["edge_bp"] = hits["edge"] / hits["S"] * 1e4
    return hits.sort_values("edge", ascending=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--underlyings", nargs="+", default=["BTCUSDT", "ETHUSDT"])
    ap.add_argument("--loop", type=int, default=0, help="seconds between scans (0 = once)")
    ap.add_argument("--log", default="user_data/option_arb_log.csv")
    a = ap.parse_args()
    while True:
        for u in a.underlyings:
            try:
                h = scan(u)
            except Exception as e:  # noqa: BLE001
                print(f"{u}: scan failed: {e}")
                continue
            stamp = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M")
            print(f"{stamp} {u}: {len(h)} violations after fees")
            if not h.empty:
                print(h[["check", "expiry", "legs", "edge", "edge_bp"]].head(15).to_string(index=False))
                h.assign(scan=stamp).to_csv(a.log, mode="a", index=False, header=not Path(a.log).exists())
        if not a.loop:
            break
        time.sleep(a.loop)


if __name__ == "__main__":
    main()
