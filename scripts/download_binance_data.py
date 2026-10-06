#!/usr/bin/env python3
"""
Download Binance spot klines from the public data archive (data.binance.vision)
and store them in Freqtrade's feather format:
    user_data/data/binance/<BASE>_<QUOTE>-<tf>.feather

Why not `freqtrade download-data`?  It works fine when the exchange API is
reachable.  This script is a fallback for restricted networks: it reads the
same official monthly archive files that Binance publishes on S3.

Usage:
    python scripts/download_binance_data.py --pairs BTC/USDT ETH/USDT \
        --timeframes 1h 4h --start 2020-01 --end 2026-09
    python scripts/download_binance_data.py --pairs-file pairs.json ...
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pandas as pd

BASE_URLS = [
    "https://data.binance.vision/data/spot/monthly/klines",
    # path-style S3 endpoint of the same bucket (useful behind strict proxies)
    "https://s3.ap-northeast-1.amazonaws.com/data.binance.vision/data/spot/monthly/klines",
]
COLS = ["date", "open", "high", "low", "close", "volume"]


def month_range(start: str, end: str) -> list[str]:
    return [p.strftime("%Y-%m") for p in pd.period_range(start, end, freq="M")]


def fetch(url: str) -> bytes | None:
    try:
        with urlopen(Request(url, headers={"User-Agent": "ft-data"}), timeout=60) as r:
            return r.read()
    except HTTPError as e:
        if e.code in (403, 404):
            return None
        raise


def fetch_month(symbol: str, tf: str, month: str) -> pd.DataFrame | None:
    name = f"{symbol}-{tf}-{month}"
    for base in BASE_URLS:
        try:
            raw = fetch(f"{base}/{symbol}/{tf}/{name}.zip")
        except Exception:
            continue
        if raw is None:
            return None
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            with zf.open(zf.namelist()[0]) as fh:
                df = pd.read_csv(fh, header=None, usecols=range(6))
        # some files ship with a header row
        if not str(df.iloc[0, 0]).isdigit():
            df = df.iloc[1:]
        df = df.astype("float64")
        df.columns = COLS
        ts = df["date"].astype("int64")
        # Binance switched spot archives to microsecond timestamps in 2025
        ts = ts.where(ts < 10**14, ts // 1000)
        df["date"] = pd.to_datetime(ts, unit="ms", utc=True)
        return df
    return None


def download_pair(pair: str, tf: str, months: list[str], outdir: Path) -> str:
    symbol = pair.replace("/", "")
    frames = [f for m in months if (f := fetch_month(symbol, tf, m)) is not None]
    if not frames:
        return f"{pair} {tf}: no data"
    df = pd.concat(frames).drop_duplicates("date").sort_values("date").reset_index(drop=True)
    out = outdir / f"{pair.replace('/', '_')}-{tf}.feather"
    df.to_feather(out)
    return f"{pair} {tf}: {len(df)} candles {df.date.iloc[0]:%Y-%m-%d} -> {df.date.iloc[-1]:%Y-%m-%d}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", nargs="*", default=[])
    ap.add_argument("--pairs-file", help="json file with a list of pairs or a freqtrade config")
    ap.add_argument("--timeframes", nargs="+", default=["1h"])
    ap.add_argument("--start", default="2020-01")
    ap.add_argument("--end", default="2026-09")
    ap.add_argument("--datadir", default="user_data/data/binance")
    ap.add_argument("--workers", type=int, default=16)
    a = ap.parse_args()

    pairs = list(a.pairs)
    if a.pairs_file:
        data = json.loads(Path(a.pairs_file).read_text())
        if isinstance(data, dict):
            data = data["exchange"]["pair_whitelist"]
        pairs += data
    if not pairs:
        ap.error("no pairs given")

    outdir = Path(a.datadir)
    outdir.mkdir(parents=True, exist_ok=True)
    months = month_range(a.start, a.end)
    jobs = [(p, tf) for p in dict.fromkeys(pairs) for tf in a.timeframes]
    with ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(download_pair, p, tf, months, outdir): (p, tf) for p, tf in jobs}
        for f in as_completed(futs):
            try:
                print(f.result(), flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"{futs[f]}: ERROR {e}", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
