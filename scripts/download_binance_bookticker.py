#!/usr/bin/env python3
"""
Download Binance USDT-M futures best bid/ask (daily `bookTicker` archive) for given symbols
and keep only the LAST quote of every minute (the raw files are tick-level, GBs per month).

Output: user_data/data/binance/bookticker/<SYMBOL>-1m.feather  columns date, bid, ask, bid_qty, ask_qty
Used by research/option_arb2.py to price the futures leg at the exact option-snapshot time.

    python scripts/download_binance_bookticker.py --symbols BTCUSDT_230929 --start 2023-06-25 --end 2023-09-29
"""
from __future__ import annotations

import argparse
import io
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from download_binance_delivery import HOST, get  # noqa: E402

OUT = Path("user_data/data/binance/bookticker")


def day(sym: str, d: pd.Timestamp) -> pd.DataFrame | None:
    raw = get(f"{HOST}/data/futures/um/daily/bookTicker/{sym}/{sym}-bookTicker-{d:%Y-%m-%d}.zip")
    if raw is None:
        return None
    with zipfile.ZipFile(io.BytesIO(raw)) as zf, zf.open(zf.namelist()[0]) as fh:
        t = pd.read_csv(fh, header=None, low_memory=False)
    if not str(t.iloc[0, 0]).isdigit():
        t = t.iloc[1:]
    # update_id, bid, bid_qty, ask, ask_qty, transaction_time, event_time
    t = t.iloc[:, :7].astype(float)
    t.columns = ["uid", "bid", "bid_qty", "ask", "ask_qty", "tt", "et"]
    t["date"] = pd.to_datetime(t["tt"].astype("int64"), unit="ms", utc=True).dt.floor("min")
    return t.groupby("date")[["bid", "ask", "bid_qty", "ask_qty"]].last().reset_index()


def symbol(sym: str, start: str, end: str, workers: int) -> str:
    days = pd.date_range(start, end, freq="D")
    with ThreadPoolExecutor(workers) as ex:
        parts = [p for p in ex.map(lambda d: day(sym, d), days) if p is not None]
    if not parts:
        return f"{sym}: no data"
    df = pd.concat(parts).sort_values("date").reset_index(drop=True)
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_feather(OUT / f"{sym}-1m.feather")
    return f"{sym}: {len(df)} minutes {df.date.iloc[0]:%Y-%m-%d} -> {df.date.iloc[-1]:%Y-%m-%d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()
    for s in a.symbols:
        print(symbol(s, a.start, a.end, a.workers), flush=True)


if __name__ == "__main__":
    main()
