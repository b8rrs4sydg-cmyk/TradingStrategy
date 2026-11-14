# pragma pylint: disable=missing-docstring, invalid-name
"""
DonchianTrendLS  (1d, Binance USDT-M perpetuals, long + short, multi-coin)
=========================================================================

Time-series trend following on every coin in the whitelist, long or short:

* signal per coin = average of three Donchian channel systems
      entry 20 / exit 10,  entry 50 / exit 20,  entry 100 / exit 50 days
  each system is +1 after a close at the N-day high, -1 after a close at the
  N-day low, and goes flat when price crosses the opposite exit channel.
* inverse-volatility weights (60-day vol), gross = 1, then the whole book is
  scaled to a target volatility on its own trailing 60-day realised vol
  (gross leverage <= 2) - identical execution to TrendMomentumLS.

Why this one: of all long/short families tested on universes A and B
(in-sample 2020-06..2023-12), only time-series trend was positive on BOTH
universes; cross-sectional momentum and the funding factor failed on B.
Windows are an ensemble of standard Turtle-style values, not optimised.
"""
from __future__ import annotations

import numpy as np
from pandas import DataFrame

from TrendMomentumLS import TrendMomentumLS


class DonchianTrendLS(TrendMomentumLS):
    donchian_windows = ((20, 10), (50, 20), (100, 50))
    target_vol = 0.12
    startup_candle_count = 200

    @staticmethod
    def _donchian(C: DataFrame, entry: int, exit_: int) -> DataFrame:
        hi, lo = C.rolling(entry).max().to_numpy(), C.rolling(entry).min().to_numpy()
        xhi, xlo = C.rolling(exit_).max().to_numpy(), C.rolling(exit_).min().to_numpy()
        Cv = C.to_numpy()
        out = np.zeros_like(Cv)
        state = np.zeros(Cv.shape[1])
        for i in range(len(Cv)):
            c = Cv[i]
            with np.errstate(invalid="ignore"):
                state = np.where(c >= hi[i], 1.0, np.where(c <= lo[i], -1.0, state))
                state = np.where((state == 1) & (c <= xlo[i]), 0.0, state)
                state = np.where((state == -1) & (c >= xhi[i]), 0.0, state)
            state = np.where(np.isnan(c), 0.0, state)
            out[i] = state
        return DataFrame(out, index=C.index, columns=C.columns)

    def _raw_weights(self, C: DataFrame, F: DataFrame, vol: DataFrame) -> DataFrame:
        sig = sum(self._donchian(C, e, x) for e, x in self.donchian_windows) / len(self.donchian_windows)
        return self._inv_vol_weights(sig.where(C.notna()), vol)


class DonchianTrendLS_TV10(DonchianTrendLS):
    target_vol = 0.10


class DonchianTrendLS_TV15(DonchianTrendLS):
    target_vol = 0.15
