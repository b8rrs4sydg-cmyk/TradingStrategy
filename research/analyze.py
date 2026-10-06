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
    # daily-return Sharpe on closed equity
    dr = daily.pct_change().dropna()
    sharpe = float(dr.mean() / dr.std() * np.sqrt(365)) if dr.std() > 0 else np.nan
    return {
        "strategy": name,
        "trades": int(st["total_trades"]),
        "win_rate": round(st["winrate"] * 100, 1),
        "profit_%": round(st["profit_total"] * 100, 1),
        "cagr_%": round(st["cagr"] * 100, 1),
        "max_dd_%": round(st["max_drawdown_account"] * 100, 1),
        "wallet_dd_%": None if wallet_dd is None else round(wallet_dd * 100, 1),
        "profit_factor": round(st["profit_factor"], 2),
        "sharpe_daily": round(sharpe, 2),
        "pos_months_%": round((monthly > 0).sum() / max(1, (monthly != 0).sum()) * 100, 1),
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
