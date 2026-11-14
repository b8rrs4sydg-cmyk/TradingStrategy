#!/usr/bin/env python3
"""
Feature lab: does extra information (price action, harmonic patterns, classic
indicators, market sentiment) predict crypto returns out of sample?

Protocol (fixed before looking at results)
------------------------------------------
* D  (discovery) : universe A+B (100 perps), 2020-06-01 .. 2023-12-31
* V1 (time)      : universe A+B,           2024-01-01 .. 2026-09-30
* V2 (universe)  : universe C (236 perps), 2020-06-01 .. 2026-09-30
* decision at the daily close t, forward returns from close t to close t+k
  (k = 1, 3, 7 days), measured in excess of the equal-weight market return
* discrete signals  -> event study: mean signed excess return per event date,
                       t-stat with Newey-West (lag k) over the event-date series
* continuous signals-> mean return of the top-minus-bottom quintile spread, NW t-stat
                       (rank IC is reported too, but it ignores fat tails and can be
                       significant while the tradable spread loses money)
* a feature SURVIVES only if it is significant in D after Benjamini-Hochberg
  (FDR 10 % over all tests) AND has the same sign with p < 0.05 in V1 AND V2

    python research/feature_lab.py --families price harmonic indicators
    python research/feature_lab.py --families sentiment          # needs metrics data
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import talib

FUT = Path("user_data/data/binance/futures")
MET = Path("user_data/data/binance/metrics")
HORIZONS = (1, 3, 7)


# ======================================================================= data
def load_panel(pairs_file: str) -> dict[str, pd.DataFrame]:
    """dict of wide DataFrames: open, high, low, close, volume, funding"""
    cols = {k: {} for k in ("open", "high", "low", "close", "volume", "funding")}
    for p in json.load(open(pairs_file)):
        base = p.split("/")[0]
        f = FUT / f"{base}_USDT_USDT-1d-futures.feather"
        if not f.exists():
            continue
        d = pd.read_feather(f).set_index("date")
        d.index = d.index.normalize()
        for k in ("open", "high", "low", "close", "volume"):
            cols[k][base] = d[k]
        fr = FUT / f"{base}_USDT_USDT-1h-funding_rate.feather"
        if fr.exists():
            r = pd.read_feather(fr).set_index("date")["close"]
            cols["funding"][base] = r.groupby(r.index.floor("D")).sum()
    P = {k: pd.DataFrame(v).sort_index() for k, v in cols.items()}
    idx = P["close"].index
    P = {k: v.reindex(idx) for k, v in P.items()}
    P["funding"] = P["funding"].fillna(0.0).where(P["close"].notna())
    return P


def load_metrics(columns, index=None) -> dict[str, pd.DataFrame]:
    out = {}
    for f in MET.glob("*_USDT-1d-metrics.feather"):
        base = f.name.split("_")[0]
        d = pd.read_feather(f).set_index("date")
        d.index = pd.DatetimeIndex(pd.to_datetime(d.index, utc=True)).normalize()
        out[base] = d[~d.index.duplicated()]
    M = {}
    for c in ("oi", "oi_value", "top_acc_ls", "top_pos_ls", "glob_ls", "taker_ls", "premium"):
        M[c] = pd.DataFrame({b: d[c] for b, d in out.items() if c in d}).reindex(columns=columns)
        if index is not None:
            M[c] = M[c].reindex(index)
    return M


def fwd_excess(P, k):
    c = P["close"]
    fwd = c.shift(-k) / c - 1
    return fwd.sub(fwd.mean(axis=1), axis=0)


# ================================================================== statistics
def nw_t(x: pd.Series, lag: int) -> tuple[float, float, int]:
    """mean, Newey-West t-stat, n for a time series"""
    x = x.dropna()
    n = len(x)
    if n < 30:
        return np.nan, np.nan, n
    m = x.mean()
    e = (x - m).to_numpy()
    var = e @ e / n
    for L in range(1, lag + 1):
        w = 1 - L / (lag + 1)
        var += 2 * w * (e[L:] @ e[:-L]) / n
    se = math.sqrt(max(var, 1e-18) / n)
    return m, m / se, n


def p_two(t):
    return math.erfc(abs(t) / math.sqrt(2)) if np.isfinite(t) else np.nan


def event_test(sig: pd.DataFrame, fx: pd.DataFrame, k: int, mask_rows):
    """sig: +1 long event, -1 short event, 0/NaN none. Signed excess return per event date."""
    s = sig.where(sig != 0).loc[mask_rows]
    r = (s * fx.loc[mask_rows])
    per_day = r.mean(axis=1)                     # average over events of that day
    n_events = int(s.notna().sum().sum())
    m, t, n = nw_t(per_day, k)
    return dict(mean_bp=m * 1e4 if np.isfinite(m) else np.nan, t=t, p=p_two(t), days=n, events=n_events)


def spread_test(feat: pd.DataFrame, fx: pd.DataFrame, k: int, mask_rows, q: float = 0.2):
    """mean excess return of the top-quantile minus bottom-quantile (equal weight), NW t-stat.

    This is what a long/short portfolio actually earns (before costs); unlike rank IC it
    is sensitive to fat right tails (e.g. shorting 'lottery' coins that occasionally explode).
    """
    f = feat.loc[mask_rows]
    y = fx.loc[mask_rows].where(f.notna())
    rk = f.rank(axis=1, pct=True)
    enough = (f.notna().sum(axis=1) >= 10).to_numpy()[:, None]
    top = y.where((rk >= 1 - q) & enough).mean(axis=1)
    bot = y.where((rk <= q) & enough).mean(axis=1)
    m, t, n = nw_t(top - bot, k)
    return dict(mean_bp=m * 1e4 if np.isfinite(m) else np.nan, t=t, p=p_two(t), days=n, events=np.nan)


def ic_test(feat: pd.DataFrame, fx: pd.DataFrame, k: int, mask_rows):
    f = feat.loc[mask_rows]
    y = fx.loc[mask_rows]
    fr = f.rank(axis=1)
    yr = y.where(f.notna()).rank(axis=1)
    fr = fr.where(yr.notna())
    ok = fr.notna().sum(axis=1) >= 8
    fc = fr.sub(fr.mean(axis=1), axis=0)
    yc = yr.sub(yr.mean(axis=1), axis=0)
    ic = (fc * yc).sum(axis=1) / np.sqrt((fc ** 2).sum(axis=1) * (yc ** 2).sum(axis=1))
    m, t, n = nw_t(ic[ok], k)
    return dict(mean_bp=m * 100 if np.isfinite(m) else np.nan, t=t, p=p_two(t), days=n, events=np.nan)


# ============================================================ feature families
def apply_talib(P, fn, *fields, **kw):
    out = {}
    for c in P["close"].columns:
        args = [P[f][c].to_numpy(dtype=float) for f in fields]
        if np.isnan(args[-1]).all():
            continue
        valid = ~np.isnan(np.vstack(args)).any(axis=0)
        res = np.full(len(args[0]), np.nan)
        if valid.sum() > 60:
            first = np.argmax(valid)
            seg = [a[first:] for a in args]
            seg = [pd.Series(a).ffill().to_numpy() for a in seg]
            res[first:] = fn(*seg, **kw)
        out[c] = res
    return pd.DataFrame(out, index=P["close"].index)


def fam_price(P):
    """candlestick patterns (TA-Lib) + market structure / price-action events"""
    feats = {}
    for name in talib.get_function_groups()["Pattern Recognition"]:
        fn = getattr(talib, name)
        raw = apply_talib(P, fn, "open", "high", "low", "close")
        sig = np.sign(raw).where(raw != 0)
        if sig.notna().sum().sum() >= 200:
            feats[f"cdl:{name[3:].lower()}"] = ("event", sig)
    o, h, l, c = P["open"], P["high"], P["low"], P["close"]
    # fractal swing points (2 bars each side) are only CONFIRMED 2 bars later
    sh = (h.shift(2) > h.shift(1)) & (h.shift(2) > h.shift(3)) & (h.shift(2) > h) & (h.shift(2) > h.shift(4))
    sl = (l.shift(2) < l.shift(1)) & (l.shift(2) < l.shift(3)) & (l.shift(2) < l) & (l.shift(2) < l.shift(4))
    last_sh = h.shift(2).where(sh).ffill()
    last_sl = l.shift(2).where(sl).ffill()
    prev_sh = h.shift(2).where(sh).ffill().where(sh).shift(1).ffill()
    prev_sl = l.shift(2).where(sl).ffill().where(sl).shift(1).ffill()
    hh_hl = ((last_sh > prev_sh) & (last_sl > prev_sl)).astype(float) - ((last_sh < prev_sh) & (last_sl < prev_sl)).astype(float)
    feats["pa:structure_hh_hl"] = ("continuous", hh_hl.where(c.notna()))
    bos_up = (c > last_sh) & (c.shift(1) <= last_sh.shift(1))
    bos_dn = (c < last_sl) & (c.shift(1) >= last_sl.shift(1))
    feats["pa:break_of_structure"] = ("event", bos_up.astype(float).where(bos_up) .fillna(0) - bos_dn.astype(float))
    rng = h - l
    body = (c - o).abs()
    lower_wick = np.minimum(o, c) - l
    upper_wick = h - np.maximum(o, c)
    low20, high20 = l.rolling(20).min(), h.rolling(20).max()
    pin_bull = (lower_wick > 2 * body) & (lower_wick > 0.6 * rng) & (l <= low20)
    pin_bear = (upper_wick > 2 * body) & (upper_wick > 0.6 * rng) & (h >= high20)
    feats["pa:pinbar_at_20d_extreme"] = ("event", pin_bull.astype(float) - pin_bear.astype(float))
    inside = (h.shift(1) < h.shift(2)) & (l.shift(1) > l.shift(2))
    feats["pa:inside_bar_breakout"] = ("event", (inside & (c > h.shift(1))).astype(float) - (inside & (c < l.shift(1))).astype(float))
    nr7 = rng.shift(1) <= rng.rolling(7).min().shift(1)
    feats["pa:nr7_breakout"] = ("event", (nr7 & (c > h.shift(1))).astype(float) - (nr7 & (c < l.shift(1))).astype(float))
    feats["pa:dist_to_50d_high"] = ("continuous", c / h.rolling(50).max() - 1)
    feats["pa:dist_to_50d_low"] = ("continuous", c / l.rolling(50).min() - 1)
    feats["pa:range_position_20d"] = ("continuous", (c - low20) / (high20 - low20))
    feats["pa:close_location_value"] = ("continuous", ((c - l) - (h - c)) / rng.replace(0, np.nan))
    return {k: (t, v.where(P["close"].notna()).replace(0, np.nan) if t == "event" else v) for k, (t, v) in feats.items()}


# ---------------------------------------------------------------- harmonics
HARMONICS = {
    # name: (AB/XA range, BC/AB range, CD/BC range, AD/XA target)
    "gartley": ((0.55, 0.68), (0.382, 0.886), (1.13, 1.618), 0.786),
    "bat": ((0.382, 0.50), (0.382, 0.886), (1.618, 2.618), 0.886),
    "butterfly": ((0.75, 0.82), (0.382, 0.886), (1.618, 2.24), 1.27),
    "crab": ((0.382, 0.618), (0.382, 0.886), (2.24, 3.618), 1.618),
}


def zigzag_confirmed(h: np.ndarray, l: np.ndarray, pct: float):
    """ZigZag pivots with the bar index at which each pivot became CONFIRMED.

    returns list of (pivot_idx, price, +1 high / -1 low, confirm_idx)
    """
    piv = []
    trend = 0
    ext_i, ext_p = 0, np.nan
    for i in range(len(h)):
        if np.isnan(h[i]):
            continue
        if np.isnan(ext_p):
            ext_i, ext_p, trend = i, h[i], 1
            continue
        if trend >= 0:
            if h[i] > ext_p:
                ext_i, ext_p = i, h[i]
            elif l[i] < ext_p * (1 - pct):
                piv.append((ext_i, ext_p, 1, i))
                trend, ext_i, ext_p = -1, i, l[i]
        else:
            if l[i] < ext_p:
                ext_i, ext_p = i, l[i]
            elif h[i] > ext_p * (1 + pct):
                piv.append((ext_i, ext_p, -1, i))
                trend, ext_i, ext_p = 1, i, h[i]
    return piv


def harmonic_signals(h: np.ndarray, l: np.ndarray, c: np.ndarray, pct: float, tol: float = 0.05):
    """+1 / -1 at the first bar whose range enters the projected D zone of a valid XABC.

    Only pivots confirmed BEFORE the bar are used, so no lookahead.
    """
    sig = {n: np.zeros(len(c)) for n in HARMONICS}
    piv = zigzag_confirmed(h, l, pct)
    for j in range(3, len(piv)):
        X, A, B, C = piv[j - 3], piv[j - 2], piv[j - 1], piv[j]
        start = C[3] + 1                                 # C confirmed at C[3]
        end = piv[j + 1][3] if j + 1 < len(piv) else len(c)
        bullish = C[2] == 1                              # X low, A high, B low, C high -> D low
        xa = abs(A[1] - X[1])
        ab = abs(A[1] - B[1])
        bc = abs(C[1] - B[1])
        if xa == 0 or ab == 0 or bc == 0:
            continue
        for name, (ab_r, bc_r, cd_r, ad_t) in HARMONICS.items():
            if not (ab_r[0] * (1 - tol) <= ab / xa <= ab_r[1] * (1 + tol)):
                continue
            if not (bc_r[0] * (1 - tol) <= bc / ab <= bc_r[1] * (1 + tol)):
                continue
            d_level = A[1] - ad_t * xa if bullish else A[1] + ad_t * xa
            cd = abs(C[1] - d_level)
            if not (cd_r[0] * (1 - tol) <= cd / bc <= cd_r[1] * (1 + tol)):
                continue
            for i in range(start, end):
                if bullish and l[i] <= d_level * (1 + tol * 0.2):
                    sig[name][i] = 1
                    break
                if not bullish and h[i] >= d_level * (1 - tol * 0.2):
                    sig[name][i] = -1
                    break
    return sig


def fam_harmonic(P):
    feats = {}
    for pct in (0.05, 0.10):
        acc = {n: {} for n in HARMONICS}
        for col in P["close"].columns:
            h, l, c = (P[k][col].to_numpy(dtype=float) for k in ("high", "low", "close"))
            s = harmonic_signals(h, l, c, pct)
            for n in HARMONICS:
                acc[n][col] = s[n]
        allsig = 0
        for n in HARMONICS:
            df = pd.DataFrame(acc[n], index=P["close"].index)
            allsig = allsig + df
            feats[f"harm:{n}_zz{int(pct*100)}"] = ("event", df.replace(0, np.nan))
        feats[f"harm:any_zz{int(pct*100)}"] = ("event", np.sign(allsig).replace(0, np.nan))
    return feats


def fam_indicators(P):
    o, h, l, c, v = (P[k] for k in ("open", "high", "low", "close", "volume"))
    f = {}
    f["ind:rsi14"] = apply_talib(P, talib.RSI, "close", timeperiod=14)
    f["ind:rsi2"] = apply_talib(P, talib.RSI, "close", timeperiod=2)
    f["ind:stoch_k"] = apply_talib(P, lambda hh, ll, cc: talib.STOCH(hh, ll, cc)[0], "high", "low", "close")
    f["ind:cci20"] = apply_talib(P, talib.CCI, "high", "low", "close", timeperiod=20)
    f["ind:willr14"] = apply_talib(P, talib.WILLR, "high", "low", "close", timeperiod=14)
    f["ind:mfi14"] = apply_talib(P, talib.MFI, "high", "low", "close", "volume", timeperiod=14)
    f["ind:adx14_x_dir"] = apply_talib(P, talib.ADX, "high", "low", "close", timeperiod=14) * np.sign(
        apply_talib(P, talib.PLUS_DI, "high", "low", "close", timeperiod=14)
        - apply_talib(P, talib.MINUS_DI, "high", "low", "close", timeperiod=14))
    macd = apply_talib(P, lambda x: talib.MACD(x)[2], "close")
    f["ind:macd_hist_norm"] = macd / c
    f["ind:bb_pctb20"] = (c - c.rolling(20).mean()) / (2 * c.rolling(20).std())
    f["ind:atr_pct14"] = apply_talib(P, talib.ATR, "high", "low", "close", timeperiod=14) / c
    f["ind:obv_slope20"] = apply_talib(P, talib.OBV, "close", "volume").diff(20) / v.rolling(20).sum()
    f["ind:volume_surge"] = v / v.rolling(20).mean()
    f["ind:ret_1d"] = c.pct_change(fill_method=None)
    f["ind:ret_7d"] = c.pct_change(7, fill_method=None)
    f["ind:ret_30d"] = c.pct_change(30, fill_method=None)
    f["ind:skew_30d"] = c.pct_change(fill_method=None).rolling(30).skew()
    f["ind:max_ret_30d"] = c.pct_change(fill_method=None).rolling(30).max()
    f["ind:dist_ema200"] = c / c.ewm(span=200, adjust=False).mean() - 1
    return {k: ("continuous", v.where(c.notna())) for k, v in f.items()}


def fam_sentiment(P):
    M = load_metrics(P["close"].columns, P["close"].index)
    c = P["close"]
    fund = P["funding"]
    f = {}
    f["sent:funding_1d"] = fund
    f["sent:funding_7d"] = fund.rolling(7).sum()
    f["sent:funding_z30"] = (fund.rolling(3).sum() - fund.rolling(30).mean() * 3) / (fund.rolling(30).std() * np.sqrt(3))
    oi = M["oi_value"]
    f["sent:oi_chg_1d"] = oi.pct_change(fill_method=None)
    f["sent:oi_chg_7d"] = oi.pct_change(7, fill_method=None)
    f["sent:oi_vs_price_7d"] = oi.pct_change(7, fill_method=None) - c.pct_change(7, fill_method=None)
    f["sent:oi_to_volume"] = oi / (P["volume"] * c).rolling(7).mean()
    f["sent:top_acc_ls"] = M["top_acc_ls"]
    f["sent:top_pos_ls"] = M["top_pos_ls"]
    f["sent:glob_ls"] = M["glob_ls"]
    f["sent:smart_vs_crowd"] = np.log(M["top_pos_ls"]) - np.log(M["glob_ls"])
    f["sent:taker_ls_1d"] = M["taker_ls"]
    f["sent:taker_ls_7d"] = M["taker_ls"].rolling(7).mean()
    f["sent:premium"] = M["premium"]
    f["sent:glob_ls_chg_7d"] = M["glob_ls"].pct_change(7, fill_method=None)
    # metrics of day d are only complete at the end of day d -> already aligned with close-t decisions
    return {k: ("continuous", v.reindex_like(c).where(c.notna())) for k, v in f.items()}


FAMILIES = {"price": fam_price, "harmonic": fam_harmonic, "indicators": fam_indicators, "sentiment": fam_sentiment}

PERIODS = {
    "D": ("configs/pairs_ab_futures.json", "2020-06-01", "2023-12-31"),
    "V1": ("configs/pairs_ab_futures.json", "2024-01-01", "2026-09-30"),
    "V2": ("configs/pairs_holdout_c_futures.json", "2020-06-01", "2026-09-30"),
}


def bh(pvals: pd.Series, q=0.10) -> pd.Series:
    p = pvals.dropna().sort_values()
    n = len(p)
    thresh = q * np.arange(1, n + 1) / n
    passed = p.to_numpy() <= thresh
    kmax = np.max(np.where(passed)[0]) if passed.any() else -1
    out = pd.Series(False, index=pvals.index)
    if kmax >= 0:
        out.loc[p.index[: kmax + 1]] = True
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--families", nargs="+", default=["price", "harmonic", "indicators"])
    ap.add_argument("--out", default="research/results/feature_lab.csv")
    ap.add_argument("--d-start", default=None, help="override discovery start (sentiment data begins 2021-12)")
    ap.add_argument("--v2-pairs", default=None, help="override the V2 universe file")
    a = ap.parse_args()
    if a.d_start:
        PERIODS["D"] = (PERIODS["D"][0], a.d_start, PERIODS["D"][2])
    if a.v2_pairs:
        PERIODS["V2"] = (a.v2_pairs, max(a.d_start or "2020-06-01", PERIODS["V2"][1]), PERIODS["V2"][2])
    panels = {}
    for pf in {v[0] for v in PERIODS.values()}:
        panels[pf] = load_panel(pf)
    rows = []
    for fam in a.families:
        feats_by_pf = {pf: FAMILIES[fam](P) for pf, P in panels.items()}
        names = list(next(iter(feats_by_pf.values())).keys())
        for name in names:
            for k in HORIZONS:
                row = {"family": fam, "feature": name, "k": k}
                for per, (pf, s, e) in PERIODS.items():
                    P = panels[pf]
                    if name not in feats_by_pf[pf]:
                        continue
                    kind, F = feats_by_pf[pf][name]
                    fx = fwd_excess(P, k)
                    rows_mask = (P["close"].index >= s) & (P["close"].index <= e)
                    if kind == "event":
                        res = event_test(F, fx, k, rows_mask)
                    else:
                        res = spread_test(F, fx, k, rows_mask)
                        ic = ic_test(F, fx, k, rows_mask)
                        row[f"{per}_rankIC_t"] = ic["t"]
                    row["kind"] = kind
                    for kk, vv in res.items():
                        row[f"{per}_{kk}"] = vv
                rows.append(row)
        print(f"{fam}: {len(names)} features done", flush=True)
    df = pd.DataFrame(rows)
    df["D_bh"] = bh(df["D_p"])
    sign_d = np.sign(df["D_t"])
    df["replicates"] = df["D_bh"] & (np.sign(df["V1_t"]) == sign_d) & (df["V1_p"] < 0.05) \
        & (np.sign(df["V2_t"]) == sign_d) & (df["V2_p"] < 0.05)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(a.out, index=False)
    pd.set_option("display.width", 250)
    show = ["feature", "k", "kind", "D_mean_bp", "D_t", "D_events", "V1_mean_bp", "V1_t", "V2_mean_bp", "V2_t", "D_bh", "replicates"]
    print(f"\n{len(df)} tests, {int(df['D_bh'].sum())} significant in D after BH(10%), {int(df['replicates'].sum())} replicate in V1 and V2")
    print(df[df["D_bh"]].sort_values("D_t", key=abs, ascending=False)[show].round(2).to_string(index=False))


if __name__ == "__main__":
    main()


# ============================================================ factor portfolios
COST = 0.001
SLOW_COMPOSITE = ["ind:max_ret_30d", "ind:atr_pct14", "pa:dist_to_50d_low", "ind:adx14_x_dir",
                  "ind:mfi14", "ind:rsi14", "ind:macd_hist_norm", "ind:ret_7d"]   # replicated at k=7, all negative IC


def factor_portfolio(F: pd.DataFrame, P, rebalance: int = 7, q: float = 0.2, sign: float = -1.0):
    """long the quantile the feature predicts to outperform, short the other; dollar neutral, gross 1"""
    c = P["close"]
    s = sign * F.where(c.notna())
    rk = s.rank(axis=1, pct=True)
    n_ok = s.notna().sum(axis=1)
    enough = (n_ok >= 10).to_numpy()[:, None]      # row-wise condition (avoid column alignment)
    longs = (rk >= 1 - q) & enough
    shorts = (rk <= q) & enough
    w = longs.astype(float).div(longs.sum(axis=1).replace(0, np.nan), axis=0).fillna(0) * 0.5 \
        - shorts.astype(float).div(shorts.sum(axis=1).replace(0, np.nan), axis=0).fillna(0) * 0.5
    if rebalance > 1:
        keep = np.arange(len(w)) % rebalance == 0
        w = w.where(np.repeat(keep[:, None], w.shape[1], axis=1), np.nan).ffill().fillna(0)
    R = c.pct_change(fill_method=None).fillna(0)
    wl = w.shift(1).fillna(0)
    turn = (w - w.shift(1).fillna(0)).abs().sum(axis=1).shift(1).fillna(0)
    gross = (wl * R).sum(axis=1)
    fund = -(wl * P["funding"].fillna(0)).sum(axis=1)
    net = gross + fund - turn * COST
    return gross, net, turn


def perf_stats(r: pd.Series):
    r = r.dropna()
    eq = (1 + r).cumprod()
    yrs = max(1e-9, len(r) / 365)
    return dict(cagr=round((eq.iloc[-1] ** (1 / yrs) - 1) * 100, 1), vol=round(r.std() * np.sqrt(365) * 100, 1),
                sharpe=round(r.mean() / r.std() * np.sqrt(365), 2) if r.std() > 0 else 0.0,
                mdd=round(float((1 - eq / eq.cummax()).max()) * 100, 1))


def factor_report():
    panels = {pf: load_panel(pf) for pf in {v[0] for v in PERIODS.values()}}
    rows = []
    for pf, P in panels.items():
        feats = {**fam_indicators(P)}
        lo50 = P["low"].rolling(50).min()
        feats["pa:dist_to_50d_low"] = ("continuous", P["close"] / lo50 - 1)
        ranks = [feats[n][1].rank(axis=1, pct=True) for n in SLOW_COMPOSITE]
        feats["COMPOSITE_slow"] = ("continuous", sum(ranks) / len(ranks))
        for name in SLOW_COMPOSITE + ["ind:ret_1d", "ind:rsi2", "COMPOSITE_slow"]:
            F = feats[name][1]
            for reb in (1, 3, 7):
                g, n, t = factor_portfolio(F, P, reb)
                for per, (ppf, s, e) in PERIODS.items():
                    if ppf != pf:
                        continue
                    sl = slice(s, e)
                    rows.append(dict(feature=name, rebalance=reb, period=per,
                                     turnover_yr=round(t.loc[sl].sum() / (len(t.loc[sl]) / 365), 1),
                                     gross_sharpe=perf_stats(g.loc[sl])["sharpe"],
                                     **{f"net_{k}": v for k, v in perf_stats(n.loc[sl]).items()}))
    df = pd.DataFrame(rows)
    piv = df.pivot_table(index=["feature", "rebalance"], columns="period",
                         values=["gross_sharpe", "net_sharpe", "net_cagr", "net_mdd", "turnover_yr"])
    pd.set_option("display.width", 250)
    print(piv.round(2).to_string())
    df.to_csv("research/results/factor_portfolios.csv", index=False)


# ============================================================ intraday (4h) re-test
def load_panel_4h(pairs_file: str) -> dict[str, pd.DataFrame]:
    spot = Path("user_data/data/binance")
    cols = {k: {} for k in ("open", "high", "low", "close", "volume")}
    for p in json.load(open(pairs_file)):
        base = p.split("/")[0]
        f = spot / f"{base}_USDT-1h.feather"
        if not f.exists():
            continue
        d = pd.read_feather(f).set_index("date").resample("4h").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        for k in cols:
            cols[k][base] = d[k]
    P = {k: pd.DataFrame(v).sort_index() for k, v in cols.items()}
    P["funding"] = P["close"] * 0
    return P


def intraday_report(horizons=(1, 6, 18)):
    P = load_panel_4h("configs/pairs_ab_futures.json")
    feats = {}
    for name in talib.get_function_groups()["Pattern Recognition"]:
        raw = apply_talib(P, getattr(talib, name), "open", "high", "low", "close")
        sig = np.sign(raw).where(raw != 0)
        if sig.notna().sum().sum() >= 500:
            feats[f"cdl4h:{name[3:].lower()}"] = sig
    for k_, v in fam_harmonic(P).items():
        feats[k_.replace("harm:", "harm4h:")] = v[1]
    rows = []
    for name, F in feats.items():
        for k in horizons:
            fx = fwd_excess(P, k)
            row = {"feature": name, "k_bars": k}
            for per, (s, e) in {"D": ("2020-06-01", "2023-12-31"), "V1": ("2024-01-01", "2026-09-30")}.items():
                m = (P["close"].index >= s) & (P["close"].index <= e)
                for kk, vv in event_test(F, fx, k, m).items():
                    row[f"{per}_{kk}"] = vv
            rows.append(row)
    df = pd.DataFrame(rows)
    df["D_bh"] = bh(df["D_p"])
    df["replicates"] = df["D_bh"] & (np.sign(df["V1_t"]) == np.sign(df["D_t"])) & (df["V1_p"] < 0.05)
    df.to_csv("research/results/feature_lab_4h.csv", index=False)
    print(f"{len(df)} tests, {int(df['D_bh'].sum())} BH-significant in D, {int(df['replicates'].sum())} replicate in V1")
    show = ["feature", "k_bars", "D_events", "D_mean_bp", "D_t", "V1_mean_bp", "V1_t", "replicates"]
    print(df[df["D_bh"] | df["feature"].str.startswith("harm4h:any")].sort_values("D_t", key=abs, ascending=False)[show].round(2).head(30).to_string(index=False))


# ============================================================ market-level (time-series) sentiment
def market_sentiment_report(horizons=(1, 3, 7)):
    P = load_panel("configs/pairs_ab_futures.json")
    M = load_metrics(P["close"].columns, P["close"].index)
    c = P["close"]
    R = c.pct_change(fill_method=None)
    mkt = R.mean(axis=1)                         # equal-weight market daily return
    btc = R["BTC"]
    mkt_px = (1 + mkt.fillna(0)).cumprod()

    def z(x, n=180):
        return (x - x.rolling(n, min_periods=60).mean()) / x.rolling(n, min_periods=60).std()

    feats = {
        "mkt:funding_7d": P["funding"].mean(axis=1).rolling(7).sum(),
        "mkt:btc_funding_7d": P["funding"]["BTC"].rolling(7).sum(),
        "mkt:oi_chg_7d": M["oi_value"].sum(axis=1, min_count=10).pct_change(7, fill_method=None),
        "mkt:glob_ls": M["glob_ls"].mean(axis=1),
        "mkt:top_pos_ls": M["top_pos_ls"].mean(axis=1),
        "mkt:taker_ls_7d": M["taker_ls"].mean(axis=1).rolling(7).mean(),
        "mkt:btc_premium": M["premium"]["BTC"] if "BTC" in M["premium"] else None,
        "mkt:breadth_above_ema50": (c > c.ewm(span=50, adjust=False).mean()).sum(axis=1) / c.notna().sum(axis=1),
        "mkt:ret_30d": mkt_px.pct_change(30),
        "mkt:vol_30d": mkt.rolling(30).std(),
    }
    feats = {k: v for k, v in feats.items() if v is not None}
    # home-made "fear & greed" proxy: greed = strong momentum, low vol, high funding, rising OI, wide breadth
    fg = (z(feats["mkt:ret_30d"]) - z(feats["mkt:vol_30d"]) + z(feats["mkt:funding_7d"])
          + z(feats["mkt:oi_chg_7d"]) + z(feats["mkt:breadth_above_ema50"])) / 5
    feats["mkt:fear_greed_proxy"] = fg
    feats["mkt:fear_greed_extreme"] = np.sign(fg).where(fg.abs() > 1.5)

    periods = {"D": ("2021-12-01", "2023-12-31"), "V1": ("2024-01-01", "2026-09-30"),
               "D_long": ("2020-06-01", "2023-12-31")}     # D_long: features available before 2021-12 only
    rows = []
    for name, f in feats.items():
        fz = z(f) if "extreme" not in name else f
        for target_name, tgt in (("EW", mkt), ("BTC", btc)):
            for k in horizons:
                fwd = (1 + tgt).rolling(k).apply(np.prod, raw=True).shift(-k) - 1
                row = {"feature": name, "target": target_name, "k": k}
                for per, (s, e) in periods.items():
                    x = (fz * fwd).loc[s:e]             # mean of z * fwd return = covariance-type predictive stat
                    m, t, n = nw_t(x, k)
                    row[f"{per}_t"] = t
                    row[f"{per}_n"] = n
                rows.append(row)
    df = pd.DataFrame(rows)
    df["D_bh"] = bh(pd.Series([p_two(t) for t in df["D_t"]], index=df.index))
    df["replicates"] = df["D_bh"] & (np.sign(df["V1_t"]) == np.sign(df["D_t"])) & (df["V1_t"].abs() > 1.96)
    df.to_csv("research/results/feature_lab_market_sentiment.csv", index=False)
    pd.set_option("display.width", 250)
    print(f"{len(df)} tests, {int(df['D_bh'].sum())} BH-significant in D, {int(df['replicates'].sum())} replicate in V1")
    print(df.sort_values("D_t", key=abs, ascending=False).round(2).head(20).to_string(index=False))
