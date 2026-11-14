#!/usr/bin/env python3
"""
Volatility risk premium (VRP) lab: Binance BVOL index (30-day implied vol, 2023-06 .. 2024-11)
versus the realised volatility of the next 30 days (from 1h spot returns).

A delta-hedged short 30-day option position earns approximately the variance-swap payoff
    P&L (per unit vega notional) ~ (IV^2 - RV^2) / (2 * IV)
i.e. it wins when realised vol ends up below implied vol, and loses in volatility spikes.
"""
import numpy as np
import pandas as pd

for coin, sym in (("BTC", "BTCBVOLUSDT"), ("ETH", "ETHBVOLUSDT")):
    b = pd.read_feather(f"user_data/data/binance/options/{sym}-BVOL.feather")
    b["ts"] = pd.to_datetime(b["calc_time"], unit="ms", utc=True)
    iv = b.set_index("ts")["index_value"].astype(float).resample("D").last() / 100
    px = pd.read_feather(f"user_data/data/binance/{coin}_USDT-1h.feather").set_index("date")["close"]
    r = np.log(px).diff()
    rv_fwd = r.rolling(24 * 30).std().shift(-24 * 30) * np.sqrt(24 * 365)
    rv_fwd = rv_fwd.resample("D").first().reindex(iv.index)
    rv_past = (r.rolling(24 * 30).std() * np.sqrt(24 * 365)).resample("D").last().reindex(iv.index)
    d = pd.DataFrame({"iv": iv, "rv_fwd": rv_fwd, "rv_past": rv_past}).dropna()
    vrp = d.iv - d.rv_fwd
    pnl = (d.iv ** 2 - d.rv_fwd ** 2) / (2 * d.iv)               # vega-notional units
    m = pnl.iloc[::30]                                             # non-overlapping monthly
    print(f"{coin}: {len(d)} days  IV mean {d.iv.mean()*100:.1f}%  fwd RV mean {d.rv_fwd.mean()*100:.1f}%  "
          f"VRP mean {vrp.mean()*100:.1f} vol pts, positive {np.mean(vrp>0)*100:.0f}% of days, "
          f"worst {vrp.min()*100:.1f} pts")
    print(f"   short-vol monthly (non-overlapping, n={len(m)}): win {np.mean(m>0)*100:.0f}%  "
          f"mean/std {m.mean()/m.std():.2f}  worst month {m.min()/m.abs().mean():.1f}x avg |P&L|")
    print("   VRP by quarter (vol pts):", (vrp.groupby(vrp.index.to_period('Q')).mean()*100).round(1).to_dict())
