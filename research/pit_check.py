#!/usr/bin/env python3
"""
Point-in-time (lookahead) check for cross-sectional strategies.

freqtrade's `lookahead-analysis` re-runs each sliced backtest with ONLY the
analysed pair in the whitelist.  For rotation strategies (whose signals depend on
a ranking across all pairs) that changes the universe and produces false
positives.  This check keeps the whole universe:

  for random cut-off times T:
      truncate ALL pairs' candles and funding at T
      run the strategy's populate_indicators / entry / exit on the truncated data
      compare indicators and signals with the full-data run for candles <= T

Any difference means the strategy used information from after T.

    python research/pit_check.py --strategy FundingCarry --config configs/config_carry.json
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from freqtrade.data.history import load_pair_history
from freqtrade.enums import CandleType

sys.path.insert(0, "user_data/strategies")
DATADIR = Path("user_data/data/binance")


class StubDP:
    """Minimal DataProvider: serves data truncated at `cutoff` (inclusive of candle dates <= cutoff)."""

    def __init__(self, pairs, data, funding, cutoff=None):
        self.pairs, self.data, self.funding, self.cutoff = pairs, data, funding, cutoff

    def current_whitelist(self):
        return list(self.pairs)

    def _cut(self, df):
        return df if self.cutoff is None else df[df["date"] <= self.cutoff].reset_index(drop=True)

    def get_pair_dataframe(self, pair, timeframe=None, candle_type=""):
        if candle_type == "funding_rate":
            return self._cut(self.funding.get(pair, pd.DataFrame(columns=["date", "funding_rate"])))
        return self._cut(self.data[pair])


def run(strategy, dp, pair, df):
    strategy.dp = dp
    type(strategy)._cs_cache = {}
    meta = {"pair": pair}
    out = strategy.populate_indicators(df.copy(), meta)
    out = strategy.populate_entry_trend(out, meta)
    out = strategy.populate_exit_trend(out, meta)
    return out.set_index("date")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", default="FundingCarry")
    ap.add_argument("--config", default="configs/config_carry.json")
    ap.add_argument("--start", default="2020-09-01")
    ap.add_argument("--end", default="2022-01-01")
    ap.add_argument("--cutoffs", type=int, default=12)
    ap.add_argument("--pairs-checked", type=int, default=8)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()

    cfg = json.load(open(a.config))
    pairs = cfg["exchange"]["pair_whitelist"]
    start, end = pd.Timestamp(a.start, tz="UTC"), pd.Timestamp(a.end, tz="UTC")
    data, funding = {}, {}
    for p in pairs:
        d = load_pair_history(pair=p, timeframe="1h", datadir=DATADIR, data_format="feather",
                              candle_type=CandleType.SPOT)
        d = d[(d["date"] >= start) & (d["date"] < end)].reset_index(drop=True)
        if d.empty:
            continue
        data[p] = d
        if p.split("/")[0].endswith("CARRY"):
            u = f"{p.split('/')[0].removesuffix('CARRY')}/USDT:USDT"
            funding[u] = load_pair_history(pair=u, timeframe="1h", datadir=DATADIR, data_format="feather",
                                           candle_type=CandleType.FUNDING_RATE)
    pairs = list(data)

    mod = importlib.import_module(a.strategy)
    cls = getattr(mod, a.strategy)
    strat = cls({"max_open_trades": cfg["max_open_trades"], "stake_currency": "USDT",
                 "trading_mode": "spot", "timeframe": "1h", "dry_run": True,
                 "exchange": {"name": "binance"}})

    rng = np.random.default_rng(a.seed)
    full_dp = StubDP(pairs, data, funding)
    checked = [pairs[i] for i in rng.choice(len(pairs), size=min(a.pairs_checked, len(pairs)), replace=False)]
    full = {p: run(strat, full_dp, p, data[p]) for p in checked}
    cols = None
    span = (end - start).total_seconds() / 3600
    cutoffs = sorted(start + pd.Timedelta(hours=int(h)) for h in rng.uniform(24 * 20, span - 24, a.cutoffs))
    mismatches = 0
    compared = 0
    for T in cutoffs:
        dp = StubDP(pairs, data, funding, cutoff=T)
        for p in checked:
            dfp = data[p][data[p]["date"] <= T]
            if dfp.empty:
                continue
            part = run(strat, dp, p, dfp)
            f = full[p].loc[part.index]
            cols = [c for c in part.columns if c in f.columns and pd.api.types.is_numeric_dtype(part[c])]
            a_ = part[cols].astype(float).to_numpy()
            b_ = f[cols].astype(float).to_numpy()
            same = np.isclose(a_, b_, rtol=1e-9, atol=1e-12, equal_nan=True)
            compared += same.size
            if not same.all():
                bad = np.argwhere(~same)
                mismatches += len(bad)
                r, c = bad[0]
                print(f"MISMATCH T={T} pair={p} col={cols[c]} at {part.index[r]}: "
                      f"truncated={a_[r, c]} full={b_[r, c]}")
    print(f"cut-offs={len(cutoffs)} pairs={len(checked)} values compared={compared} mismatches={mismatches}")
    print("RESULT:", "PASS (no lookahead)" if mismatches == 0 else "FAIL")
    return 0 if mismatches == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
