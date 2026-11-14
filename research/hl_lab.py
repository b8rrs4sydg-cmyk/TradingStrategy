#!/usr/bin/env python3
"""
Hyperliquid (HL) tests, exactly as pre-registered in research/PREREG_hyperliquid.md.

    python scripts/download_hyperliquid.py      # data first (needs api.hyperliquid.xyz reachable)
    python research/hl_lab.py

HL-A options availability, HL-B1 cross-venue funding arbitrage (HL vs Binance perps), HL-B2 HL carry
(Binance spot long + HL perp short), HL-C new HL perp listings (snipe long / fade short),
HL-D HIP-1 spot token launches (snipe long).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import listing_lab as L  # noqa: E402

HL = Path("user_data/data/hyperliquid")
BN = Path("user_data/data/binance")
OUT = Path("research/results")
SPLITS = {"IS": ("2023-01-01", "2024-12-31"), "OOS": ("2025-01-01", "2025-12-31"),
          "HOLDOUT": ("2026-01-01", "2026-12-31")}
F_HL_PERP, F_HL_SPOT, F_BN_PERP, F_BN_SPOT = 0.00045, 0.0007, 0.0005, 0.001


def split_of(ts):
    for k, (a, b) in SPLITS.items():
        if pd.Timestamp(a, tz="UTC") <= ts <= pd.Timestamp(b, tz="UTC") + pd.Timedelta(hours=23):
            return k
    return None


def end_of_data(dfs) -> pd.Timestamp:
    return max(d.index[-1] for d in dfs.values())


# ------------------------------------------------------------------ loading
def _daily(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    d = pd.read_feather(path).set_index("date")
    d.index = d.index.floor("D")
    d = d[(d["close"] > 0) & (d["volume"] > 0)]
    return d if len(d) >= 2 else None


def load_hl_perps() -> dict[str, pd.DataFrame]:
    out = {}
    for f in sorted((HL / "perp").glob("*-1d.feather")):
        coin = f.name.removesuffix("-1d.feather")
        d = _daily(f)
        if d is None:
            continue
        fr = HL / "perp" / f"{coin}-funding.feather"
        if fr.exists():
            r = pd.read_feather(fr).set_index("date")["funding"]
            d["funding"] = r.resample("1D").sum().reindex(d.index).fillna(0.0)
        else:
            d["funding"] = 0.0
        out[coin] = d
    return out


def load_hl_spot() -> dict[str, pd.DataFrame]:
    out = {}
    for f in sorted((HL / "spot").glob("*-1d.feather")):
        d = _daily(f)
        if d is not None:
            out[f.name.removesuffix("-1d.feather")] = d
    return out


def binance_name(coin: str) -> str:
    """HL 'kPEPE' (1000 units) <-> Binance '1000PEPE'; otherwise the same ticker."""
    if coin.startswith("k") and coin[1:].isupper() and (BN / "futures" / f"1000{coin[1:]}_USDT_USDT-1d-futures.feather").exists():
        return "1000" + coin[1:]
    return coin


def load_binance_pair(coin: str):
    b = binance_name(coin)
    fut = BN / "futures" / f"{b}_USDT_USDT-1d-futures.feather"
    if not fut.exists():
        return None
    p = pd.read_feather(fut).set_index("date")
    p = p[(p["close"] > 0) & (p["volume"] > 0)]
    fr = BN / "futures" / f"{b}_USDT_USDT-1h-funding_rate.feather"
    if fr.exists():
        r = pd.read_feather(fr)
        r = r[r["volume"] > 0].set_index("date")["close"]
        p["funding"] = r.resample("1D").sum().reindex(p.index).fillna(0.0)
    else:
        p["funding"] = 0.0
    s = BN / f"{b}_USDT-1d.feather"
    spot = pd.read_feather(s).set_index("date")["close"] if s.exists() else None
    return p, spot


def listings(dfs) -> pd.DataFrame:
    """first daily candle = listing; coins already trading in the first week of HL data are excluded"""
    first = min(d.index[0] for d in dfs.values())
    rows = [(c, d.index[0]) for c, d in dfs.items() if d.index[0] > first + pd.Timedelta(days=7)]
    r = pd.DataFrame(rows, columns=["base", "listed"])
    r["split"] = r["listed"].map(split_of)
    return r.dropna(subset=["split"])


# ------------------------------------------------------------------ HL-B rotation engine
def rotation(R_pos, R_neg, sig, enter, exit_, cost, slots=10, cap_mult=2.0, two_sided=True):
    """Daily rotation into up to `slots` delta-neutral positions.
    R_pos / R_neg: return of the position taken when sig > 0 / sig < 0 (per unit notional, day t).
    Signal known at the close of day t, position earns day t+1.  cost: per-coin cost of ONE side
    (open or close) of the whole position, as a fraction of notional."""
    idx = sig.index
    alive = (R_pos.notna() & R_neg.notna()) if two_sided else R_pos.notna()
    tradable = alive & alive.shift(-1, fill_value=False)
    held: dict[str, int] = {}
    eq, curve, trades, acc = 1.0, [], [], {}
    for i, t in enumerate(idx[:-1]):
        nxt = idx[i + 1]
        st = sig.loc[t]
        for b, dirn in list(held.items()):
            s_now = st.get(b, np.nan)
            if not tradable.at[t, b] or not np.isfinite(s_now) or dirn * s_now < exit_:
                held.pop(b)
                eq -= eq / slots / cap_mult * cost[b]
                trades.append(dict(base=b, ret=acc.pop(b) - cost[b], split=split_of(t)))
        if len(held) < slots:
            mag = st.abs() if two_sided else st
            ok = tradable.loc[t] & (mag >= enter)
            cand = mag[ok].drop(list(held), errors="ignore").sort_values(ascending=False)
            for b in cand.index[: slots - len(held)]:
                held[b] = 1 if st[b] > 0 else -1
                eq -= eq / slots / cap_mult * cost[b]
                acc[b] = -cost[b]
        day = 0.0
        for b, dirn in held.items():
            r = R_pos.at[nxt, b] if dirn > 0 else R_neg.at[nxt, b]
            r = 0.0 if not np.isfinite(r) else float(r)
            acc[b] += r
            day += r
        eq *= 1 + day / slots / cap_mult
        curve.append((nxt, eq))
    return pd.Series(dict(curve)), pd.DataFrame(trades)


def hl_b(perps, top50):
    rows_b1, rows_b2 = {}, {}
    for c, h in perps.items():
        bn = load_binance_pair(c)
        if bn is None:
            continue
        p, spot = bn
        df = pd.concat([h["close"].rename("P_hl"), h["funding"].rename("F_hl"),
                        p["close"].rename("P_bn"), p["funding"].rename("F_bn")], axis=1)
        if spot is not None:
            df["S_bn"] = spot
        rows_b1[c] = df
    if not rows_b1:
        print("  no coin listed on both HL and Binance in the data")
        return
    idx = pd.date_range(min(d.index[0] for d in rows_b1.values()), max(d.index[-1] for d in rows_b1.values()),
                        freq="D", tz="UTC")
    panel = {k: pd.DataFrame({c: d[k] for c, d in rows_b1.items() if k in d}).reindex(idx)
             for k in ("P_hl", "F_hl", "P_bn", "F_bn", "S_bn")}
    r_hl = panel["P_hl"].pct_change(fill_method=None)
    r_bn = panel["P_bn"].pct_change(fill_method=None)
    slip = pd.Series({c: 0.0005 if binance_name(c) in top50 or c in top50 else 0.002 for c in rows_b1})

    print(f"  coins on both venues: {len(rows_b1)}")
    diff = panel["F_hl"] - panel["F_bn"]
    sig = diff.rolling(3, min_periods=3).mean() * 365
    R_pos = r_bn - r_hl + diff            # short HL perp, long Binance perp
    R_neg = r_hl - r_bn - diff            # long HL perp, short Binance perp
    cost = F_HL_PERP + F_BN_PERP + 2 * slip
    eq, tr = rotation(R_pos, R_neg, sig, 0.15, 0.03, cost)
    report("B1 cross-venue funding (HL vs Binance perps)  [PRIMARY]", eq, tr)
    eq.to_frame("equity").reset_index(names="date").to_feather(OUT / "hl_b1_equity.feather")
    print(f"     mean |funding diff| annualised: {(diff.abs().mean().mean() * 365) * 100:.1f}%")

    sig2 = panel["F_hl"].rolling(3, min_periods=3).mean() * 365
    R2 = panel["S_bn"].pct_change(fill_method=None) - r_hl + panel["F_hl"]
    cost2 = F_BN_SPOT + F_HL_PERP + 2 * slip
    eq2, tr2 = rotation(R2, R2 * np.nan, sig2, 0.15, 0.03, cost2, two_sided=False)
    report("B2 HL carry (long Binance spot, short HL perp)", eq2, tr2)
    print(f"     mean HL funding annualised: {panel['F_hl'].mean().mean() * 365 * 100:.1f}% "
          f"vs Binance {panel['F_bn'].mean().mean() * 365 * 100:.1f}% (same coins)")


def report(name, eq, tr):
    print(f"  {name}")
    for k, (a, b) in SPLITS.items():
        x = tr[tr["split"] == k]["ret"] if len(tr) else pd.Series(dtype=float)
        print(f"     {k:8s} {L.stats(eq, a, b)}  trades {len(x)}  "
              f"win {np.mean(x > 0) * 100 if len(x) else float('nan'):.0f}%  mean {x.mean() * 100 if len(x) else float('nan'):+.2f}%")
    print(f"     full {L.stats(eq, str(eq.index[0].date()), str(eq.index[-1].date()))}")


# ------------------------------------------------------------------ HL-C / HL-D listings
def first_entry(kind: str, name: str, d: pd.DataFrame):
    """entry = close of the first hour if hourly data covers the listing, else close of day 0"""
    h = HL / kind / f"{name}-1h.feather"
    if h.exists():
        x = pd.read_feather(h)
        x = x[x["volume"] > 0]
        if len(x) and x["date"].iloc[0].floor("D") == d.index[0]:
            return float(x["close"].iloc[0]), "1h"
    return float(d["close"].iloc[0]), "1d"


def snipe(dfs, lst, kind, fee, slip, horizons=(1, 7, 30)):
    rows, c = [], fee + slip
    for _, r in lst.iterrows():
        d = dfs[r["base"]]
        px, src = first_entry(kind, r["base"], d)
        for h in horizons:
            if len(d) > h:
                rows.append(dict(base=r["base"], split=r["split"], h=h, src=src,
                                 ret=d["close"].iloc[h] * (1 - c) / (px * (1 + c)) - 1))
    s = pd.DataFrame(rows)
    if s.empty:
        print("   no listings")
        return
    g = s.groupby(["h", "split"])["ret"]
    t = pd.DataFrame({"n": g.size(), "mean%": (g.mean() * 100).round(1), "median%": (g.median() * 100).round(1),
                      "win%": (g.apply(lambda x: (x > 0).mean()) * 100).round(0),
                      "p": g.apply(lambda x: round(L.signflip_p(x.to_numpy()), 3))})
    print(t.unstack("split").to_string())
    print(f"   entry price source: {s.drop_duplicates('base')['src'].value_counts().to_dict()}")


def main():
    OUT.mkdir(exist_ok=True)
    pd.set_option("display.width", 250)
    meta = json.loads((HL / "meta.json").read_text())
    spot_meta = json.loads((HL / "spot_meta.json").read_text())
    print("=== HL-A options")
    names = [u["name"] for u in meta["universe"]] + [u["name"] for u in spot_meta["universe"]]
    opt = [n for n in names if any(k in n.upper() for k in ("-C", "-P", "CALL", "PUT", "OPTION"))]
    print(f"  {len(meta['universe'])} perps, {len(spot_meta['universe'])} spot pairs; "
          f"option-like instruments: {opt if opt else 'none'}")

    perps, spot = load_hl_perps(), load_hl_spot()
    top50 = {p.split("/")[0].removesuffix("CARRY") for p in json.load(open("configs/pairs_carry.json"))}
    print(f"\n=== HL-B multi-coin funding arbitrage ({len(perps)} HL perps with data)")
    hl_b(perps, top50)

    L.SPLITS = SPLITS                       # listing_lab.fade tags trades with these splits
    print("\n=== HL-C new HL perp listings")
    lp = listings(perps)
    print(f"  listings: {lp['split'].value_counts().to_dict()}")
    print("  C1 snipe long (0.045 % fee + 0.5 % slippage per side)")
    snipe(perps, lp, "perp", F_HL_PERP, 0.005)
    end = str(end_of_data(perps).date())
    eq, tr = L.fade(perps, lp, 1, 30, 1.0, 0.05, F_HL_PERP, 0.005, start=str(lp["listed"].min().date()), end=end)
    print("  C2 fade short (d=1, H=30, stop +100 %, 5 % per listing, funding included)")
    for k, (a, b) in SPLITS.items():
        x = tr[tr["split"] == k]["ret"].to_numpy() if len(tr) else np.array([])
        if len(x):
            print(f"     {k:8s} trades {len(x)}  mean {x.mean() * 100:+.2f}%  win {np.mean(x > 0) * 100:.0f}%  "
                  f"p {L.signflip_p(x):.3f} | {L.stats(eq, a, b)}")

    print("\n=== HL-D HIP-1 spot token launches: snipe long (0.07 % fee + 1 % slippage per side)")
    ls_ = listings(spot)
    print(f"  launches: {ls_['split'].value_counts().to_dict()}")
    snipe(spot, ls_, "spot", F_HL_SPOT, 0.01)


if __name__ == "__main__":
    main()
