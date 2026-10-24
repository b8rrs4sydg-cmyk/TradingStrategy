#!/usr/bin/env python3
"""
Monte-Carlo robustness tests for the long/short portfolio strategy.

1. bootstrap  : stationary block bootstrap (20-day blocks) of the strategy's DAILY
                mark-to-market returns from a Freqtrade result -> distribution of
                CAGR / MDD / Sharpe.  Blocks keep volatility clustering and the
                correlation between simultaneously open positions.
2. permutation: "is the edge real?"  Each coin's signal is circularly shifted by a
                random offset (same signal statistics, turnover and vol targeting,
                but the alignment with future returns is destroyed).  p-value =
                share of random strategies with Sharpe >= the real one.
3. jitter     : every parameter drawn at random from a wide range at once
                -> distribution of results (no single lucky parameter set).

Tests 2 and 3 use the vectorised model in ls_lab.py (thousands of runs are not
feasible with full Freqtrade backtests); its daily returns track the Freqtrade
implementation with a correlation of ~0.95.

    python research/mc_ls.py bootstrap research/results/ls_full.zip
    python research/mc_ls.py permutation --start 2020-06-01 --end 2024-01-01
    python research/mc_ls.py jitter --start 2020-06-01 --end 2024-01-01
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import ls_lab  # noqa: E402
from analyze import load, mtm_equity_orders  # noqa: E402


def perf(r: np.ndarray) -> tuple[float, float, float]:
    eq = np.cumprod(1 + r)
    cagr = eq[-1] ** (365 / len(r)) - 1
    mdd = float(np.max(1 - eq / np.maximum.accumulate(eq)))
    sh = float(r.mean() / r.std() * np.sqrt(365)) if r.std() > 0 else 0.0
    return cagr, mdd, sh


def q(x, p):
    return round(float(np.quantile(x, p)) * 100, 1)


def bootstrap(path: str, runs: int, block: int, seed: int):
    res = load(path)
    rng = np.random.default_rng(seed)
    for name, r in res.items():
        eq = mtm_equity_orders(r["stats"], r["trades"])
        ret = eq.resample("D").last().pct_change().dropna().to_numpy()
        n = len(ret)
        out = np.empty((runs, 3))
        for k in range(runs):
            idx = []
            while len(idx) < n:
                s = rng.integers(0, n)
                L = rng.geometric(1 / block)
                idx.extend((s + np.arange(L)) % n)
            out[k] = perf(ret[np.array(idx[:n])])
        c, m, s = out.T
        real = perf(ret)
        print(f"{name}: {n} days, {runs} block-bootstrap paths (mean block {block}d)")
        print(f"  real      : CAGR {real[0]*100:.1f}%  MDD {real[1]*100:.1f}%  Sharpe {real[2]:.2f}")
        print(f"  CAGR  %   : p5 {q(c,.05)}  median {q(c,.5)}  p95 {q(c,.95)}   P(CAGR>=15%) = {np.mean(c>=.15)*100:.1f}%  P(CAGR>0) = {np.mean(c>0)*100:.1f}%")
        print(f"  MDD   %   : median {q(m,.5)}  p90 {q(m,.9)}  p95 {q(m,.95)}   P(MDD<15%) = {np.mean(m<.15)*100:.1f}%")
        print(f"  Sharpe    : p5 {np.quantile(s,.05):.2f}  median {np.median(s):.2f}  p95 {np.quantile(s,.95):.2f}")


DEFAULTS3 = dict(trend_lbs=(10, 20, 40, 80, 160), xs_lbs=(14, 30, 60, 90), q=0.2,
                 carry_lbs=(3, 7, 14), vol_lb=60, tv=0.12)


def _signals(C, F, R, p):
    trend = ls_lab.ensemble_trend(C, R, p["trend_lbs"])
    xs = ls_lab.ensemble_xsmom(C, R, p["xs_lbs"], p["q"])
    carry = ls_lab.ensemble_xscarry(C, F, p["carry_lbs"], p["q"])
    return trend, xs, carry


def _book(C, F, sigs, p):
    w = sum(ls_lab.raw_weights(C, s) for s in sigs) / len(sigs)
    return ls_lab.vol_target(C, F, w, target_vol=p["tv"], lookback=p["vol_lb"])


def permutation(pairs_file, start, end, runs, seed):
    C, F = ls_lab.load_universe(pairs_file)
    C, F = C.loc[:end], F.loc[:end]
    R = C.pct_change(fill_method=None)
    p = dict(DEFAULTS3)
    sigs = _signals(C, F, R, p)
    real, _ = _book(C, F, sigs, p)
    real_sh = perf(real.loc[start:].to_numpy())[2]
    rng = np.random.default_rng(seed)
    n = len(C)
    sh = []
    for _ in range(runs):
        shifts = rng.integers(60, n - 60, size=C.shape[1])
        shuffled = []
        for sig in sigs:
            s2 = sig.copy()
            for j, off in enumerate(shifts):
                s2.iloc[:, j] = np.roll(sig.iloc[:, j].to_numpy(), off)
            shuffled.append(s2.where(C.notna()))
        r, _ = _book(C, F, shuffled, p)
        sh.append(perf(r.loc[start:].to_numpy())[2])
    sh = np.array(sh)
    pval = (np.sum(sh >= real_sh) + 1) / (runs + 1)
    print(f"permutation test {start}..{end}: real Sharpe {real_sh:.2f}")
    print(f"  random-alignment Sharpe: p50 {np.median(sh):.2f}  p95 {np.quantile(sh,.95):.2f}  p99 {np.quantile(sh,.99):.2f}  max {sh.max():.2f}")
    print(f"  p-value = {pval:.4f}  ({runs} runs)")


def jitter(pairs_file, start, end, runs, seed):
    C, F = ls_lab.load_universe(pairs_file)
    C, F = C.loc[:end], F.loc[:end]
    R = C.pct_change(fill_method=None)
    rng = np.random.default_rng(seed)
    rows = []
    for _ in range(runs):
        base = rng.uniform(5, 20)
        p = dict(
            trend_lbs=tuple(int(round(base * 2 ** k)) for k in range(5)),
            xs_lbs=tuple(sorted(set(int(x) for x in rng.uniform(7, 180, size=rng.integers(2, 6))))),
            q=float(rng.uniform(0.1, 0.35)),
            carry_lbs=tuple(sorted(set(int(x) for x in rng.uniform(1, 45, size=rng.integers(1, 4))))),
            vol_lb=int(rng.uniform(30, 120)),
            tv=0.12,
        )
        r, _ = _book(C, F, _signals(C, F, R, p), p)
        rows.append(perf(r.loc[start:].to_numpy()))
    c, m, s = np.array(rows).T
    print(f"parameter jitter {start}..{end}: {runs} random parameter sets (tv fixed 12%)")
    print(f"  CAGR %  : p5 {q(c,.05)}  median {q(c,.5)}  p95 {q(c,.95)}   share >0: {np.mean(c>0)*100:.0f}%")
    print(f"  MDD  %  : median {q(m,.5)}  p95 {q(m,.95)}")
    print(f"  Sharpe  : p5 {np.quantile(s,.05):.2f}  median {np.median(s):.2f}  p95 {np.quantile(s,.95):.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("test", choices=["bootstrap", "permutation", "jitter"])
    ap.add_argument("path", nargs="?")
    ap.add_argument("--pairs-file", default="configs/pairs_universe_futures.json")
    ap.add_argument("--start", default="2020-06-01")
    ap.add_argument("--end", default="2024-01-01")
    ap.add_argument("--runs", type=int, default=None)
    ap.add_argument("--block", type=int, default=20)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    if a.test == "bootstrap":
        bootstrap(a.path, a.runs or 5000, a.block, a.seed)
    elif a.test == "permutation":
        permutation(a.pairs_file, a.start, a.end, a.runs or 300, a.seed)
    else:
        jitter(a.pairs_file, a.start, a.end, a.runs or 200, a.seed)


if __name__ == "__main__":
    main()
