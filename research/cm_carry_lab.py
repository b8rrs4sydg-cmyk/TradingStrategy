#!/usr/bin/env python3
"""
Coin-margined vs USDT-margined funding carry (same FundingCarry rules, same coins, same period).

USDT-margined (UM): long spot + short USDT perp; capital = 2 x notional (spot + 1x margin)
Coin-margined (CM): long spot coins posted as margin + short COIN-margined (inverse) perp of
                    the same USD value; capital = 1 x notional. An inverse short hedged with
                    the coin itself is exactly USD-neutral and cannot be liquidated by price moves.

Rules (identical to FundingCarry): enter when trailing-72h average funding >= 0.02 %/8h, rank by
it (10 slots), exit when trailing-72h funding < 0.  Round trip cost 0.3 % of notional.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from carry_lab import hysteresis_backtest  # noqa: E402

CM = Path("user_data/data/binance/cm_perp")
SPOT = Path("user_data/data/binance")
FUT = SPOT / "futures"


def panel(kind: str, start: str, end: str):
    R, F = {}, {}
    for f in sorted(CM.glob("*USD_PERP-funding.feather")):
        coin = f.name.split("USD_PERP")[0]
        s = SPOT / f"{coin}_USDT-1h.feather"
        if not s.exists():
            continue
        spot = pd.read_feather(s).set_index("date")["close"]
        if kind == "cm":
            pk = pd.read_feather(CM / f"{coin}USD_PERP-1h.feather").set_index("date")
            j = pk.join(spot.rename("spot"), how="inner").loc[start:end]
            bad = (j["volume"] <= 0) | ((j["close"] / j["spot"] - 1).abs() > 0.02)
            if bad.mean() > 0.05:          # dead / illiquid contract (stale prices) -> not tradable
                continue
            perp = pk["close"].where(~bad.reindex(pk.index, fill_value=False))   # untradable hours -> NaN
            fund = pd.read_feather(f).set_index("date")["rate"]
        else:
            uf = FUT / f"{coin}_USDT_USDT-1h-futures.feather"
            ur = FUT / f"{coin}_USDT_USDT-1h-funding_rate.feather"
            if not (uf.exists() and ur.exists()):
                continue
            perp = pd.read_feather(uf).set_index("date")["close"]
            fund = pd.read_feather(ur).set_index("date")["close"]
        fund = fund[~fund.index.duplicated()]
        df = pd.concat([spot.rename("s"), perp.rename("p")], axis=1, join="inner").loc[start:end]
        if len(df) < 24 * 60:
            continue
        df["f"] = fund.reindex(df.index + pd.Timedelta(hours=1)).fillna(0.0).values   # earned by holders across T
        df["p"] = df["p"].ffill()
        R[coin] = df["s"].pct_change() - df["p"].pct_change() + df["f"]
        F[coin] = fund.reindex(df.index).fillna(0.0)
    return pd.DataFrame(R).fillna(0.0), pd.DataFrame(F).fillna(0.0)


def stats(port: pd.Series, trades):
    eq = (1 + port).cumprod()
    d = eq.resample("D").last()
    r = d.pct_change().dropna()
    yrs = len(r) / 365
    yr = d.resample("YE").last()
    yrr = yr.pct_change()
    yrr.iloc[0] = yr.iloc[0] - 1
    return dict(cagr=round((d.iloc[-1] ** (1 / yrs) - 1) * 100, 1), mdd=round(float((1 - d / d.cummax()).max()) * 100, 2),
                sharpe=round(r.mean() / r.std() * np.sqrt(365), 2), trades=len(trades),
                win=round(float(np.mean(trades > 0)) * 100, 1), pos_months=round(float((d.resample("ME").last().pct_change().dropna() > 0).mean()) * 100, 0),
                years={k.year: round(v * 100, 1) for k, v in yrr.items()})


def main(start="2022-08-01", end="2026-09-30"):
    common = None
    res = {}
    for kind in ("um", "cm"):
        R, F = panel(kind, start, end)
        res[kind] = (R, F)
        common = set(R.columns) if common is None else common & set(R.columns)
    common = sorted(common)
    print(f"{len(common)} coins available in both, {start}..{end}")
    for kind, capital in (("um", 2.0), ("cm", 1.0)):
        R, F = res[kind]
        port, trades = hysteresis_backtest(R[common], F[common], slots=10, enter_rate=0.0002, lookback_h=72, cost=0.003)
        print(f"{kind.upper()} funding carry (capital = {capital:.0f}x notional):", stats(port / capital, trades / capital))


if __name__ == "__main__":
    main(*sys.argv[1:3])
