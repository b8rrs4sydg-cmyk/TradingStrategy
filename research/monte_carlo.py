#!/usr/bin/env python3
"""
Monte-Carlo robustness check of a backtest.

Resamples the trade sequence (bootstrap with replacement, compounding each
trade's return on its stake fraction) many times and reports the distribution
of max drawdown, final return and win-rate.  A backtest whose real MDD sits far
below the bootstrap median was probably lucky in its trade ordering.

    python research/monte_carlo.py [result.zip] --runs 5000
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from analyze import latest_zip, load  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?")
    ap.add_argument("--runs", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    res = load(a.path or latest_zip())
    rng = np.random.default_rng(a.seed)
    for name, r in res.items():
        t = r["trades"].sort_values("close_date")
        start = r["stats"]["starting_balance"]
        # equity impact of each trade as a fraction of the equity at that time
        eq_before = start + t["profit_abs"].cumsum().shift(fill_value=0)
        impact = (t["profit_abs"] / eq_before).to_numpy()
        n = len(impact)
        idx = rng.integers(0, n, size=(a.runs, n))
        paths = np.cumprod(1 + impact[idx], axis=1)
        peak = np.maximum.accumulate(np.concatenate([np.ones((a.runs, 1)), paths], axis=1), axis=1)[:, 1:]
        mdd = (1 - paths / peak).max(axis=1)
        final = paths[:, -1] - 1
        win = (impact[idx] > 0).mean(axis=1)
        q = lambda x, p: round(float(np.quantile(x, p)) * 100, 1)  # noqa: E731
        print(f"{name}: trades={n}  runs={a.runs}")
        print(f"  max drawdown %  median={q(mdd, .5)}  p90={q(mdd, .9)}  p95={q(mdd, .95)}  p99={q(mdd, .99)}"
              f"  P(MDD<15%)={round(float((mdd < .15).mean()) * 100, 1)}%")
        print(f"  total return %  p5={q(final, .05)}  median={q(final, .5)}  p95={q(final, .95)}"
              f"  P(return>0)={round(float((final > 0).mean()) * 100, 1)}%")
        print(f"  win rate %      p5={q(win, .05)}  median={q(win, .5)}  p95={q(win, .95)}"
              f"  P(win>60%)={round(float((win > .6).mean()) * 100, 1)}%")


if __name__ == "__main__":
    main()
