#!/usr/bin/env python3
"""
Summarise a Freqtrade backtest result (zip) with the metrics this project targets:
win-rate, max drawdown (closed trades and mark-to-market wallet), CAGR, profit
factor, yearly breakdown and share of positive months.

    python research/analyze.py                       # latest result
    python research/analyze.py path/to/result.zip    # specific result
    python research/analyze.py --plot equity.png     # also save an equity curve
"""
from __future__ import annotations

import argparse
import glob
import io
import json
import os
import zipfile

import numpy as np
import pandas as pd

RESULTS = "user_data/backtest_results"


def latest_zip() -> str:
    return sorted(glob.glob(f"{RESULTS}/*.zip"), key=os.path.getmtime)[-1]


def load(path: str) -> dict[str, dict]:
    """Return {strategy: {"stats": dict, "trades": DataFrame, "wallet": DataFrame|None}}."""
    z = zipfile.ZipFile(path)
    main = [n for n in z.namelist() if n.endswith(".json") and "_config" not in n][0]
    data = json.loads(z.read(main))
    out = {}
    for name, st in data["strategy"].items():
        t = pd.DataFrame(st["trades"])
        if not t.empty:
            t["open_date"] = pd.to_datetime(t["open_date"], utc=True)
            t["close_date"] = pd.to_datetime(t["close_date"], utc=True)
        wallet = None
        wn = [n for n in z.namelist() if n.endswith(f"_{name}_wallet.feather")]
        if wn:
            wallet = pd.read_feather(io.BytesIO(z.read(wn[0])))
        out[name] = {"stats": st, "trades": t, "wallet": wallet}
    return out


def closed_equity(st: dict, t: pd.DataFrame) -> pd.Series:
    start = st["starting_balance"]
    if t.empty:
        return pd.Series([start])
    eq = start + t.sort_values("close_date").set_index("close_date")["profit_abs"].cumsum()
    return eq


def max_dd(eq: pd.Series) -> float:
    return float((1 - eq / eq.cummax()).max())


def mtm_equity(st: dict, t: pd.DataFrame, datadir: str = "user_data/data/binance") -> pd.Series | None:
    """Hourly mark-to-market equity rebuilt from trades + candle closes (spot, long-only).

    Independent of freqtrade's wallet series, which loses the stake of trades whose
    pair data ends before the backtest end (delisted / migrated coins).
    """
    if t.empty or st.get("trading_mode", "spot") != "spot" or (t.get("is_short", False) is True):
        return None
    start = pd.Timestamp(st["backtest_start"], tz="UTC")
    end = pd.Timestamp(st["backtest_end"], tz="UTC")
    idx = pd.date_range(start, end, freq=st.get("timeframe", "1h").replace("m", "min"))
    eq = pd.Series(float(st["starting_balance"]), index=idx)
    for _, tr in t.iterrows():
        # realised P&L from the close time on
        eq[eq.index >= tr["close_date"]] += tr["profit_abs"]
        # unrealised P&L while open
        f = os.path.join(datadir, f"{tr['pair'].replace('/', '_')}-{st.get('timeframe', '1h')}.feather")
        if not os.path.exists(f):
            continue
        px = pd.read_feather(f).set_index("date")["close"]
        # candle close of date d is known at d + timeframe
        px.index = px.index + pd.Timedelta(st.get("timeframe", "1h").replace("m", "min"))
        win = (eq.index >= tr["open_date"]) & (eq.index < tr["close_date"])
        if not win.any():
            continue
        p = px.reindex(eq.index[win], method="ffill").fillna(tr["open_rate"])
        fee = tr.get("fee_open", 0.0) or 0.0
        unreal = tr["amount"] * p.values * (1 - fee) - tr["stake_amount"] * (1 + fee)
        eq.loc[win] += unreal
    return eq


def summarize(name: str, res: dict) -> dict:
    st, t, w = res["stats"], res["trades"], res["wallet"]
    eq = closed_equity(st, t)
    # daily closed-trade equity (for monthly / yearly stats)
    days = pd.date_range(pd.Timestamp(st["backtest_start"], tz="UTC").normalize(),
                         pd.Timestamp(st["backtest_end"], tz="UTC").normalize(), freq="D")
    daily = eq.groupby(eq.index.normalize()).last().reindex(days).ffill().fillna(st["starting_balance"])
    monthly = daily.resample("ME").last().pct_change().fillna(daily.resample("ME").last().iloc[0] / st["starting_balance"] - 1)
    yearly = daily.resample("YE").last()
    yearly_ret = yearly.pct_change()
    yearly_ret.iloc[0] = yearly.iloc[0] / st["starting_balance"] - 1
    wallet_dd = None
    if w is not None and not w.empty:
        # one row per currency and candle -> total equity marked to market
        wv = w.groupby("date")["total_quote"].sum()
        wallet_dd = max_dd(wv)
    mtm = mtm_equity(st, t)
    mtm_dd = None if mtm is None else max_dd(mtm)
    # daily-return Sharpe on closed equity
    dr = daily.pct_change().dropna()
    sharpe = float(dr.mean() / dr.std() * np.sqrt(365)) if dr.std() > 0 else np.nan
    return {
        "strategy": name,
        "trades": int(st["total_trades"]),
        "win_rate": round(st["winrate"] * 100, 1),
        "profit_%": round(st["profit_total"] * 100, 1),
        # CAGR from total profit (freqtrade's own field relies on final_balance)
        "cagr_%": round(((1 + st["profit_total"]) ** (365 / max(1, st["backtest_days"])) - 1) * 100, 1),
        "max_dd_%": round(st["max_drawdown_account"] * 100, 1),
        "wallet_dd_%": None if wallet_dd is None else round(wallet_dd * 100, 1),
        "mtm_dd_%": None if mtm_dd is None else round(mtm_dd * 100, 1),
        "profit_factor": round(st["profit_factor"], 2),
        "sharpe_daily": round(sharpe, 2),
        "pos_months_%": round(float((monthly > 0).sum() / max(1, (monthly != 0).sum())) * 100, 1),
        "worst_month_%": round(monthly.min() * 100, 1),
        "yearly_%": {str(k.year): round(v * 100, 1) for k, v in yearly_ret.items()},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?")
    ap.add_argument("--plot")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    path = a.path or latest_zip()
    res = load(path)
    rows = [summarize(n, r) for n, r in res.items()]
    if a.json:
        print(json.dumps(rows, indent=2))
    else:
        for r in rows:
            print(r)
    if a.plot:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(11, 4.5))
        for n, r in res.items():
            eq = closed_equity(r["stats"], r["trades"])
            ax.plot(eq.index, eq.values, label=n, lw=1.4)
        ax.set_title("Closed-trade equity (USDT)")
        ax.grid(alpha=0.3)
        ax.legend()
        fig.tight_layout()
        fig.savefig(a.plot, dpi=110)


if __name__ == "__main__":
    main()
