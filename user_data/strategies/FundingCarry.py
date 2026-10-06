# pragma pylint: disable=missing-docstring, invalid-name, too-many-arguments
"""
FundingCarry  (1h, delta-neutral funding-rate arbitrage with multi-coin rotation)
================================================================================

Trades synthetic carry instruments <COIN>CARRY/USDT built by
scripts/build_carry_data.py: each one is the equity curve of a
1x-hedged position  "long COIN spot + short COIN/USDT perpetual".  Price risk
cancels out; the position earns the funding paid by leveraged longs and is
exposed only to basis (perp vs spot) moves.

Rules (all fixed up-front, round numbers):
  * signal: trailing 72h funding of the underlying perpetual, expressed as the
    average rate per 8h  (Binance base rate = 0.01 % / 8h)
  * rotation: rank all coins by that signal; only the top `max_open_trades`
    coins are eligible -> capital rotates to the best-paying coins
  * enter: average funding >= 0.02 % / 8h  (2x base rate, ~22 % APR)
  * exit : trailing 72h funding turns negative  (hysteresis: no churn)
           or the perpetual stops paying funding (delisting)
  * stop : -5 % on capital (= ~10 % adverse basis move)

To trade it live you run the two legs (spot long, perp short) with identical
signals - see docs/STRATEGY_REPORT.md.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pandas import DataFrame

from freqtrade.strategy import IStrategy


class FundingCarry(IStrategy):
    INTERFACE_VERSION = 3
    can_short = False
    timeframe = "1h"
    startup_candle_count = 100

    minimal_roi = {"0": 100.0}       # no take-profit: carry is held while it pays
    stoploss = -0.05
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    process_only_new_candles = True

    lookback_h = 72                  # funding look-back window (hours)
    enter_rate = 0.0002              # average funding per 8h needed to enter
    stale_h = 24                     # exit when no funding paid for this long

    _cs_cache: dict = {}

    @staticmethod
    def underlying(pair: str) -> str:
        coin, quote = pair.split("/")
        return f"{coin.removesuffix('CARRY')}/{quote}:{quote}"

    def _funding(self, pair: str) -> pd.DataFrame:
        fr = self.dp.get_pair_dataframe(self.underlying(pair), "1h", candle_type="funding_rate")
        if fr is None or fr.empty:
            return pd.DataFrame(columns=["date", "funding"])
        col = "funding_rate" if "funding_rate" in fr.columns else "close"
        if "volume" in fr.columns:
            fr = fr[fr["volume"] > 0]  # drop rows forward-filled by a loader (real events have volume=1)
        return fr[["date", col]].rename(columns={col: "funding"})

    def _signals(self, pair: str, dates: pd.Series) -> pd.DataFrame:
        f = self._funding(pair)
        s = pd.DataFrame({"date": dates})
        s = s.merge(f.astype({"date": dates.dtype}), on="date", how="left")
        s["paid"] = s["funding"].notna().astype(float)
        s["funding"] = s["funding"].fillna(0.0)
        trail = s["funding"].rolling(self.lookback_h, min_periods=self.lookback_h).sum()
        s["funding_trail"] = trail
        s["funding_8h"] = trail / (self.lookback_h / 8)
        s["hours_since_paid"] = s.groupby(s["paid"].cumsum()).cumcount()
        return s.set_index("date")

    def _cross_section(self) -> dict:
        pairs = self.dp.current_whitelist()
        ref = self.dp.get_pair_dataframe(pairs[0], self.timeframe)
        key = (tuple(pairs), len(ref), ref["date"].iloc[-1] if len(ref) else None)
        if self._cs_cache.get("key") == key:
            return self._cs_cache
        sig = {}
        for p in pairs:
            d = self.dp.get_pair_dataframe(p, self.timeframe)
            if d is None or d.empty:
                continue
            sig[p] = self._signals(p, d["date"])["funding_8h"]
        f8 = pd.DataFrame(sig).sort_index()
        type(self)._cs_cache = {"key": key, "rank": f8.rank(axis=1, ascending=False)}
        return self._cs_cache

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        pair = metadata["pair"]
        s = self._signals(pair, dataframe["date"])
        for c in ("funding", "funding_trail", "funding_8h", "hours_since_paid"):
            dataframe[c] = s[c].values
        rank = self._cross_section()["rank"]
        if pair in rank.columns:
            r = rank[pair]
            r.index = r.index.astype(dataframe["date"].dtype)
            dataframe["funding_rank"] = dataframe["date"].map(r).values
        else:
            dataframe["funding_rank"] = np.nan
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        slots = self.config.get("max_open_trades", 10)
        dataframe.loc[
            (dataframe["funding_8h"] >= self.enter_rate)
            & (dataframe["funding_rank"] <= slots)
            & (dataframe["hours_since_paid"] < 9)
            & (dataframe["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "carry")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["funding_trail"] < 0, ["exit_long", "exit_tag"]] = (1, "funding_negative")
        dataframe.loc[dataframe["hours_since_paid"] >= self.stale_h, ["exit_long", "exit_tag"]] = (1, "no_funding")
        return dataframe
