#!/usr/bin/env python3
"""
Build synthetic "carry instruments" for Freqtrade backtesting.

For every coin with spot klines, USDT-M perpetual klines and funding rates, the
hourly return of a delta-neutral position

    long 1 unit spot  +  short 1 unit perpetual   (1x hedge, both legs fully funded)

per unit of CAPITAL (= 2 units of notional) is

    r = (r_spot - r_perp + funding) / 2

The cumulative product of (1 + r) is written as an OHLCV series named
<COIN>CARRY/USDT so Freqtrade can backtest a carry-rotation strategy on it with
its normal machinery (fees, slots, protections, reports, FreqUI).

    python scripts/build_carry_data.py --pairs-file configs/pairs_universe.json

Notes
-----
* funding is credited to the candle that closes at the payment time
  (Binance pays the short when > 0; entries right after a payment miss it)
* basis moves (perp vs spot divergence) are fully included
* open = previous close, high/low = max/min(open, close): intrabar basis spikes
  are NOT visible, which is why the strategy stop is evaluated on closes only
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

DATA = Path("user_data/data/binance")
HEDGE_CAPITAL = 2.0  # capital per unit of notional (spot leg + 1x perp margin)


def build(coin: str, quote: str = "USDT") -> str:
    fs = DATA / f"{coin}_{quote}-1h.feather"
    ff = DATA / "futures" / f"{coin}_{quote}_{quote}-1h-futures.feather"
    fr = DATA / "futures" / f"{coin}_{quote}_{quote}-1h-funding_rate.feather"
    if not (fs.exists() and ff.exists() and fr.exists()):
        return f"{coin}: missing spot/futures/funding data"
    spot = pd.read_feather(fs).set_index("date")
    perp = pd.read_feather(ff).set_index("date")["close"].rename("perp")
    fund = pd.read_feather(fr).set_index("date")["close"]
    fund = fund[~fund.index.duplicated()]
    df = spot[["close", "volume"]].join(perp, how="inner").sort_index()
    # A funding event at time T is earned by positions held across T, i.e. it belongs to
    # the candle that CLOSES at T (candle date = T - 1h).  A bot entering right after
    # the candle close at T therefore never receives the payment of T.
    df["funding"] = fund.reindex(df.index + pd.Timedelta(hours=1)).fillna(0.0).values
    r = (df["close"].pct_change() - df["perp"].pct_change() + df["funding"]) / HEDGE_CAPITAL
    close = 100.0 * (1 + r.fillna(0.0)).cumprod()
    open_ = close.shift(1).fillna(100.0)
    out = pd.DataFrame({
        "date": df.index,
        "open": open_.values,
        "high": pd.concat([open_, close], axis=1).max(axis=1).values,
        "low": pd.concat([open_, close], axis=1).min(axis=1).values,
        "close": close.values,
        "volume": (df["volume"] * df["close"]).values,  # spot quote volume, informational
    })
    path = DATA / f"{coin}CARRY_{quote}-1h.feather"
    out.to_feather(path)
    return f"{coin}CARRY/{quote}: {len(out)} candles {out.date.iloc[0]:%Y-%m-%d} -> {out.date.iloc[-1]:%Y-%m-%d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs-file", required=True, help="json list of spot pairs, e.g. BTC/USDT")
    ap.add_argument("--out-pairs", help="write the resulting CARRY pair list to this json file")
    a = ap.parse_args()
    built = []
    for p in json.load(open(a.pairs_file)):
        coin, quote = p.split(":")[0].split("/")
        msg = build(coin, quote)
        print(msg)
        if "candles" in msg:
            built.append(f"{coin}CARRY/{quote}")
    if a.out_pairs:
        Path(a.out_pairs).write_text(json.dumps(built, indent=1))


if __name__ == "__main__":
    main()
