# pragma pylint: disable=missing-docstring, invalid-name, too-many-arguments
"""
RotationDipLS  (1h, USDT-M futures, long + short, 1x leverage)
==============================================================

The long side is exactly RotationDip.  The short side is its mirror image, so
the strategy can also earn in bear markets / alt-season-less markets instead of
sitting in cash:

    long  : healthy market  -> buy  oversold dips  of the strongest coins
    short : weak market     -> sell overbought bounces of the weakest coins

Mirroring rule: every short threshold is the long threshold reflected around
the neutral point (breadth 0.5 / RSI 50).  No new parameters were introduced
and none were tuned for the short side.

    long                               short (mirror)
    BTC close > SMA50 (daily)          BTC close < SMA50
    breadth >= 0.50 to enter           breadth <= 0.50
    exit if breadth < 0.40             exit if breadth > 0.60
    crash exit hourly breadth < 0.25   squeeze exit hourly breadth > 0.75
    top-10 momentum, score > 0         bottom-10 momentum, score < 0
    RSI < 35 & close > EMA200          RSI > 65 & close < EMA200
    RSI < 30 & close < lower BB        RSI > 70 & close > upper BB
    BTC 1h RSI >= 30 (no panic)        BTC 1h RSI <= 70 (no squeeze)
    ROI 3% / SL 10% / time stop        same
"""
from __future__ import annotations

from pandas import DataFrame

from RotationDip import RotationDip


class RotationDipLS(RotationDip):
    can_short = True

    def leverage(self, pair: str, current_time, current_rate: float, proposed_leverage: float,
                 max_leverage: float, entry_tag: str | None, side: str, **kwargs) -> float:
        return 1.0

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)
        m = lambda x: 1.0 - x  # noqa: E731  (mirror a breadth threshold)
        dataframe["regime_short"] = (
            (dataframe["btc_bull"] == 0) & (dataframe["breadth"] <= m(self.breadth_min))
        ).astype(int)
        dataframe["regime_short_exit"] = (
            (dataframe["btc_bull"] == 1)
            | (dataframe["breadth"] > m(self.breadth_exit))
            | (dataframe["breadth_fast"] > m(self.crash_breadth))
        ).astype(int)
        dataframe["laggard"] = (
            (dataframe["mom_rank_low"] <= self.top_n) & (dataframe["mom_score"] < 0)
        ).astype(int)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_entry_trend(dataframe, metadata)
        base = (
            (dataframe["regime_short"] == 1)
            & (dataframe["laggard"] == 1)
            & (dataframe["btc_rsi"] <= 100 - self.btc_rsi_guard)
            & (dataframe["volume"] > 0)
        )
        trend_bounce = (dataframe["rsi"] > 100 - self.rsi_pullback) & (dataframe["close"] < dataframe["ema200"])
        bb_spike = (dataframe["rsi"] > 100 - self.rsi_flush) & (dataframe["close"] > dataframe["bb_upper"])
        dataframe.loc[base & bb_spike, ["enter_short", "enter_tag"]] = (1, "bb_spike")
        dataframe.loc[base & trend_bounce, ["enter_short", "enter_tag"]] = (1, "trend_bounce")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_exit_trend(dataframe, metadata)
        dataframe.loc[dataframe["regime_short_exit"] == 1, ["exit_short", "exit_tag"]] = (1, "regime_off")
        return dataframe
