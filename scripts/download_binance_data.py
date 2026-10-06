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
    python scripts/download_binance_data.py --market futures --pairs BTC/USDT:USDT --timeframes 1h
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

HOSTS = [
    "https://data.binance.vision",
    # path-style S3 endpoint of the same bucket (useful behind strict proxies)
    "https://s3.ap-northeast-1.amazonaws.com/data.binance.vision",
]
# archive sub-path per dataset
DATASETS = {
    "spot": "data/spot/monthly/klines/{symbol}/{tf}/{symbol}-{tf}-{month}.zip",
    "futures": "data/futures/um/monthly/klines/{symbol}/{tf}/{symbol}-{tf}-{month}.zip",
    "mark": "data/futures/um/monthly/markPriceKlines/{symbol}/{tf}/{symbol}-{tf}-{month}.zip",
    "funding_rate": "data/futures/um/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{month}.zip",
}
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


def fetch_month(symbol: str, tf: str, month: str, dataset: str = "spot") -> pd.DataFrame | None:
    path = DATASETS[dataset].format(symbol=symbol, tf=tf, month=month)
    for host in HOSTS:
        try:
            raw = fetch(f"{host}/{path}")
        except Exception:
            continue
        if raw is None:
            return None
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            with zf.open(zf.namelist()[0]) as fh:
                df = pd.read_csv(fh, header=None)
        # some files ship with a header row
        if not str(df.iloc[0, 0]).isdigit():
            df = df.iloc[1:]
        if dataset == "funding_rate":
            # calc_time, funding_interval_hours, last_funding_rate -> 1h "candle" per funding event
            rate = df.iloc[:, 2].astype("float64")
            ts = (df.iloc[:, 0].astype("int64") // 3_600_000) * 3_600_000
            df = pd.DataFrame({"date": ts, "open": rate, "high": rate, "low": rate,
                               "close": rate, "volume": 0.0})
        else:
            df = df.iloc[:, :6].astype("float64")
            df.columns = COLS
        ts = df["date"].astype("int64")
        # Binance switched spot archives to microsecond timestamps in 2025
        ts = ts.where(ts < 10**14, ts // 1000)
        df["date"] = pd.to_datetime(ts, unit="ms", utc=True)
        return df
    return None


def download_pair(pair: str, tf: str, months: list[str], outdir: Path, dataset: str = "spot") -> str:
    base_quote = pair.split(":")[0]
    symbol = base_quote.replace("/", "")
    frames = [f for m in months if (f := fetch_month(symbol, tf, m, dataset)) is not None]
    if not frames:
        return f"{pair} {dataset} {tf}: no data"
    df = pd.concat(frames).drop_duplicates("date").sort_values("date").reset_index(drop=True)
    if dataset == "spot":
        out = outdir / f"{base_quote.replace('/', '_')}-{tf}.feather"
    else:
        # freqtrade futures layout: futures/BTC_USDT_USDT-1h-futures.feather
        settle = pair.split(":")[1] if ":" in pair else base_quote.split("/")[1]
        (outdir / "futures").mkdir(exist_ok=True)
        out = outdir / "futures" / f"{base_quote.replace('/', '_')}_{settle}-{tf}-{dataset}.feather"
    df.to_feather(out)
    return f"{pair} {dataset} {tf}: {len(df)} rows {df.date.iloc[0]:%Y-%m-%d} -> {df.date.iloc[-1]:%Y-%m-%d}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", nargs="*", default=[])
    ap.add_argument("--pairs-file", help="json file with a list of pairs or a freqtrade config")
    ap.add_argument("--timeframes", nargs="+", default=["1h"])
    ap.add_argument("--start", default="2020-01")
    ap.add_argument("--end", default="2026-09")
    ap.add_argument("--datadir", default="user_data/data/binance")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--market", choices=["spot", "futures"], default="spot",
                    help="futures = USDT-M perpetuals incl. mark price (1h) and funding rates")
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
    if a.market == "spot":
        jobs = [(p, tf, "spot") for p in dict.fromkeys(pairs) for tf in a.timeframes]
    else:
        jobs = [(p, tf, "futures") for p in dict.fromkeys(pairs) for tf in a.timeframes]
        jobs += [(p, "1h", ds) for p in dict.fromkeys(pairs) for ds in ("mark", "funding_rate")]
    with ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(download_pair, p, tf, months, outdir, ds): (p, tf, ds) for p, tf, ds in jobs}
        for f in as_completed(futs):
            try:
                print(f.result(), flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"{futs[f]}: ERROR {e}", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
