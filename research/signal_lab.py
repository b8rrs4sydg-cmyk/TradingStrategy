#!/usr/bin/env python3
"""
Signal lab: fast, vectorised evaluation of entry-signal families.

For every entry signal we simulate a single isolated trade with
take-profit / stop-loss / time-stop (first touch on 1h high/low, stop assumed
first when both are touched in the same candle -> conservative) and report
win-rate, average net return and profit factor.

This is *idea generation* on the in-sample period only.  The final strategy is
then validated with Freqtrade on data it has never seen.

    python research/signal_lab.py --start 2020-06-01 --end 2024-01-01
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import talib

DATA = Path("user_data/data/binance")
FEE = 0.002  # round trip


def load(pairs, tf="1h"):
    out = {}
    for p in pairs:
        f = DATA / f"{p.replace('/', '_')}-{tf}.feather"
        if f.exists():
            out[p] = pd.read_feather(f).set_index("date")
    return out


def panel(dfs, col):
    return pd.DataFrame({p: d[col] for p, d in dfs.items()}).sort_index()


def simulate(entries, o, h, l, c, tp, sl, max_h):
    """entries: bool DataFrame; enter at next candle open."""
    res = []
    O, H, L, C = o.values, h.values, l.values, c.values
    E = entries.values
    n = len(o)
    for j in range(E.shape[1]):
        idx = np.flatnonzero(E[:, j])
        last_exit = -1
        for i in idx:
            if i + 1 >= n or i + 1 <= last_exit:
                continue
            ep = O[i + 1, j]
            if not np.isfinite(ep):
                continue
            up, dn = ep * (1 + tp), ep * (1 - sl)
            end = min(n - 1, i + max_h)
            r = None
            for k in range(i + 1, end + 1):
                if L[k, j] <= dn:
                    r, ex = -sl, k
                    break
                if H[k, j] >= up:
                    r, ex = tp, k
                    break
            if r is None:
                ex = end
                r = C[end, j] / ep - 1
            res.append((o.index[i], o.columns[j], r - FEE))
            last_exit = ex
    return pd.DataFrame(res, columns=["date", "pair", "ret"])


def stats(t):
    if t.empty:
        return dict(n=0)
    r = t["ret"]
    pf = r[r > 0].sum() / max(1e-9, -r[r < 0].sum())
    return dict(n=len(r), win=round((r > 0).mean(), 3), avg=round(r.mean() * 100, 3),
                pf=round(pf, 2), worst=round(r.min() * 100, 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2020-06-01")
    ap.add_argument("--end", default="2024-01-01")
    ap.add_argument("--tf", default="1h")
    a = ap.parse_args()
    cph = {"1h": 24, "4h": 6}[a.tf]  # candles per day

    pairs = json.load(open("configs/pairs_universe.json"))
    dfs = load(pairs, a.tf)
    o, h, l, c = (panel(dfs, k) for k in ("open", "high", "low", "close"))

    # --- cross-sectional features
    W = cph * 20
    lr = np.log(c).diff()
    score = np.log(c / c.shift(W)) / (lr.rolling(W).std() * np.sqrt(W))
    rank = score.rank(axis=1, ascending=False)
    breadth = (score > 0).sum(axis=1) / score.notna().sum(axis=1)

    btc_d = load(["BTC/USDT"], "1d")["BTC/USDT"]
    bull = (btc_d["close"] > btc_d["close"].rolling(50).mean()).astype(float)
    bull.index = bull.index + pd.Timedelta(days=1)
    bull = bull.reindex(c.index, method="ffill")
    regime = (bull == 1) & (breadth >= 0.5)
    reg = pd.DataFrame(np.repeat(regime.values[:, None], c.shape[1], 1), index=c.index, columns=c.columns)

    rsi = c.apply(lambda s: pd.Series(talib.RSI(s.values, 14), index=s.index))
    sma20 = c.rolling(20).mean()
    std20 = c.rolling(20).std()
    bbl = sma20 - 2 * std20
    ema50 = c.ewm(span=50, adjust=False).mean()
    ema200 = c.ewm(span=200, adjust=False).mean()
    hh = h.rolling(W).max().shift(1)
    top = (rank <= 10) & (score > 0)

    fam = {
        "baseline_every_6th_bar_top_regime": top & reg & pd.DataFrame(
            np.repeat((np.arange(len(c)) % 6 == 0)[:, None], c.shape[1], 1), index=c.index, columns=c.columns),
        "pullback_rsi30_bb": top & reg & (rsi < 30) & (c < bbl),
        "pullback_rsi35_above_ema200": top & reg & (rsi < 35) & (c > ema200),
        "dip_to_ema50_in_trend": top & reg & (l < ema50) & (c > ema50) & (ema50 > ema200),
        "breakout_20d_high": top & reg & (c > hh),
        "pullback_no_regime": top & (rsi < 30) & (c < bbl),
        "pullback_any_coin_regime": reg & (rsi < 30) & (c < bbl),
    }
    sel = (c.index >= a.start) & (c.index < a.end)
    d = cph  # candles per day
    exits = [(0.03, 0.06, 2 * d), (0.05, 0.10, 4 * d), (0.08, 0.12, 7 * d), (0.10, 0.10, 10 * d), (0.06, 0.15, 10 * d)]
    rows = []
    for name, sig in fam.items():
        sig = sig.fillna(False) & pd.DataFrame(np.repeat(sel[:, None], c.shape[1], 1), index=c.index, columns=c.columns)
        for tp, sl, mh in exits:
            t = simulate(sig, o, h, l, c, tp, sl, mh)
            rows.append(dict(signal=name, tp=tp, sl=sl, max_h=mh, **stats(t)))
            print(rows[-1], flush=True)
    pd.DataFrame(rows).to_csv(f"research/signal_lab_results_{a.tf}.csv", index=False)


if __name__ == "__main__":
    main()
