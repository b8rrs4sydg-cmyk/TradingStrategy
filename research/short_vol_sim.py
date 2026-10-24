#!/usr/bin/env python3
"""
Delta-hedged short ATM straddle simulation (volatility risk premium harvesting).

* every `tenor` days at 08:00 UTC sell one ATM straddle (strike = spot) at the BID
  implied vol  = ratio_bid(tenor) * BVOL   (ratios calibrated on real Binance option
  quotes, research/option_arb.py data, 2023-05..10)
* hedge delta every 24h with the perpetual (0.05 % fee per hedge trade)
* marked to market daily at ratio_mark * BVOL; settled at intrinsic value at expiry
* option fees: 0.03 % of notional per leg at entry, 0.015 % exercise on the ITM leg
* size: `notional` (x capital) of underlying sold per straddle; collateral in USDT

Data: BVOL (BTC, ETH) 2023-06-20 .. 2024-11-05, spot 1h.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import bs  # noqa: E402

RATIO_BID = {("BTC", 7): 0.760, ("BTC", 14): 0.778, ("BTC", 30): 0.822,
             ("ETH", 7): 0.745, ("ETH", 14): 0.752, ("ETH", 30): 0.761}
MARK_OVER_BID = 1.02          # mark IV ~ 0.6-0.8 vol pts above bid IV (calibrated)


def load(coin):
    b = pd.read_feather(f"user_data/data/binance/options/{coin}BVOLUSDT-BVOL.feather")
    b["ts"] = pd.to_datetime(b["calc_time"], unit="ms", utc=True)
    iv = b.set_index("ts")["index_value"].astype(float).resample("h").last().ffill() / 100
    px = pd.read_feather(f"user_data/data/binance/{coin}_USDT-1h.feather").set_index("date")["close"]
    df = pd.concat([px.rename("S"), iv.rename("bvol")], axis=1, join="inner").dropna()
    return df


def simulate(coin, tenor=7, notional=1.0, ratio_shift=0.0):
    df = load(coin)
    daily = df[df.index.hour == 8]
    rb = RATIO_BID[(coin, tenor)] + ratio_shift
    equity, pos, curve, cycles = 1.0, None, [], []
    for ts, row in daily.iterrows():
        S, bvol = row.S, row.bvol
        if pos is not None:
            T = max((pos["exp"] - ts).total_seconds() / (365 * 86400), 0.0)
            # hedge P&L since last rebalance
            equity += pos["hedge"] * (S - pos["S_last"])
            if T <= 1e-9:
                payoff = abs(S - pos["K"]) * pos["n"]
                equity -= payoff + 0.00015 * S * pos["n"]
                cycles.append(equity / pos["eq0"] - 1)
                pos = None
            else:
                pos["S_last"] = S
                sig = rb * bvol * MARK_OVER_BID
                d_tot = (bs.delta(S, pos["K"], T, sig, True) + bs.delta(S, pos["K"], T, sig, False)) * -pos["n"]
                trade = -d_tot - pos["hedge"]
                equity -= abs(trade) * S * 0.0005
                pos["hedge"] = -d_tot
                opt_val = (bs.price(S, pos["K"], T, sig, True) + bs.price(S, pos["K"], T, sig, False)) * pos["n"]
                curve.append((ts, equity - opt_val))
                continue
        if pos is None:
            K, T = S, tenor / 365
            sig_bid = rb * bvol
            n = notional * equity / S
            prem = (bs.price(S, K, T, sig_bid, True) + bs.price(S, K, T, sig_bid, False)) * n
            equity += prem - 2 * 0.0003 * S * n
            d_tot = (bs.delta(S, K, T, sig_bid, True) + bs.delta(S, K, T, sig_bid, False)) * -n
            equity -= abs(d_tot) * S * 0.0005
            pos = dict(K=K, n=n, exp=ts + pd.Timedelta(days=tenor), hedge=-d_tot, S_last=S, eq0=equity - prem)
            opt_val = prem
            curve.append((ts, equity - opt_val))
    eq = pd.Series(dict(curve))
    r = eq.resample("D").last().pct_change().dropna()
    yrs = len(r) / 365
    out = dict(coin=coin, tenor=tenor, notional=notional, ratio_shift=ratio_shift,
               cagr=round(((eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1) * 100, 1),
               mdd=round(float((1 - eq / eq.cummax()).max()) * 100, 1),
               sharpe=round(r.mean() / r.std() * np.sqrt(365), 2),
               cycles=len(cycles), win=round(float(np.mean(np.array(cycles) > 0)) * 100, 0),
               worst_cycle=round(min(cycles) * 100, 1))
    return out, eq


def main():
    rows = []
    for coin in ("BTC", "ETH"):
        for tenor in (7, 14, 30):
            for shift in (0.0, 0.05):
                rows.append(simulate(coin, tenor, 1.0, shift)[0])
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
