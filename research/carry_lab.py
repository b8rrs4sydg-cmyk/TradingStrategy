#!/usr/bin/env python3
"""
Carry lab: economics of a delta-neutral funding-rate carry (long spot + short
USDT-M perpetual, equal notional) on Binance, per coin and per year.

Hourly carry return of one unit of notional:
    r_carry = r_spot - r_perp + funding      (funding paid to the short when > 0)
Capital needed per unit of notional = 1 (spot) + 1/LEV (perp margin)

    python research/carry_lab.py --pairs-file configs/pairs_universe.json --start 2020-06-01 --end 2024-01-01
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path("user_data/data/binance")


def load_pair(pair: str) -> pd.DataFrame | None:
    base, quote = pair.split(":")[0].split("/")
    fs = DATA / f"{base}_{quote}-1h.feather"
    ff = DATA / "futures" / f"{base}_{quote}_{quote}-1h-futures.feather"
    fr = DATA / "futures" / f"{base}_{quote}_{quote}-1h-funding_rate.feather"
    if not (fs.exists() and ff.exists() and fr.exists()):
        return None
    s = pd.read_feather(fs).set_index("date")["close"].rename("spot")
    f = pd.read_feather(ff).set_index("date")["close"].rename("perp")
    r = pd.read_feather(fr).set_index("date")["close"].rename("funding")
    r = r[~r.index.duplicated()]
    df = pd.concat([s, f], axis=1, join="inner").sort_index()
    df["funding"] = r.reindex(df.index).fillna(0.0)
    return df


def carry_returns(df: pd.DataFrame) -> pd.Series:
    return df["spot"].pct_change() - df["perp"].pct_change() + df["funding"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs-file", default="configs/pairs_universe.json")
    ap.add_argument("--start", default="2020-06-01")
    ap.add_argument("--end", default="2024-01-01")
    a = ap.parse_args()
    pairs = json.load(open(a.pairs_file))
    rows = {}
    fund = {}
    for p in pairs:
        df = load_pair(p)
        if df is None:
            continue
        df = df.loc[a.start:a.end]
        if len(df) < 24 * 30:
            continue
        rows[p] = carry_returns(df)
        fund[p] = df["funding"]
    R = pd.DataFrame(rows).fillna(0.0)
    F = pd.DataFrame(fund).fillna(0.0)
    # per-coin always-on carry (no selection), annualised on notional
    yr = R.groupby(R.index.year).sum()
    print("Always-on carry, sum of hourly returns on notional, per year (median / mean over coins):")
    print(pd.DataFrame({"median": yr.median(axis=1), "mean": yr.mean(axis=1),
                        "share_coins_positive": (yr > 0).mean(axis=1)}).round(3))
    # rotation: each day hold the top-N coins by trailing 3-day funding (only if > 0)
    trail = F.rolling(72).sum()
    for n in (5, 10):
        rank = trail.rank(axis=1, ascending=False)
        sel = ((rank <= n) & (trail > 0)).shift(1).fillna(False)
        sel = sel.astype(float)
        sel[sel.index.hour != 0] = np.nan
        sel = sel.ffill().fillna(0.0).astype(bool)  # rebalance daily
        w = sel.div(sel.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
        turnover = w.diff().abs().sum(axis=1)
        port = (w * R).sum(axis=1) - turnover * 0.002  # 4 legs x ~0.05-0.1% + slippage
        eq = (1 + port).cumprod()
        dd = (1 - eq / eq.cummax()).max()
        by_year = port.groupby(port.index.year).sum()
        pos_days = (port.resample("D").sum() > 0).mean()
        print(f"\nTop-{n} rotation (notional returns): total {eq.iloc[-1] - 1:.1%}, MDD {dd:.2%}, "
              f"positive days {pos_days:.1%}, invested {(w.sum(axis=1) > 0).mean():.0%} of time")
        print("  per year:", by_year.round(3).to_dict())


if __name__ == "__main__":
    main()


def hysteresis_backtest(R, F, slots=10, enter_rate=0.0001, lookback_h=72, cost=0.004):
    """Event-driven carry rotation on notional returns.

    enter: trailing average funding per 8h >= enter_rate; exit: trailing sum < 0.
    Each position uses 1/slots of capital (capital = notional, i.e. already hedged).
    cost: round-trip cost per position on notional (4 legs + slippage).
    Returns hourly portfolio return series and list of per-trade returns.
    """
    per8h = F.rolling(lookback_h).sum() / (lookback_h / 8)
    trail = F.rolling(lookback_h).sum()
    hold: dict[str, float] = {}
    port = np.zeros(len(R))
    trades = []
    Rv, Pv, Tv = R.to_numpy(), per8h.to_numpy(), trail.to_numpy()
    cols = list(R.columns)
    for i in range(1, len(R)):
        # accrue returns of open positions
        for c in list(hold):
            j = cols.index(c)
            port[i] += Rv[i, j] / slots
            hold[c] += Rv[i, j]
        # decisions on the previous closed hour (no lookahead)
        sig_p, sig_t = Pv[i - 1], Tv[i - 1]
        for c in list(hold):
            j = cols.index(c)
            if not sig_t[j] >= 0:
                trades.append(hold.pop(c) - cost)
                port[i] -= cost / 2 / slots
        free = slots - len(hold)
        if free > 0:
            cand = [(sig_p[j], cols[j]) for j in range(len(cols))
                    if cols[j] not in hold and sig_p[j] >= enter_rate]
            for _, c in sorted(cand, reverse=True)[:free]:
                hold[c] = 0.0
                port[i] -= cost / 2 / slots
    return pd.Series(port, index=R.index), np.array(trades)
