#!/usr/bin/env python3
"""
Daily scanner for the coin-margined quarterly cash-and-carry (docs/ARBITRAGE_RESEARCH.md).

For every Binance COIN-M quarterly delivery contract it computes the EXECUTABLE locked yield
    y = (future_bid / spot_ask - 1) * 365 / days_to_delivery
net of the round-trip cost spread over the remaining life, ranks the contracts, and turns the
best ones into an order plan for your capital (number of contracts, spot to buy).

Rules (same as the backtest): enter if net yield >= 5 % and 14 <= days <= 200, at most one
position per coin, `--slots` equal positions; close an open position early when its remaining
annualised basis falls below 2 % (pass your open positions with --open BTCUSD_251226 ...).

Live mode uses only PUBLIC Binance endpoints (no API key):
    python scripts/basis_scanner.py --capital-twd 1000000 --usdtwd 32.0
Offline check against the downloaded archive (no network):
    python scripts/basis_scanner.py --offline-date 2025-03-28 --capital-usdt 31000

Nothing here places orders.  Always double-check prices in the exchange UI before trading.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd

DAPI = "https://dapi.binance.com/dapi/v1"
SPOT_API = "https://api.binance.com/api/v3"
ROUND_TRIP = {"BTC": 0.003, "ETH": 0.003}      # spot 0.1 % x2 + futures 0.05 % x2
ROUND_TRIP_ALT = 0.006                         # thinner contracts: extra slippage assumed
ENTER, EXIT, MIN_DAYS, MAX_DAYS = 0.05, 0.02, 14, 200


def get(url: str):
    with urlopen(Request(url, headers={"User-Agent": "basis-scanner"}), timeout=20) as r:
        return json.loads(r.read())


def live_quotes() -> pd.DataFrame:
    info = get(f"{DAPI}/exchangeInfo")["symbols"]
    book = {b["symbol"]: b for b in get(f"{DAPI}/ticker/bookTicker")}
    vol = {t["symbol"]: t for t in get(f"{DAPI}/ticker/24hr")}
    spot_book = {b["symbol"]: b for b in get(f"{SPOT_API}/ticker/bookTicker")}
    now = pd.Timestamp.now(tz="UTC")
    rows = []
    for s in info:
        if s.get("contractType") not in ("CURRENT_QUARTER", "NEXT_QUARTER") or s.get("contractStatus") != "TRADING":
            continue
        base = s["baseAsset"]
        sb = spot_book.get(f"{base}USDT")
        fb = book.get(s["symbol"])
        if not sb or not fb:
            continue
        delivery = pd.Timestamp(int(s["deliveryDate"]), unit="ms", tz="UTC")
        cs = float(s.get("contractSize", 100 if base == "BTC" else 10))
        v = vol.get(s["symbol"], {})
        rows.append(dict(symbol=s["symbol"], base=base, days=(delivery - now).total_seconds() / 86400,
                         fut_bid=float(fb["bidPrice"]), fut_ask=float(fb["askPrice"]),
                         spot_bid=float(sb["bidPrice"]), spot_ask=float(sb["askPrice"]),
                         contract_usd=cs, vol_usd_24h=float(v.get("volume", 0)) * cs))
    return pd.DataFrame(rows)


def offline_quotes(day: str) -> pd.DataFrame:
    """Same table from the downloaded daily archive (closes used as both bid and ask)."""
    d = pd.Timestamp(day, tz="UTC")
    rows = []
    for f in sorted(Path("user_data/data/binance/delivery/cm").glob("*-1d.feather")):
        sym = f.name.split("-")[0]
        base = sym.split("USD_")[0]
        exp = pd.Timestamp("20" + sym.split("_")[1], tz="UTC") + pd.Timedelta(hours=8)
        fut = pd.read_feather(f).set_index("date")
        spot_f = Path(f"user_data/data/binance/{base}_USDT-1d.feather")
        if d not in fut.index or not spot_f.exists():
            continue
        spot = pd.read_feather(spot_f).set_index("date")["close"]
        if d not in spot.index:
            continue
        F, S = float(fut.at[d, "close"]), float(spot.at[d])
        cs = 100.0 if base == "BTC" else 10.0
        rows.append(dict(symbol=sym, base=base, days=(exp - d).total_seconds() / 86400, fut_bid=F, fut_ask=F,
                         spot_bid=S, spot_ask=S, contract_usd=cs, vol_usd_24h=float(fut.at[d, "volume"]) * cs))
    return pd.DataFrame(rows)


def plan(q: pd.DataFrame, capital_usdt: float, slots: int, open_pos: list[str]) -> None:
    q = q.copy()
    q["cost"] = q["base"].map(ROUND_TRIP).fillna(ROUND_TRIP_ALT)
    q["locked_y"] = (q["fut_bid"] / q["spot_ask"] - 1) * 365 / q["days"]
    q["net_y"] = q["locked_y"] - q["cost"] * 365 / q["days"]
    q["remaining_y"] = (q["fut_ask"] / q["spot_bid"] - 1) * 365 / q["days"]   # to close: buy future, sell spot
    pd.set_option("display.width", 200)
    q = q[q["days"] >= 1]                      # contracts delivering today: annualised numbers are meaningless
    show = q.sort_values("net_y", ascending=False)
    print(show[["symbol", "days", "spot_ask", "fut_bid", "locked_y", "net_y", "vol_usd_24h"]]
          .assign(locked_y=lambda x: (x.locked_y * 100).round(2), net_y=lambda x: (x.net_y * 100).round(2),
                  days=lambda x: x.days.round(1), vol_usd_24h=lambda x: x.vol_usd_24h.round(0))
          .to_string(index=False))

    print("\n=== open positions")
    held_bases = set()
    for sym in open_pos:
        r = q[q["symbol"] == sym]
        if r.empty:
            print(f"  {sym}: not quoted (expired / settled?)")
            continue
        r = r.iloc[0]
        held_bases.add(r["base"])
        act = "CLOSE early (basis converged)" if r["remaining_y"] < EXIT and r["days"] > 3 else "hold to delivery"
        print(f"  {sym}: remaining annualised {r['remaining_y']*100:.2f}%  -> {act}")

    free = slots - len(open_pos)
    per_pos = capital_usdt / slots
    cands = show[(show["net_y"] >= ENTER) & show["days"].between(MIN_DAYS, MAX_DAYS)
                 & ~show["base"].isin(held_bases)].drop_duplicates("base")
    print(f"\n=== new entries (free slots: {free}, {per_pos:,.0f} USDT per position)")
    if free <= 0 or cands.empty:
        print("  none - keep idle capital in stablecoin savings / coin-margined funding carry")
        return
    for _, r in cands.head(free).iterrows():
        n = int(per_pos // r["contract_usd"])
        notional = n * r["contract_usd"]
        coins = notional / r["spot_ask"]
        print(f"  {r['symbol']}: net locked {r['net_y']*100:.2f}% p.a. for {r['days']:.0f} days | "
              f"buy {coins:.6f} {r['base']} spot (~{notional:,.0f} USDT), move it to the COIN-M wallet, "
              f"SHORT {n} x {r['symbol']} (contract {r['contract_usd']:.0f} USD)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital-twd", type=float, default=None)
    ap.add_argument("--usdtwd", type=float, default=32.0, help="TWD per USDT")
    ap.add_argument("--capital-usdt", type=float, default=None)
    ap.add_argument("--slots", type=int, default=10)
    ap.add_argument("--open", nargs="*", default=[], help="symbols you currently hold, e.g. BTCUSD_251226")
    ap.add_argument("--offline-date", default=None)
    a = ap.parse_args()
    capital = a.capital_usdt or (a.capital_twd / a.usdtwd if a.capital_twd else 31_000)
    q = offline_quotes(a.offline_date) if a.offline_date else live_quotes()
    if q.empty:
        raise SystemExit("no quotes")
    print(f"capital {capital:,.0f} USDT, {a.slots} slots\n")
    plan(q, capital, a.slots, a.open)


if __name__ == "__main__":
    main()
