# pragma pylint: disable=missing-docstring, invalid-name
"""
BasisCarry  (1d, coin-margined quarterly cash-and-carry on BTC and ETH)
=====================================================================

Trades the synthetic instruments <COIN>Q1BASIS/USDT (nearest quarterly) and <COIN>Q2BASIS/USDT
(the next one) built by scripts/build_basis_data.py:
each is the equity of "long spot (posted as margin) + short the active COIN-margined
quarterly delivery future", capital = 1x notional.  An inverse future hedged with the coin
itself is exactly USD-neutral and cannot be liquidated by price moves; at delivery the
future settles to the index, so the basis locked at entry is earned regardless of price.

Rules (fixed, see docs/ARBITRAGE_RESEARCH.md):
  * enter : locked annualised basis of the active contract, net of the round-trip cost
            spread over its remaining life, >= 5 %
  * exit  : remaining annualised basis < 2 %  (basis converged early -> free the capital)
  * the instrument rolls to the next quarterly 14 days before expiry (roll cost included);
            on a roll day the position is closed and the best contract is re-selected
  * BTC and ETH only (capacity: the only coin-margined quarterlies with > 10 M USD daily volume)

Live trading needs the two legs (spot + coin-margined quarterly) placed by the user / an
execution layer; the backtest uses the synthetic instrument.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from pandas import DataFrame

from freqtrade.strategy import IStrategy

BASIS_DIR = Path("user_data/data/binance/basis")


class BasisCarry(IStrategy):
    INTERFACE_VERSION = 3
    can_short = False
    timeframe = "1d"
    startup_candle_count = 5

    minimal_roi = {"0": 100.0}
    stoploss = -0.50          # mark-to-market basis swings only; no liquidation risk (coin-margined)
    use_exit_signal = True
    process_only_new_candles = True

    enter_yield = 0.05
    exit_yield = 0.02
    round_trip_cost = 0.003   # spot 0.1 % x2 + futures 0.05 % x2 on notional

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        inst = metadata["pair"].split("BASIS")[0]            # e.g. BTCQ1 / ETHQ2
        side = pd.read_feather(BASIS_DIR / f"{inst}-basis.feather")
        side["date"] = side["date"].astype(dataframe["date"].dtype)
        dataframe = dataframe.merge(side[["date", "locked_y", "tau", "contract"]], on="date", how="left")
        dataframe["rolled"] = (dataframe["contract"] != dataframe["contract"].shift(1)) & dataframe["contract"].shift(1).notna()
        dataframe["net_y"] = dataframe["locked_y"] - self.round_trip_cost * 365 / dataframe["tau"].clip(lower=1)
        # cross-sectional rank of net yield over all instruments (pick the best contracts)
        dataframe["y_rank"] = dataframe["date"].map(self._ranks()).apply(lambda r: r.get(metadata["pair"], 99) if isinstance(r, dict) else 99)
        return dataframe

    _rank_cache: dict = {}

    def _ranks(self) -> dict:
        pairs = tuple(self.dp.current_whitelist())
        if self._rank_cache.get("pairs") == pairs:
            return self._rank_cache["r"]
        ys = {}
        for p in pairs:
            side = pd.read_feather(BASIS_DIR / f"{p.split('BASIS')[0]}-basis.feather").set_index("date")
            ys[p] = side["locked_y"] - self.round_trip_cost * 365 / side["tau"].clip(lower=1)
        rk = pd.DataFrame(ys).rank(axis=1, ascending=False)
        r = {d: row.dropna().to_dict() for d, row in rk.iterrows()}
        type(self)._rank_cache = {"pairs": pairs, "r": r}
        return r

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        slots = self.config.get("max_open_trades", 2)
        dataframe.loc[(dataframe["net_y"] >= self.enter_yield) & (dataframe["y_rank"] <= slots)
                      & (dataframe["volume"] > 0),
                      ["enter_long", "enter_tag"]] = (1, "basis_rich")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[(dataframe["locked_y"] < self.exit_yield) & (dataframe["tau"] > 3),
                      ["exit_long", "exit_tag"]] = (1, "basis_converged")
        # the instrument just rolled into the next quarterly: close and re-select, so the
        # capital always goes to the best contract available (as at an expiry)
        dataframe.loc[dataframe["rolled"], ["exit_long", "exit_tag"]] = (1, "roll_reselect")
        return dataframe
