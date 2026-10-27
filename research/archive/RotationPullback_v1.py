# pragma pylint: disable=missing-docstring, invalid-name, too-many-arguments
"""
RotationPullback
================

Multi-coin rotation + regime filter + pullback entries (long only, spot).

1. Regime (right-side):   only trade while BTC's daily close is above its daily SMA
                          and market breadth (share of coins with positive momentum)
                          is healthy.
2. Rotation:              every hour all pairs in the whitelist are ranked by
                          volatility-adjusted momentum; only the top-N with
                          positive absolute momentum are eligible.
3. Entry (left-side):     buy a short-term oversold pullback in an eligible coin,
                          optionally waiting for the first up-tick (confirmation).
4. Exit:                  time-decaying ROI, mean-reversion exit, regime-off exit,
                          hard stoploss.

All parameters are "textbook" round numbers chosen up-front (no hyperopt).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import talib.abstract as ta
from pandas import DataFrame

from freqtrade.strategy import IStrategy


class RotationPullback(IStrategy):
    INTERFACE_VERSION = 3
    can_short = False
    timeframe = "1h"
    startup_candle_count = 500

    # --- risk -------------------------------------------------------------
    minimal_roi = {"0": 0.06, "240": 0.035, "720": 0.02, "1440": 0.01}
    stoploss = -0.10
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    process_only_new_candles = True

    # --- fixed design parameters (deliberately not optimised) -------------
    regime_sma = 50          # BTC daily SMA for the bull/bear regime
    mom_window = 24 * 20     # 20 days momentum (in 1h candles)
    top_n = 10               # rotation basket size
    rsi_entry = 30
    rsi_exit = 70
    breadth_min = 0.0        # min share of coins with positive momentum (0 = off)
    exit_on_regime_off = False
    confirm_entry = False    # wait for RSI to turn up before buying

    _rank_cache: dict = {}

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 4},
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 48,
                "trade_limit": 3,
                "stop_duration_candles": 24,
                "only_per_pair": False,
            },
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 24 * 7,
                "trade_limit": 10,
                "stop_duration_candles": 48,
                "max_allowed_drawdown": 0.08,
            },
        ]

    def informative_pairs(self):
        return [("BTC/USDT", "1d")]

    # ------------------------------------------------------------------ #
    # cross-sectional ranking (rotation)
    # ------------------------------------------------------------------ #
    def _momentum_score(self, df: DataFrame) -> pd.Series:
        close = df.set_index("date")["close"]
        ret = np.log(close).diff()
        mom = np.log(close / close.shift(self.mom_window))
        vol = ret.rolling(self.mom_window).std() * np.sqrt(self.mom_window)
        return mom / vol

    def _ranks(self) -> dict:
        pairs = self.dp.current_whitelist()
        btc = self.dp.get_pair_dataframe("BTC/USDT", self.timeframe)
        key = (type(self).__name__, tuple(pairs), len(btc),
               btc["date"].iloc[-1] if len(btc) else None)
        if self._rank_cache.get("key") != key:
            scores = {}
            for p in pairs:
                d = self.dp.get_pair_dataframe(p, self.timeframe)
                if d is not None and len(d):
                    scores[p] = self._momentum_score(d)
            score = pd.DataFrame(scores).sort_index()
            rank = score.rank(axis=1, ascending=False)
            breadth = (score > 0).sum(axis=1) / score.notna().sum(axis=1).replace(0, np.nan)
            type(self)._rank_cache = {"key": key, "score": score, "rank": rank, "breadth": breadth}
        return self._rank_cache

    # ------------------------------------------------------------------ #
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        pair = metadata["pair"]
        dtype = dataframe["date"].dtype

        # BTC regime (daily, merged without lookahead)
        btc_d = self.dp.get_pair_dataframe("BTC/USDT", "1d").copy()
        btc_d["btc_bull"] = (btc_d["close"] > ta.SMA(btc_d, timeperiod=self.regime_sma)).astype(int)
        btc_d = btc_d[["date", "btc_bull"]]
        # a daily candle is only known after it closes -> shift by one day
        btc_d["date"] = (btc_d["date"] + pd.Timedelta(days=1)).astype(dtype)
        dataframe = pd.merge_asof(
            dataframe.sort_values("date"), btc_d.sort_values("date"), on="date", direction="backward"
        )

        # rotation rank + breadth
        rc = self._ranks()
        cs = pd.DataFrame({"date": rc["rank"].index.astype(dtype), "breadth": rc["breadth"].values})
        if pair in rc["rank"].columns:
            cs["mom_rank"] = rc["rank"][pair].values
            cs["mom_score"] = rc["score"][pair].values
        else:
            cs["mom_rank"] = np.nan
            cs["mom_score"] = np.nan
        dataframe = dataframe.merge(cs, on="date", how="left")

        dataframe["regime_ok"] = (
            (dataframe["btc_bull"] == 1) & (dataframe["breadth"] >= self.breadth_min)
        ).astype(int)

        # pullback indicators
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        bb = ta.BBANDS(dataframe, timeperiod=20, nbdevup=2.0, nbdevdn=2.0)
        dataframe["bb_lower"] = bb["lowerband"]
        dataframe["bb_mid"] = bb["middleband"]
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if self.confirm_entry:
            # previous candle was oversold, current candle turns up
            pullback = (
                (dataframe["rsi"].shift(1) < self.rsi_entry)
                & (dataframe["close"].shift(1) < dataframe["bb_lower"].shift(1))
                & (dataframe["rsi"] > dataframe["rsi"].shift(1))
                & (dataframe["close"] > dataframe["open"])
            )
        else:
            pullback = (dataframe["rsi"] < self.rsi_entry) & (dataframe["close"] < dataframe["bb_lower"])

        dataframe.loc[
            (dataframe["regime_ok"] == 1)
            & (dataframe["mom_rank"] <= self.top_n)
            & (dataframe["mom_score"] > 0)
            & pullback
            & (dataframe["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "rot_pullback")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[(dataframe["rsi"] > self.rsi_exit), ["exit_long", "exit_tag"]] = (1, "rsi_bounce")
        if self.exit_on_regime_off:
            dataframe.loc[(dataframe["regime_ok"] == 0), ["exit_long", "exit_tag"]] = (1, "regime_off")
        return dataframe
