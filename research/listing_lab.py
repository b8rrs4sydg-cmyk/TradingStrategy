#!/usr/bin/env python3
"""
New-listing ("CEX meme sniping") and small-cap funding-carry tests, exactly as pre-registered in
research/PREREG_listing_smallcap.md (committed before any result was computed).

    python research/listing_lab.py            # H1 snipe, H2 fade (primary + grid), H3 small-cap carry
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path("user_data/data/binance")
OUT = Path("research/results")
SPLITS = {"IS": ("2020-01-01", "2023-12-31"), "OOS": ("2024-01-01", "2025-06-30"),
          "HOLDOUT": ("2025-07-01", "2026-09-30")}
# first month of each download: a first candle on these days means "already trading", not a listing
NOT_LISTING = {pd.Timestamp("2017-08-01", tz="UTC"), pd.Timestamp("2019-09-01", tz="UTC"),
               pd.Timestamp("2020-01-01", tz="UTC")}
STABLE = {"USDC", "BUSD", "TUSD", "FDUSD", "USDP", "DAI", "PAX", "EUR", "GBP", "AUD", "USDS", "USDE",
          "AEUR", "EURI", "XUSD", "USD1", "BFUSD", "PAXG", "WBTC", "WBETH", "BETH"}


def split_of(ts) -> str | None:
    for k, (a, b) in SPLITS.items():
        if pd.Timestamp(a, tz="UTC") <= ts <= pd.Timestamp(b, tz="UTC") + pd.Timedelta(hours=23):
            return k
    return None


def skip_base(b: str) -> bool:
    return b in STABLE or b.endswith(("UP", "DOWN", "BULL", "BEAR"))


def load_perps() -> dict[str, pd.DataFrame]:
    out = {}
    for f in sorted((DATA / "futures").glob("*_USDT_USDT-1d-futures.feather")):
        b = f.name.split("_USDT_USDT")[0]
        if skip_base(b):
            continue
        d = pd.read_feather(f).set_index("date")[["open", "high", "low", "close", "volume"]]
        # after a perp is delisted the archive repeats a frozen last price with zero volume;
        # the contract is really settled at the index (~spot), so those rows must not be traded
        d = d[(d["close"] > 0) & (d["volume"] > 0)]
        if len(d) < 2:
            continue
        fr = DATA / "futures" / f"{b}_USDT_USDT-1h-funding_rate.feather"
        if fr.exists():
            r = pd.read_feather(fr)
            r = r[r["volume"] > 0].set_index("date")["close"]
            d["funding"] = r.resample("1D").sum().reindex(d.index).fillna(0.0)
        else:
            d["funding"] = 0.0
        out[b] = d
    return out


def load_spot() -> dict[str, pd.DataFrame]:
    out = {}
    for f in sorted(DATA.glob("*_USDT-1d.feather")):
        b = f.name.split("_USDT-1d")[0]
        if skip_base(b) or "CARRY" in b or "BASIS" in b:
            continue
        d = pd.read_feather(f).set_index("date")[["open", "high", "low", "close", "volume"]]
        d = d[d["close"] > 0]
        if len(d) >= 2:
            out[b] = d
    return out


def listings(dfs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = [(b, d.index[0]) for b, d in dfs.items() if d.index[0] not in NOT_LISTING]
    r = pd.DataFrame(rows, columns=["base", "listed"])
    r["split"] = r["listed"].map(split_of)
    return r.dropna(subset=["split"])


# ---------------------------------------------------------------- H1 snipe long
def snipe(dfs, lst, fee, slip, horizons=(0, 1, 3, 7, 30)):
    rows = []
    c = fee + slip
    for _, L in lst.iterrows():
        d = dfs[L["base"]]
        p0 = d["open"].iloc[0] * (1 + c)
        for h in horizons:
            if len(d) > h:
                rows.append(dict(base=L["base"], split=L["split"], h=h,
                                 ret=d["close"].iloc[h] * (1 - c) / p0 - 1))
    return pd.DataFrame(rows)


def signflip_p(x: np.ndarray, n: int = 20000, seed: int = 0) -> float:
    """one-sided p-value that the mean of x is > 0 (sign-flip permutation)"""
    x = np.asarray(x, float)
    if len(x) < 5:
        return np.nan
    rng = np.random.default_rng(seed)
    obs = x.mean()
    sims = (rng.choice([-1.0, 1.0], size=(n, len(x))) * np.abs(x)).mean(axis=1)
    return float((sims >= obs).mean())


def listing_minutes(market: str, base: str, day: pd.Timestamp) -> pd.DataFrame | None:
    """1-minute klines of the listing day (cached); market 'spot' or 'futures'."""
    cache = DATA / "listing1m" / f"{market}_{base}.feather"
    if cache.exists():
        return pd.read_feather(cache)
    import io
    import zipfile
    from urllib.request import Request, urlopen
    sym = f"{base}USDT"
    path = "data/spot/daily/klines" if market == "spot" else "data/futures/um/daily/klines"
    url = (f"https://s3.ap-northeast-1.amazonaws.com/data.binance.vision/{path}/{sym}/1m/"
           f"{sym}-1m-{day:%Y-%m-%d}.zip")
    try:
        with urlopen(Request(url, headers={"User-Agent": "listing-lab"}), timeout=60) as r:
            raw = r.read()
    except Exception:  # noqa: BLE001
        return None
    with zipfile.ZipFile(io.BytesIO(raw)) as zf, zf.open(zf.namelist()[0]) as fh:
        d = pd.read_csv(fh, header=None)
    if not str(d.iloc[0, 0]).isdigit():
        d = d.iloc[1:]
    d = d.iloc[:, :6].astype(float)
    d.columns = ["date", "open", "high", "low", "close", "volume"]
    ts = d["date"].astype("int64")
    d["date"] = pd.to_datetime(ts.where(ts < 10**14, ts // 1000), unit="ms", utc=True)
    d = d[d["volume"] > 0].reset_index(drop=True)          # start at the first real trade
    cache.parent.mkdir(exist_ok=True)
    d.to_feather(cache)
    return d


def snipe_minutes(dfs, lst, market, fee, slip, entries=(1, 5, 60), horizons=(0, 1, 3, 7, 30)):
    """Amendment 1: enter at the close of minute k after the first trade, exit at daily closes."""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(16) as ex:
        mins = dict(zip(lst["base"], ex.map(lambda r: listing_minutes(market, r[0], r[1]),
                                            zip(lst["base"], lst["listed"]))))
    rows, c = [], fee + slip
    for _, L in lst.iterrows():
        m, d = mins.get(L["base"]), dfs[L["base"]]
        if m is None or len(m) < max(entries):
            continue
        for k in entries:
            p0 = m["close"].iloc[k - 1] * (1 + c)
            for h in horizons:
                if len(d) > h:
                    rows.append(dict(base=L["base"], split=L["split"], entry_min=k, h=h,
                                     ret=d["close"].iloc[h] * (1 - c) / p0 - 1))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- H2 fade (short) portfolio
def fade(perps, lst, d_entry=1, hold=30, stop=1.0, w=0.05, fee=0.0005, slip=0.002, stop_slip=0.01):
    """Daily mark-to-market portfolio of short positions in newly listed perps."""
    events = {}
    for _, L in lst.iterrows():
        d = perps[L["base"]]
        if len(d) > d_entry + 1:
            events.setdefault(d.index[d_entry], []).append(L["base"])
    days = pd.date_range("2020-01-01", "2026-09-30", freq="D", tz="UTC")
    cash, pos, curve, trades = 1.0, [], [], []
    c = fee + slip
    for t in days:
        still = []
        for p in pos:
            d = perps[p["base"]]
            if t not in d.index:
                if t > d.index[-1]:                     # delisted / data ended: close at last close
                    pnl = p["n"] * (1 - d["close"].iloc[-1] * (1 + c) / p["px"])
                    cash += pnl
                    trades.append(dict(base=p["base"], split=p["split"], ret=pnl / p["n"] + p["fr"], why="ended"))
                    continue
                still.append(p)
                continue
            row = d.loc[t]
            # funding: the short receives rate x current notional
            f = row["funding"] * p["n"] * row["close"] / p["px"]
            cash += f
            p["fr"] += f / p["n"]
            stop_px = p["px"] * (1 + stop) if stop is not None else p["px"] * 1.9    # 1x: liquidation ~+90 %
            if row["high"] >= stop_px:
                pnl = p["n"] * (1 - stop_px * (1 + stop_slip + c) / p["px"])
                cash += pnl
                trades.append(dict(base=p["base"], split=p["split"], ret=pnl / p["n"] + p["fr"], why="stop"))
                continue
            if t >= p["exit"]:
                pnl = p["n"] * (1 - row["close"] * (1 + c) / p["px"])
                cash += pnl
                trades.append(dict(base=p["base"], split=p["split"], ret=pnl / p["n"] + p["fr"], why="time"))
                continue
            p["last"] = row["close"]
            still.append(p)
        pos = still
        eq = cash + sum(p["n"] * (1 - p["last"] / p["px"]) for p in pos)
        for b in events.get(t, []):
            px = perps[b].loc[t, "close"] * (1 - c)
            pos.append(dict(base=b, split=split_of(perps[b].index[0]), px=px, last=px / (1 - c), n=w * eq,
                            exit=t + pd.Timedelta(days=hold), fr=0.0))
        curve.append((t, eq))
    eq = pd.Series(dict(curve))
    return eq, pd.DataFrame(trades)


def stats(eq: pd.Series, a: str, b: str) -> dict:
    e = eq[(eq.index >= pd.Timestamp(a, tz="UTC")) & (eq.index <= pd.Timestamp(b, tz="UTC"))]
    if len(e) < 30:
        return {}
    r = e.pct_change().dropna()
    yrs = len(e) / 365
    return dict(cagr=round(((e.iloc[-1] / e.iloc[0]) ** (1 / yrs) - 1) * 100, 1),
                mdd=round(float((1 - e / e.cummax()).max()) * 100, 1),
                sharpe=round(float(r.mean() / r.std() * np.sqrt(365)) if r.std() > 0 else 0.0, 2))


# ---------------------------------------------------------------- H3 small-cap funding carry
def smallcap_carry(perps, spot, top50, enter=0.20, exit_=0.05, slots=10, cap_mult=2.0,
                   fee_spot=0.0015, fee_perp=0.0005, slip_small=0.003):
    bases = sorted(set(perps) & set(spot))
    idx = pd.date_range("2020-01-01", "2026-09-30", freq="D", tz="UTC")
    S = pd.DataFrame({b: spot[b]["close"] for b in bases}).reindex(idx)
    P = pd.DataFrame({b: perps[b]["close"] for b in bases}).reindex(idx)
    F = pd.DataFrame({b: perps[b]["funding"] for b in bases}).reindex(idx)
    R = (S.pct_change(fill_method=None) - P.pct_change(fill_method=None) + F)       # carry return day t
    sig = F.rolling(3, min_periods=3).mean() * 365                                   # funding/day x 365
    alive = S.notna() & P.notna()
    # a coin is tradable on day t only if both legs trade on t AND t+1 (no closing into a gap)
    tradable = alive & alive.shift(-1, fill_value=False)
    cost_side = pd.Series({b: fee_spot + fee_perp + (0 if b in top50 else 2 * slip_small) for b in bases})
    held: set[str] = set()
    eq, curve, trades, open_ = 1.0, [], [], {}
    for i, t in enumerate(idx[:-1]):
        nxt = idx[i + 1]
        # exits
        for b in list(held):
            if not tradable.at[t, b] or sig.at[t, b] < exit_:
                held.discard(b)
                eq -= eq / slots / cap_mult * cost_side[b]
                trades.append(dict(base=b, ret=open_.pop(b) - cost_side[b], split=split_of(t)))
        # entries
        if len(held) < slots:
            cand = sig.loc[t][tradable.loc[t] & (sig.loc[t] >= enter)].drop(list(held), errors="ignore")
            for b in cand.sort_values(ascending=False).index[: slots - len(held)]:
                held.add(b)
                eq -= eq / slots / cap_mult * cost_side[b]
                open_[b] = -cost_side[b]
        # P&L of day t+1 for held positions: each slot = eq/slots capital, notional = capital/cap_mult
        r = R.loc[nxt, list(held)].fillna(0.0) if held else pd.Series(dtype=float)
        for b in held:
            open_[b] += float(r.get(b, 0.0))
        eq *= 1 + float(r.sum()) / slots / cap_mult
        curve.append((nxt, eq))
    return pd.Series(dict(curve)), pd.DataFrame(trades)


def main():
    OUT.mkdir(exist_ok=True)
    perps, spot = load_perps(), load_spot()
    lp, ls_ = listings(perps), listings(spot)
    print(f"perps loaded {len(perps)}, new perp listings {len(lp)}: {lp['split'].value_counts().to_dict()}")
    print(f"spot  loaded {len(spot)}, new spot listings {len(ls_)}: {ls_['split'].value_counts().to_dict()}")

    print("\n=== H1 snipe long: buy the first print, sell at close of day h (costs incl. 0.5 % slippage/side)")
    for name, dfs, lst, fee in (("spot", spot, ls_, 0.001), ("perp", perps, lp, 0.0005)):
        s = snipe(dfs, lst, fee, 0.005)
        g = s.groupby(["split", "h"])["ret"]
        t = pd.DataFrame({"n": g.size(), "mean%": (g.mean() * 100).round(1), "median%": (g.median() * 100).round(1),
                          "win%": (g.apply(lambda x: (x > 0).mean()) * 100).round(0)})
        print(f"-- {name}\n{t.unstack('split').to_string()}")
    print("\n=== H1 (amendment 1): enter at the close of minute 1 / 5 / 60 after the first trade")
    for name, dfs, lst, fee, mk in (("spot", spot, ls_, 0.001, "spot"), ("perp", perps, lp, 0.0005, "futures")):
        s = snipe_minutes(dfs, lst, mk, fee, 0.005)
        g = s.groupby(["entry_min", "h", "split"])["ret"]
        t = pd.DataFrame({"n": g.size(), "mean%": (g.mean() * 100).round(1), "median%": (g.median() * 100).round(1),
                          "win%": (g.apply(lambda x: (x > 0).mean()) * 100).round(0),
                          "p": g.apply(lambda x: round(signflip_p(x.to_numpy()), 3))})
        print(f"-- {name}\n{t.unstack('split').to_string()}")

    print("\n=== H2 fade new perp listings (short).  PRIMARY: d=1, H=30, stop=100 %, w=5 %")
    eq, tr = fade(perps, lp)
    eq.to_frame("equity").reset_index(names="date").to_feather(OUT / "listing_fade_primary_equity.feather")
    for k, (a, b) in SPLITS.items():
        x = tr[tr["split"] == k]["ret"].to_numpy()
        print(f"  {k:8s} trades {len(x):4d}  mean {x.mean() * 100:+.2f}%  median {np.median(x) * 100:+.2f}%  "
              f"win {np.mean(x > 0) * 100:.0f}%  p(sign-flip) {signflip_p(x):.3f}  | portfolio {stats(eq, a, b)}")
    print(f"  exits: {tr['why'].value_counts().to_dict()}")

    print("\n  sensitivity grid (portfolio CAGR / MDD per split, same w=5 %):")
    rows = []
    for d_entry in (0, 1, 3):
        for hold in (7, 14, 30, 60):
            for stop in (0.5, 1.0, None):
                e, t2 = fade(perps, lp, d_entry, hold, stop)
                r = dict(d=d_entry, H=hold, stop=stop if stop is not None else "none")
                for k, (a, b) in SPLITS.items():
                    s2 = stats(e, a, b)
                    x = t2[t2["split"] == k]["ret"]
                    r[f"{k}_cagr"], r[f"{k}_mdd"], r[f"{k}_mean%"] = s2.get("cagr"), s2.get("mdd"), round(x.mean() * 100, 2)
                rows.append(r)
    grid = pd.DataFrame(rows)
    pd.set_option("display.width", 250)
    print(grid.to_string(index=False))

    print("\n=== H3 small-cap funding carry (all coins with spot + perp; enter 20 %, exit 5 %, 10 slots, 2x capital)")
    top50 = {p.split("/")[0].removesuffix("CARRY") for p in json.load(open("configs/pairs_carry.json"))}
    eq3, tr3 = smallcap_carry(perps, spot, top50)
    eq3.to_frame("equity").reset_index(names="date").to_feather(OUT / "smallcap_carry_equity.feather")
    for k, (a, b) in SPLITS.items():
        x = tr3[tr3["split"] == k]["ret"]
        print(f"  {k:8s} {stats(eq3, a, b)}  trades {len(x)}  win {np.mean(x > 0) * 100:.0f}%  "
              f"mean trade {x.mean() * 100:+.2f}%")
    print(f"  full {stats(eq3, '2020-01-01', '2026-09-30')}")
    small = tr3[~tr3["base"].isin(top50)]
    print(f"  share of trades outside the top-50: {len(small) / max(len(tr3), 1) * 100:.0f}%")


if __name__ == "__main__":
    main()
