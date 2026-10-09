#!/usr/bin/env python3
"""
Basis lab: cash-and-carry arbitrage with quarterly DELIVERY futures.

Position: long spot + short delivery future of the same underlying, equal notional.
At entry the annualised yield is LOCKED:   y = (F/S - 1) * 365 / days_to_expiry
At expiry the future settles to the index, so the position earns the entry basis
(minus costs) regardless of price moves; in between it is marked to market.

Capital per unit of notional
  * coin-margined (cm) contracts: the spot coins ARE the margin  -> 1.0
  * USDT-margined (um) contracts: spot + separate USDT margin      -> 2.0 (1x)

Rotation: every day all (underlying, contract) pairs are ranked by locked
annualised yield; free slots are filled with the best ones above a threshold.
Optional early roll: close a position when its REMAINING annualised yield falls
below `exit_yield` (basis converged early) and redeploy the capital.

    python research/basis_lab.py --start 2020-09-01 --end 2023-12-31
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

DEL = Path("user_data/data/binance/delivery")
SPOT = Path("user_data/data/binance")
COST_RT = 0.003          # round trip, 4 legs (spot 0.1% x2 + futures 0.05% x2), on notional


def load_contracts():
    rows = []
    for market in ("um", "cm"):
        for f in sorted((DEL / market).glob("*-1d.feather")):
            sym = f.name.split("-")[0]                     # e.g. BTCUSDT_240329 / ETHUSD_230630
            under, code = sym.split("_")
            base = under.removesuffix("USDT").removesuffix("USD").removesuffix("BUSD")
            if under.endswith("BUSD"):
                continue
            spot_f = SPOT / f"{base}_USDT-1d.feather"
            if not spot_f.exists():
                continue
            fut = pd.read_feather(f).set_index("date")["close"]
            fut.index = fut.index.normalize()
            spot = pd.read_feather(spot_f).set_index("date")["close"]
            spot.index = spot.index.normalize()
            expiry = pd.Timestamp("20" + code, tz="UTC")
            df = pd.concat([fut.rename("F"), spot.rename("S")], axis=1, join="inner").dropna()
            df = df[df.index < expiry]
            if len(df) < 10:
                continue
            # settlement: delivery contracts settle at 08:00 UTC on the expiry day to the index;
            # use the spot price at 08:00 (1h data) and let F converge to it
            s1h = SPOT / f"{base}_USDT-1h.feather"
            if s1h.exists():
                h = pd.read_feather(s1h).set_index("date")["close"]
                at8 = h.get(expiry + pd.Timedelta(hours=7))      # 07:00 candle closes at 08:00
                if at8 is not None and np.isfinite(at8):
                    df.loc[expiry] = [at8, at8]
            df = df.sort_index()
            df["tau"] = (expiry - df.index).days
            rows.append(dict(sym=sym, market=market, base=base, expiry=expiry, data=df))
    return rows


def backtest(contracts, start, end, slots=10, enter_yield=0.10, exit_yield=None,
             min_tau=14, max_tau=200, cm_only=False, cost=COST_RT, bases=None, um_only=False):
    days = pd.date_range(start, end, freq="D", tz="UTC")
    book = {}        # sym -> dict(entry_S, entry_F, weight(capital fraction), market, expiry)
    equity = 1.0
    eq_curve, trades = [], []
    cs = {c["sym"]: c for c in contracts
          if not (cm_only and c["market"] != "cm") and not (um_only and c["market"] != "um")
          and (bases is None or c["base"] in bases)}
    for d in days:
        # 1) mark to market and settle expiries
        pnl_day = 0.0
        for sym in list(book):
            pos = book[sym]
            df = cs[sym]["data"]
            if d not in df.index:
                continue
            S, F = df.at[d, "S"], df.at[d, "F"]
            cap_mult = 1.0 if pos["market"] == "cm" else 2.0
            ret = (S / pos["S0"] - 1) - (F / pos["F0"] - 1)          # on notional
            val = pos["cap"] * (1 + ret / cap_mult)
            pnl_day += val - pos["val"]
            pos["val"] = val
            tau = df.at[d, "tau"]
            remaining = (F / S - 1) * 365 / max(tau, 1)
            if tau <= 0 or (exit_yield is not None and tau > 3 and remaining < exit_yield):
                exit_cost = pos["cap"] * cost / 2 / cap_mult if tau > 0 else pos["cap"] * cost / 4 / cap_mult
                pnl_day -= exit_cost
                trades.append(dict(sym=sym, entry=pos["d0"], exit=d, locked=pos["y0"],
                                   ret=(val - exit_cost) / pos["cap0"] - 1, early=tau > 0))
                del book[sym]
        equity += pnl_day
        # 2) fill free slots with the best locked yields
        free = slots - len(book)
        if free > 0:
            cands = []
            for sym, c in cs.items():
                if sym in book or sum(cs[s]["base"] == c["base"] for s in book) >= max(1, slots // max(1, len({x["base"] for x in cs.values()}))):
                    continue
                df = c["data"]
                if d not in df.index:
                    continue
                tau = df.at[d, "tau"]
                if not (min_tau <= tau <= max_tau):
                    continue
                y = (df.at[d, "F"] / df.at[d, "S"] - 1) * 365 / tau
                # net of round-trip cost spread over the holding period
                y_net = y - cost * 365 / tau
                if y_net >= enter_yield:
                    cands.append((y_net, sym))
            for y_net, sym in sorted(cands, reverse=True)[:free]:
                c = cs[sym]
                df = c["data"]
                cap = equity / slots
                cap_mult = 1.0 if c["market"] == "cm" else 2.0
                entry_cost = cap * cost / 2 / cap_mult
                equity -= entry_cost
                book[sym] = dict(S0=df.at[d, "S"], F0=df.at[d, "F"], cap=cap, cap0=cap + entry_cost,
                                 val=cap, market=c["market"], d0=d, y0=y_net)
        eq_curve.append((d, equity))
    eq = pd.Series(dict(eq_curve))
    return eq, pd.DataFrame(trades)


def stats(eq: pd.Series, trades: pd.DataFrame):
    r = eq.pct_change().dropna()
    yrs = len(r) / 365
    by = eq.resample("YE").last()
    yr = by.pct_change()
    yr.iloc[0] = by.iloc[0] / eq.iloc[0] - 1
    m = eq.resample("ME").last().pct_change().dropna()
    return dict(cagr=round((eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) * 100 - 100, 1),
                mdd=round(float((1 - eq / eq.cummax()).max()) * 100, 2),
                sharpe=round(r.mean() / r.std() * np.sqrt(365), 2) if r.std() > 0 else None,
                pos_months=round(float((m > 0).mean()) * 100, 0),
                trades=len(trades), win=round(float((trades["ret"] > 0).mean()) * 100, 1) if len(trades) else None,
                years={k.year: round(v * 100, 1) for k, v in yr.items()})


def basis_overview(contracts):
    rows = []
    for c in contracts:
        df = c["data"]
        y = (df["F"] / df["S"] - 1) * 365 / df["tau"].clip(lower=1)
        y = y[df["tau"].between(14, 200)]
        for dt, v in y.items():
            rows.append((dt.year, c["market"], c["base"], v))
    d = pd.DataFrame(rows, columns=["year", "market", "base", "y"])
    print("median locked annualised basis (contracts 14-200 days to expiry):")
    print(d.pivot_table(index="year", columns="market", values="y", aggfunc="median").mul(100).round(1))
    print(d.groupby("year")["y"].quantile(0.9).mul(100).round(1).rename("p90 all"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2020-09-01")
    ap.add_argument("--end", default="2023-12-31")
    a = ap.parse_args()
    contracts = load_contracts()
    print(f"{len(contracts)} contracts loaded")
    basis_overview(contracts)
    for ey in (0.05, 0.08, 0.10, 0.15, 0.20):
        for ex in (None, 0.02):
            for cm_only in (False, True):
                eq, tr = backtest(contracts, a.start, a.end, enter_yield=ey, exit_yield=ex, cm_only=cm_only)
                print(f"enter>={ey:.2f} exit={ex} cm_only={cm_only}:", stats(eq, tr))


if __name__ == "__main__":
    main()
