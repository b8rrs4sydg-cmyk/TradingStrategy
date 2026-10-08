#!/usr/bin/env python3
"""
Long/short lab: vectorised daily portfolio simulation of long/short strategy
families on Binance USDT-M perpetuals, net of trading costs and REAL funding.

Idea generation on the in-sample period only.  Positions are decided on the
close of day t and earn the return of day t+1 (no lookahead).

    python research/ls_lab.py --start 2020-06-01 --end 2024-01-01
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path("user_data/data/binance/futures")
COST = 0.001        # per unit of traded notional (taker 0.05% + slippage, conservative)


def load_universe(pairs_file: str):
    pairs = json.load(open(pairs_file))
    close, fund = {}, {}
    for p in pairs:
        base, quote = p.split(":")[0].split("/")
        f = DATA / f"{base}_{quote}_{quote}-1d-futures.feather"
        fr = DATA / f"{base}_{quote}_{quote}-1h-funding_rate.feather"
        if not f.exists():
            continue
        close[base] = pd.read_feather(f).set_index("date")["close"]
        if fr.exists():
            r = pd.read_feather(fr).set_index("date")["close"]
            fund[base] = r.groupby(r.index.floor("D")).sum()
    C = pd.DataFrame(close).sort_index()
    F = pd.DataFrame(fund).reindex(C.index).fillna(0.0)
    return C, F


def vol(R, n=60):
    return R.rolling(n, min_periods=n // 2).std() * np.sqrt(365)


# ---------------------------------------------------------------- signals
def sig_tsmom(C, R, lbs=(20, 60, 120)):
    """time-series momentum: average sign of returns over several look-backs"""
    return sum(np.sign(C / C.shift(lb) - 1) for lb in lbs) / len(lbs)


def sig_ema(C, R, fast=20, slow=100):
    ef, es = C.ewm(span=fast, adjust=False).mean(), C.ewm(span=slow, adjust=False).mean()
    return np.sign(ef - es)


def sig_donchian(C, R, entry=50, exit_=20):
    hi, lo = C.rolling(entry).max(), C.rolling(entry).min()
    xhi, xlo = C.rolling(exit_).max(), C.rolling(exit_).min()
    pos = pd.DataFrame(0.0, index=C.index, columns=C.columns)
    state = np.zeros(C.shape[1])
    Cv, H, L, XH, XL = C.values, hi.values, lo.values, xhi.values, xlo.values
    out = np.zeros_like(Cv)
    for i in range(len(C)):
        c = Cv[i]
        state = np.where(c >= H[i], 1, np.where(c <= L[i], -1, state))
        state = np.where((state == 1) & (c <= XL[i]), 0, state)
        state = np.where((state == -1) & (c >= XH[i]), 0, state)
        state = np.where(np.isnan(c), 0, state)
        out[i] = state
    pos.loc[:, :] = out
    return pos


def sig_xsmom(C, R, lb=30, q=0.2):
    """cross-sectional momentum: long top quantile, short bottom quantile"""
    m = C / C.shift(lb) - 1
    rk = m.rank(axis=1, pct=True)
    return (rk >= 1 - q).astype(float) - (rk <= q).astype(float)


def sig_xsrev(C, R, lb=7, q=0.2):
    """cross-sectional short-term reversal"""
    return -sig_xsmom(C, R, lb, q)


SIGNALS = {
    "tsmom_20_60_120": sig_tsmom,
    "ema_20_100": sig_ema,
    "donchian_50_20": sig_donchian,
    "xsmom_30d": sig_xsmom,
    "xsrev_7d": sig_xsrev,
}


# ---------------------------------------------------------------- portfolio
def portfolio(C, F, signal, target_vol=0.15, rebalance="D", risk_parity=True, gross_cap=2.0):
    R = C.pct_change(fill_method=None)
    s = signal.where(C.notna())
    v = vol(R)
    w = s / v if risk_parity else s.copy()
    w = w.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    # normalise so the *naive* (uncorrelated) portfolio vol = target
    n = (w != 0).sum(axis=1).replace(0, np.nan)
    w = w.div(n, axis=0).fillna(0.0) * target_vol * np.sqrt(n.fillna(1)).values[:, None] if risk_parity else \
        w.div(w.abs().sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
    if rebalance != "D":
        w = w.resample(rebalance).last().reindex(C.index, method="ffill").fillna(0.0)
    gross = w.abs().sum(axis=1)
    w = w.mul(np.minimum(1.0, gross_cap / gross.replace(0, np.nan)).fillna(1.0), axis=0)
    wl = w.shift(1).fillna(0.0)                       # decided at close t, held during t+1
    pnl = (wl * R.fillna(0.0)).sum(axis=1)
    fund = -(wl * F).sum(axis=1)                      # longs pay positive funding, shorts receive
    turn = (w - w.shift(1).fillna(0.0)).abs().sum(axis=1).shift(1).fillna(0.0)
    ret = pnl + fund - turn * COST
    return ret, wl


def vol_target(C, F, w_raw, target_vol=0.12, lookback=60, max_lev=3.0):
    """Scale raw weights so the strategy's trailing realised vol hits `target_vol`.

    The scale used on day t+1 only uses returns up to day t.
    """
    R = C.pct_change(fill_method=None).fillna(0.0)
    raw = (w_raw.shift(1).fillna(0.0) * R).sum(axis=1)
    rv = raw.rolling(lookback, min_periods=20).std() * np.sqrt(365)
    scale = (target_vol / rv).clip(upper=max_lev).fillna(0.0)
    w = w_raw.mul(scale, axis=0)
    wl = w.shift(1).fillna(0.0)
    pnl = (wl * R).sum(axis=1)
    fund = -(wl * F).sum(axis=1)
    turn = (w - w.shift(1).fillna(0.0)).abs().sum(axis=1).shift(1).fillna(0.0)
    return pnl + fund - turn * COST, wl


def raw_weights(C, signal):
    """inverse-vol weights, gross exposure normalised to 1"""
    R = C.pct_change(fill_method=None)
    w = (signal.where(C.notna()) / vol(R)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return w.div(w.abs().sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)


def stats(ret, wl):
    eq = (1 + ret).cumprod()
    yrs = (ret.index[-1] - ret.index[0]).days / 365
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    vol_ = ret.std() * np.sqrt(365)
    mdd = (1 - eq / eq.cummax()).max()
    by = ret.groupby(ret.index.year).apply(lambda x: (1 + x).prod() - 1)
    m = (1 + ret).resample("ME").prod() - 1
    return dict(cagr=round(cagr * 100, 1), vol=round(vol_ * 100, 1),
                sharpe=round(ret.mean() / ret.std() * np.sqrt(365), 2) if ret.std() > 0 else 0,
                mdd=round(mdd * 100, 1), pos_m=round((m > 0).mean() * 100, 0),
                gross=round(wl.abs().sum(axis=1).mean(), 2),
                net=round(wl.sum(axis=1).mean(), 2),
                years={int(k): round(v * 100, 1) for k, v in by.items()})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs-file", default="configs/pairs_universe_futures.json")
    ap.add_argument("--start", default="2020-06-01")
    ap.add_argument("--end", default="2024-01-01")
    ap.add_argument("--target-vol", type=float, default=0.12)
    a = ap.parse_args()
    C, F = load_universe(a.pairs_file)
    C = C.loc[:a.end]
    F = F.loc[:a.end]
    R = C.pct_change(fill_method=None)
    variants = {k: fn(C, R) for k, fn in SIGNALS.items()}
    for lb in (7, 14, 21, 30, 60, 90):
        for q in (0.1, 0.2, 0.3):
            variants[f"xsmom_{lb}d_q{q}"] = sig_xsmom(C, R, lb, q)
    for name, sig in variants.items():
        ret, wl = vol_target(C, F, raw_weights(C, sig), target_vol=a.target_vol)
        ret, wl = ret.loc[a.start:], wl.loc[a.start:]
        print(name.ljust(20), stats(ret, wl))


if __name__ == "__main__":
    main()


def ensemble_trend(C, R, lbs=(10, 20, 40, 80, 160)):
    """average sign of returns across a geometric ladder of look-backs (no single 'best' value)"""
    return sum(np.sign(C / C.shift(lb) - 1) for lb in lbs) / len(lbs)


def ensemble_xsmom(C, R, lbs=(14, 30, 60, 90), q=0.2):
    return sum(sig_xsmom(C, R, lb, q) for lb in lbs) / len(lbs)


def combo_report(pairs_file="configs/pairs_universe_futures.json", start="2020-06-01", end="2024-01-01", tv=0.12):
    C, F = load_universe(pairs_file)
    C, F = C.loc[:end], F.loc[:end]
    R = C.pct_change(fill_method=None)
    parts = {
        "trend_ens": raw_weights(C, ensemble_trend(C, R)),
        "xsmom_ens": raw_weights(C, ensemble_xsmom(C, R)),
        "donchian": raw_weights(C, sig_donchian(C, R)),
    }
    rets = {}
    for k, w in parts.items():
        r, wl = vol_target(C, F, w, target_vol=tv)
        rets[k] = r.loc[start:]
        print(k.ljust(12), stats(r.loc[start:], wl.loc[start:]))
    print("correlation of daily returns:\n", pd.DataFrame(rets).corr().round(2))
    # equal-risk combination of the vol-targeted sleeves, then re-targeted
    for combo in (("trend_ens", "xsmom_ens"), ("trend_ens", "donchian", "xsmom_ens")):
        w = sum(parts[k] / len(combo) for k in combo)
        r, wl = vol_target(C, F, w, target_vol=tv)
        print("+".join(combo).ljust(12), stats(r.loc[start:], wl.loc[start:]))


DEFAULTS = dict(trend_lbs=(10, 20, 40, 80, 160), xs_lbs=(14, 30, 60, 90), q=0.2, vol_lb=60, tv=0.12, w_trend=0.5)


def combo_returns(C, F, trend_lbs, xs_lbs, q, vol_lb, tv, w_trend):
    R = C.pct_change(fill_method=None)
    wt = raw_weights(C, ensemble_trend(C, R, trend_lbs))
    wx = raw_weights(C, ensemble_xsmom(C, R, xs_lbs, q))
    return vol_target(C, F, w_trend * wt + (1 - w_trend) * wx, target_vol=tv, lookback=vol_lb)


def combo_sensitivity(pairs_file="configs/pairs_universe_futures.json", start="2020-06-01", end="2024-01-01"):
    C, F = load_universe(pairs_file)
    C, F = C.loc[:end], F.loc[:end]
    grid = {
        "trend_lbs": [(5, 10, 20, 40, 80), (10, 20, 40, 80, 160), (20, 40, 80, 160, 320), (20, 60, 120)],
        "xs_lbs": [(7, 14, 30), (14, 30, 60, 90), (30, 60, 90, 180), (30,)],
        "q": [0.1, 0.2, 0.3, 0.4],
        "vol_lb": [30, 60, 90, 120],
        "w_trend": [0.3, 0.5, 0.7],
        "tv": [0.08, 0.10, 0.12, 0.15],
    }
    rows = []
    for k, vals in grid.items():
        for v in vals:
            p = dict(DEFAULTS, **{k: v})
            r, wl = combo_returns(C, F, **p)
            st = stats(r.loc[start:], wl.loc[start:])
            rows.append({"param": k, "value": str(v), **{x: st[x] for x in ("cagr", "mdd", "sharpe", "pos_m")},
                         "worst_year": min(st["years"].values())})
    df = pd.DataFrame(rows)
    print(df.to_string(index=False))
    return df


def execute(C, F, w_target, band=0.25, flip_lag=True):
    """Simulate freqtrade-like execution of daily target weights.

    * a position is only re-sized when |actual/target - 1| > band
    * a sign flip closes the position; the opposite position opens one day later
    """
    R = C.pct_change(fill_method=None).fillna(0.0)
    W = w_target.fillna(0.0).to_numpy()
    held = np.zeros(W.shape)
    cur = np.zeros(W.shape[1])
    for i in range(W.shape[0]):
        tgt = W[i]
        new = cur.copy()
        flip = (np.sign(cur) != 0) & (np.sign(tgt) != np.sign(cur))
        if flip_lag:
            new[flip] = 0.0
        else:
            new[flip] = tgt[flip]
        opening = (cur == 0) & (tgt != 0)
        new[opening] = tgt[opening]
        same = (np.sign(cur) == np.sign(tgt)) & (cur != 0)
        drift = np.abs(np.divide(cur, tgt, out=np.ones_like(cur), where=tgt != 0) - 1) > band
        new[same & drift] = tgt[same & drift]
        held[i] = new
        cur = new
    w = pd.DataFrame(held, index=w_target.index, columns=w_target.columns)
    wl = w.shift(1).fillna(0.0)
    turn = (w - w.shift(1).fillna(0.0)).abs().sum(axis=1).shift(1).fillna(0.0)
    return (wl * R).sum(axis=1) - (wl * F).sum(axis=1) - turn * COST, wl


def execution_report(start="2020-06-01", end="2024-01-01"):
    C, F = load_universe("configs/pairs_universe_futures.json")
    C, F = C.loc[:end], F.loc[:end]
    _, wl = combo_returns(C, F, **DEFAULTS)
    w_t = wl.shift(-1).fillna(0.0)
    for band, lag in ((0.0, False), (0.25, False), (0.0, True), (0.25, True)):
        r, h = execute(C, F, w_t, band, lag)
        print(f"band={band} flip_lag={lag}", stats(r.loc[start:], h.loc[start:]))


def ensemble_xscarry(C, F, lbs=(3, 7, 14), q=0.2):
    """cross-sectional funding carry: short the highest trailing funding, long the lowest"""
    out = 0
    for lb in lbs:
        rk = F.rolling(lb).sum().where(C.notna()).rank(axis=1, pct=True)
        out = out + (rk <= q).astype(float) - (rk >= 1 - q).astype(float)
    return out / len(lbs)


def three_sleeve_report(pairs_file="configs/pairs_universe_futures.json", start="2020-06-01", end="2024-01-01", tv=0.12):
    C, F = load_universe(pairs_file)
    C, F = C.loc[:end], F.loc[:end]
    R = C.pct_change(fill_method=None)
    sleeves = {
        "trend": raw_weights(C, ensemble_trend(C, R, DEFAULTS["trend_lbs"])),
        "xsmom": raw_weights(C, ensemble_xsmom(C, R, DEFAULTS["xs_lbs"], DEFAULTS["q"])),
        "xscarry": raw_weights(C, ensemble_xscarry(C, F)),
    }
    rets = {}
    for k, w in sleeves.items():
        r, wl = vol_target(C, F, w, target_vol=tv)
        rets[k] = r.loc[start:]
        print(k.ljust(10), stats(r.loc[start:], wl.loc[start:]))
    print(pd.DataFrame(rets).corr().round(2))
    for combo in (("trend", "xsmom"), ("trend", "xsmom", "xscarry")):
        w = sum(sleeves[k] / len(combo) for k in combo)
        r, wl = vol_target(C, F, w, target_vol=tv)
        print("+".join(combo).ljust(22), stats(r.loc[start:], wl.loc[start:]))
