# pragma pylint: disable=missing-docstring, invalid-name, too-many-arguments
"""
TrendMomentumLS  (1d, Binance USDT-M perpetuals, long + short, multi-coin)
=========================================================================

A portfolio strategy that combines three nearly uncorrelated return sources
(pairwise daily-return correlations between -0.04 and 0.09 in-sample):

1. Time-series trend (per coin, long or short):
       average sign of the coin's return over 10/20/40/80/160 days
2. Cross-sectional momentum (market neutral, rotation):
       average over 14/30/60/90-day look-backs of
       +1 for the top 20 % of coins, -1 for the bottom 20 %
3. Cross-sectional funding carry (market neutral, rotation):
       average over 3/7/14-day trailing funding of
       +1 for the 20 % of coins with the LOWEST funding, -1 for the highest
       (short crowded longs, receive their funding)

Each sleeve is turned into inverse-volatility weights (60-day vol, gross = 1),
the sleeves are blended equally, and the whole book is scaled so that its
trailing 60-day realised volatility targets 10 % p.a. (gross leverage <= 2).

Freqtrade mechanics
-------------------
* every daily candle a target weight per coin is computed from CLOSED candles
* weight > 0 -> long, < 0 -> short, flips close the trade
* `adjust_trade_position` re-sizes an open trade when it drifts > 25 % from target
* isolated margin, 2x leverage per position, -90 % disaster stop on margin (~45 % price move)

No parameter was optimised: look-backs are geometric ladders / standard values,
and the in-sample sensitivity of every parameter is a plateau
(see docs/LONG_SHORT_REPORT.md).
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
from pandas import DataFrame

from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy


class TrendMomentumLS(IStrategy):
    INTERFACE_VERSION = 3
    can_short = True
    timeframe = "1d"
    startup_candle_count = 200

    minimal_roi = {"0": 100.0}
    stoploss = -0.90                 # disaster stop only: on margin at 2x = ~45 % adverse price move
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    position_adjustment_enable = True
    max_entry_position_adjustment = -1
    process_only_new_candles = True

    # ---- fixed design parameters (not optimised) -------------------------
    trend_lbs = (10, 20, 40, 80, 160)
    xs_lbs = (14, 30, 60, 90)
    xs_quantile = 0.2
    carry_lbs = (3, 7, 14)
    vol_lb = 60
    target_vol = 0.10
    max_gross = 2.0
    pos_leverage = 2.0
    rebalance_band = 0.25            # re-size when |actual/target - 1| > band

    _cache: dict = {}

    # ------------------------------------------------------------------ #
    # portfolio target weights (cross-sectional), computed once per candle
    # ------------------------------------------------------------------ #
    @staticmethod
    def _inv_vol_weights(signal: DataFrame, vol: DataFrame) -> DataFrame:
        w = (signal / vol).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        return w.div(w.abs().sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)

    def _targets(self) -> DataFrame:
        pairs = self.dp.current_whitelist()
        ref = self.dp.get_pair_dataframe(pairs[0], self.timeframe)
        key = (tuple(pairs), len(ref), ref["date"].iloc[-1] if len(ref) else None)
        if self._cache.get("key") == key:
            return self._cache["w"]

        closes, funding = {}, {}
        for p in pairs:
            d = self.dp.get_pair_dataframe(p, self.timeframe)
            if d is not None and not d.empty:
                closes[p] = d.set_index("date")["close"]
            fr = self.dp.get_pair_dataframe(p, "1h", candle_type="funding_rate")
            if fr is not None and not fr.empty:
                col = "funding_rate" if "funding_rate" in fr.columns else "open"
                f = fr.set_index("date")[col]
                funding[p] = f.groupby(f.index.floor("D")).sum()  # events of day d, known at its close
        C = pd.DataFrame(closes).sort_index()
        F = pd.DataFrame(funding).reindex(index=C.index, columns=C.columns).fillna(0.0)
        R = C.pct_change(fill_method=None)
        vol = R.rolling(self.vol_lb, min_periods=self.vol_lb // 2).std() * np.sqrt(365)

        trend = sum(np.sign(C / C.shift(lb) - 1) for lb in self.trend_lbs) / len(self.trend_lbs)
        xs = 0
        for lb in self.xs_lbs:
            rk = (C / C.shift(lb) - 1).rank(axis=1, pct=True)
            xs = xs + (rk >= 1 - self.xs_quantile).astype(float) - (rk <= self.xs_quantile).astype(float)
        xs = xs / len(self.xs_lbs)

        carry = 0
        for lb in self.carry_lbs:
            rk = F.rolling(lb).sum().where(C.notna()).rank(axis=1, pct=True)
            carry = carry + (rk <= self.xs_quantile).astype(float) - (rk >= 1 - self.xs_quantile).astype(float)
        carry = carry / len(self.carry_lbs)

        w_raw = (self._inv_vol_weights(trend.where(C.notna()), vol)
                 + self._inv_vol_weights(xs.where(C.notna()), vol)
                 + self._inv_vol_weights(carry.where(C.notna()), vol)) / 3
        # volatility targeting on the book's own trailing returns (uses data up to t only)
        raw_ret = (w_raw.shift(1).fillna(0.0) * R.fillna(0.0)).sum(axis=1)
        rv = raw_ret.rolling(self.vol_lb, min_periods=20).std() * np.sqrt(365)
        scale = (self.target_vol / rv).clip(upper=self.max_gross).fillna(0.0)
        w = w_raw.mul(scale, axis=0)
        gross = w.abs().sum(axis=1)
        w = w.mul(np.minimum(1.0, self.max_gross / gross.replace(0, np.nan)).fillna(1.0), axis=0)
        type(self)._cache = {"key": key, "w": w}
        return w

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        w = self._targets()
        pair = metadata["pair"]
        if pair in w.columns:
            s = w[pair]
            s.index = s.index.astype(dataframe["date"].dtype)
            dataframe["target_w"] = dataframe["date"].map(s).fillna(0.0).values
        else:
            dataframe["target_w"] = 0.0
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["target_w"] > 0, ["enter_long", "enter_tag"]] = (1, "long")
        dataframe.loc[dataframe["target_w"] < 0, ["enter_short", "enter_tag"]] = (1, "short")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["target_w"] <= 0, ["exit_long", "exit_tag"]] = (1, "target_not_long")
        dataframe.loc[dataframe["target_w"] >= 0, ["exit_short", "exit_tag"]] = (1, "target_not_short")
        return dataframe

    # ------------------------------------------------------------------ #
    # sizing
    # ------------------------------------------------------------------ #
    def _equity(self) -> float:
        return float(self.wallets.get_total_stake_amount()) if self.wallets else 0.0

    def _target_stake(self, pair: str) -> float:
        df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if df.empty:
            return 0.0
        return abs(float(df["target_w"].iloc[-1])) * self._equity() / self.pos_leverage

    def leverage(self, pair: str, current_time: datetime, current_rate: float, proposed_leverage: float,
                 max_leverage: float, entry_tag: str | None, side: str, **kwargs) -> float:
        return min(self.pos_leverage, max_leverage)

    def custom_stake_amount(self, pair: str, current_time: datetime, current_rate: float,
                            proposed_stake: float, min_stake: float | None, max_stake: float,
                            leverage: float, entry_tag: str | None, side: str, **kwargs) -> float:
        stake = self._target_stake(pair)
        if min_stake and stake < min_stake:
            return 0.0
        return min(stake, max_stake)

    def adjust_trade_position(self, trade: Trade, current_time: datetime, current_rate: float,
                              current_profit: float, min_stake: float | None, max_stake: float,
                              current_entry_rate: float, current_exit_rate: float,
                              current_entry_profit: float, current_exit_profit: float, **kwargs):
        target = self._target_stake(trade.pair)
        # current margin at today's price
        current = trade.amount * current_rate / trade.leverage
        if target <= 0 or current <= 0:
            return None
        if abs(current / target - 1) <= self.rebalance_band:
            return None
        delta = target - current
        if delta > 0:
            if min_stake and delta < min_stake:
                return None
            return min(delta, max_stake), "rebalance_up"
        reduce = min(-delta, current - (min_stake or 0) * 1.05)
        if reduce <= 0 or (min_stake and reduce < min_stake):
            return None
        return -reduce, "rebalance_down"
