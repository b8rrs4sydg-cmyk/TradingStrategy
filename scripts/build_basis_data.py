#!/usr/bin/env python3
"""
Build synthetic quarterly-basis carry instruments for Freqtrade: <COIN>Q<rank>BASIS/USDT (1d).

The instrument is the equity of a COIN-MARGINED cash-and-carry position:
    long spot (posted as margin) + short the ACTIVE quarterly delivery future, capital = 1x notional
ACTIVE contract = the rank-th nearest quarterly (Q1 = nearest, Q2 = next) with >= `roll_days`
days to expiry; when it gets closer
than that, the position rolls into the next quarterly (roll cost: 2 futures legs).
Delivery settles at 08:00 UTC to the index; a contract still held at expiry converges to spot.

Side file  user_data/data/binance/basis/<COIN>Q<rank>-basis.feather  (one row per day, known at the close):
    locked_y   annualised basis of the active contract  (F/S - 1) * 365 / days_to_expiry
    tau        days to expiry of the active contract
The strategy reads it to decide entries (locked yield high) and exits (remaining yield low).

    python scripts/build_basis_data.py --coins BTC ETH
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

DEL = Path("user_data/data/binance/delivery/cm")
SPOT = Path("user_data/data/binance")
OUT_SIDE = SPOT / "basis"
FUT_FEE = 0.0005


def build(coin: str, roll_days: int = 14, rank: int = 1) -> str:
    spot = pd.read_feather(SPOT / f"{coin}_USDT-1d.feather").set_index("date")["close"]
    spot.index = spot.index.normalize()
    s1h = pd.read_feather(SPOT / f"{coin}_USDT-1h.feather").set_index("date")["close"]
    futs = {}
    for f in sorted(DEL.glob(f"{coin}USD_*-1d.feather")):
        code = f.name.split("_")[1].split("-")[0]
        exp = pd.Timestamp("20" + code, tz="UTC")
        fc = pd.read_feather(f).set_index("date")["close"]
        fc.index = fc.index.normalize()
        fc = fc[fc.index < exp]
        at8 = s1h.get(exp + pd.Timedelta(hours=7))
        if at8 is not None:
            fc.loc[exp] = at8                                  # settles to the index at 08:00
        futs[exp] = fc.sort_index()
    days = spot.index[(spot.index >= min(futs) - pd.Timedelta(days=200))]
    rows = []
    active = None
    eq = 100.0
    prev = None
    for d in days:
        S = spot.get(d)
        if S is None or not np.isfinite(S):
            continue
        # P&L of the position held since yesterday (1x capital: notional = equity)
        if active is not None and prev is not None:
            F_prev, S_prev = prev
            F_now = futs[active].get(d, np.nan)
            if np.isfinite(F_now):
                eq *= 1 + (S / S_prev - 1) - (F_now / F_prev - 1)
        # choose / roll the active contract
        cands = [e for e, fc in futs.items() if (e - d).days >= roll_days and d in fc.index]
        new = sorted(cands)[rank - 1] if len(cands) >= rank else None
        if new != active:
            if active is not None and new is not None:
                eq *= 1 - 2 * FUT_FEE                          # close old + open new future
            active = new
        if active is None:
            prev = None
            continue
        F = futs[active][d]
        tau = (active - d).days
        rows.append(dict(date=d, close=eq, locked_y=(F / S - 1) * 365 / tau, tau=tau, contract=active.strftime("%y%m%d")))
        prev = (F, S)
    df = pd.DataFrame(rows)
    out = pd.DataFrame({"date": df["date"], "open": df["close"].shift(1).fillna(df["close"].iloc[0]),
                        "close": df["close"], "volume": 1.0})
    out["high"] = out[["open", "close"]].max(axis=1)
    out["low"] = out[["open", "close"]].min(axis=1)
    out[["date", "open", "high", "low", "close", "volume"]].reset_index(drop=True).to_feather(
        SPOT / f"{coin}Q{rank}BASIS_USDT-1d.feather")
    OUT_SIDE.mkdir(exist_ok=True)
    df[["date", "locked_y", "tau", "contract"]].reset_index(drop=True).to_feather(OUT_SIDE / f"{coin}Q{rank}-basis.feather")
    return f"{coin}Q{rank}BASIS/USDT: {len(df)} days {df.date.iloc[0]:%Y-%m-%d} -> {df.date.iloc[-1]:%Y-%m-%d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", nargs="+", default=["BTC", "ETH"])
    ap.add_argument("--roll-days", type=int, default=14)
    ap.add_argument("--ranks", nargs="+", type=int, default=[1, 2],
                    help="1 = nearest quarterly, 2 = the next one after it")
    a = ap.parse_args()
    for c in a.coins:
        for r in a.ranks:
            print(build(c, a.roll_days, r))


if __name__ == "__main__":
    main()
