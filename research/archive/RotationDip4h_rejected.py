# pragma pylint: disable=missing-docstring, invalid-name, too-many-arguments
"""
RotationDip  (4h, spot, long-only)
==================================

"Buy the dip, but only in the strongest coins, and only when the market is healthy."

Layers
------
1. Market regime (right-side / trend):
     * BTC daily close > BTC daily SMA50 (previous, closed daily candle)
     * market breadth >= 50 %  (share of coins in the whitelist with positive
       20-day risk-adjusted momentum)
2. Multi-coin rotation:
     every 4h candle, all whitelisted coins are ranked by 20-day
     volatility-adjusted momentum.  Only the TOP_N coins with positive momentum
     are eligible -> capital rotates automatically into the current leaders.
3. Entry (left-side / mean reversion):
     a short-term oversold pullback inside the long-term uptrend of that coin
       - RSI(14) < 35 and close > EMA200     ("trend_pullback")
       - RSI(14) < 30 and close < lower BB(20,2)  ("bb_flush")
4. Exits:
     * ROI: +5 % (any time), +2.5 % after 3 days, break-even after 5 days
     * hard stoploss -10 %
     * time stop after 10 days
     * regime turns off -> leave the market
5. Protections: cooldown, stoploss guard, max-drawdown circuit breaker.

All numbers are standard, round "textbook" values fixed before testing.  The
strategy contains no hyperopt spaces on purpose (see docs/OVERFITTING.md).
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import talib.abstract as ta
from pandas import DataFrame

from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy


class RotationDip4h(IStrategy):
    INTERFACE_VERSION = 3
    can_short = False
    timeframe = "4h"
    startup_candle_count = 300

    minimal_roi = {"0": 0.05, "4320": 0.025, "7200": 0.0}
    stoploss = -0.10
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    process_only_new_candles = True

    # ---- fixed design parameters (not optimised) -------------------------
    regime_sma = 50            # BTC daily SMA
    breadth_min = 0.5          # >= half of the universe in positive momentum
    breadth_exit = 0.4         # leave the market below this breadth (hysteresis)
    btc_rsi_guard = 30         # no new entries while BTC 4h RSI is below this (0 = off)
    mom_days = 20              # momentum look-back (days)
    top_n = 10                 # rotation basket
    rsi_pullback = 35
    rsi_flush = 30
    max_trade_days = 10        # time stop

    _cs_cache: dict = {}

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 2},
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 12,      # 2 days
                "trade_limit": 3,
                "stop_duration_candles": 12,
                "only_per_pair": False,
            },
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 42,      # 1 week
                "trade_limit": 5,
                "stop_duration_candles": 18,        # 3 days
                "max_allowed_drawdown": 0.08,
            },
        ]

    def informative_pairs(self):
        return [("BTC/USDT", "1d")]

    # ------------------------------------------------------------------ #
    # cross-sectional features (rotation + breadth), computed once per candle
    # ------------------------------------------------------------------ #
    def _cross_section(self) -> dict:
        pairs = self.dp.current_whitelist()
        ref = self.dp.get_pair_dataframe(pairs[0], self.timeframe)
        key = (type(self).__name__, tuple(pairs), len(ref), ref["date"].iloc[-1] if len(ref) else None)
        if self._cs_cache.get("key") == key:
            return self._cs_cache

        w = int(self.mom_days * 24 / 4)  # candles in the momentum window (4h)
        scores = {}
        for p in pairs:
            d = self.dp.get_pair_dataframe(p, self.timeframe)
            if d is None or d.empty:
                continue
            close = d.set_index("date")["close"]
            lr = np.log(close).diff()
            scores[p] = np.log(close / close.shift(w)) / (lr.rolling(w).std() * np.sqrt(w))
        score = pd.DataFrame(scores).sort_index()
        cache = {
            "key": key,
            "score": score,
            "rank": score.rank(axis=1, ascending=False),
            "breadth": (score > 0).sum(axis=1) / score.notna().sum(axis=1).replace(0, np.nan),
        }
        type(self)._cs_cache = cache
        return cache

    # ------------------------------------------------------------------ #
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        pair = metadata["pair"]
        dtype = dataframe["date"].dtype

        # --- BTC daily regime, shifted so only CLOSED daily candles are used
        btc_d = self.dp.get_pair_dataframe("BTC/USDT", "1d")[["date", "close"]].copy()
        btc_d["btc_bull"] = (btc_d["close"] > btc_d["close"].rolling(self.regime_sma).mean()).astype(int)
        btc_d["date"] = (btc_d["date"] + pd.Timedelta(days=1)).astype(dtype)
        dataframe = pd.merge_asof(
            dataframe.sort_values("date"),
            btc_d[["date", "btc_bull"]].sort_values("date"),
            on="date",
            direction="backward",
        )

        # --- rotation rank / breadth
        cs = self._cross_section()
        feat = pd.DataFrame({"date": cs["score"].index.astype(dtype), "breadth": cs["breadth"].values})
        if pair in cs["score"].columns:
            feat["mom_score"] = cs["score"][pair].values
            feat["mom_rank"] = cs["rank"][pair].values
        else:
            feat["mom_score"] = np.nan
            feat["mom_rank"] = np.nan
        dataframe = dataframe.merge(feat, on="date", how="left")

        dataframe["regime_ok"] = (
            (dataframe["btc_bull"] == 1) & (dataframe["breadth"] >= self.breadth_min)
        ).astype(int)
        dataframe["regime_exit"] = (
            (dataframe["btc_bull"] == 0) | (dataframe["breadth"] < self.breadth_exit)
        ).astype(int)

        # BTC short-term state (market-wide selloff guard)
        btc = self.dp.get_pair_dataframe("BTC/USDT", self.timeframe)[["date", "close"]].copy()
        btc["btc_rsi"] = ta.RSI(btc["close"], timeperiod=14)
        btc["date"] = btc["date"].astype(dtype)
        dataframe = dataframe.merge(btc[["date", "btc_rsi"]], on="date", how="left")
        dataframe["leader"] = (
            (dataframe["mom_rank"] <= self.top_n) & (dataframe["mom_score"] > 0)
        ).astype(int)

        # --- coin level
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200)
        bb = ta.BBANDS(dataframe, timeperiod=20, nbdevup=2.0, nbdevdn=2.0)
        dataframe["bb_lower"] = bb["lowerband"]
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        base = (
            (dataframe["regime_ok"] == 1)
            & (dataframe["leader"] == 1)
            & (dataframe["btc_rsi"] >= self.btc_rsi_guard)
            & (dataframe["volume"] > 0)
        )

        trend_pullback = (dataframe["rsi"] < self.rsi_pullback) & (dataframe["close"] > dataframe["ema200"])
        bb_flush = (dataframe["rsi"] < self.rsi_flush) & (dataframe["close"] < dataframe["bb_lower"])

        dataframe.loc[base & bb_flush, ["enter_long", "enter_tag"]] = (1, "bb_flush")
        dataframe.loc[base & trend_pullback, ["enter_long", "enter_tag"]] = (1, "trend_pullback")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["regime_exit"] == 1, ["exit_long", "exit_tag"]] = (1, "regime_off")
        return dataframe

    def custom_exit(self, pair: str, trade: Trade, current_time: datetime, current_rate: float,
                    current_profit: float, **kwargs):
        if (current_time - trade.open_date_utc).days >= self.max_trade_days:
            return "time_stop"
        return None
