#!/usr/bin/env python3
"""
Download Binance USDT-M futures *sentiment* data from the public archive and
aggregate it to one row per day:

  metrics (5-minute files, from ~2021-12):
    oi            open interest (contracts), last value of the day
    oi_value      open interest in USDT, last value of the day
    top_acc_ls    top-trader long/short ACCOUNT ratio, daily mean
    top_pos_ls    top-trader long/short POSITION ratio, daily mean
    glob_ls       all-accounts long/short ratio, daily mean
    taker_ls      taker buy/sell volume ratio, daily mean
  premiumIndexKlines (1d):
    premium       close of the perp-vs-index premium index (basis)

Output: user_data/data/binance/metrics/<BASE>_USDT-1d-metrics.feather
        (index = UTC day; a day's values are only known after the day closes)

    python scripts/download_binance_metrics.py --pairs-file configs/pairs_ab_futures.json
"""
from __future__ import annotations

import argparse
import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pandas as pd

HOST = "https://s3.ap-northeast-1.amazonaws.com/data.binance.vision"
OUT = Path("user_data/data/binance/metrics")


def get(url: str) -> bytes | None:
    for _ in range(3):
        try:
            with urlopen(Request(url, headers={"User-Agent": "ft-data"}), timeout=60) as r:
                return r.read()
        except HTTPError as e:
            if e.code in (403, 404):
                return None
        except Exception:  # noqa: BLE001  transient network error -> retry
            continue
    return None


def read_zip_csv(raw: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(raw)) as zf, zf.open(zf.namelist()[0]) as fh:
        return pd.read_csv(fh)


def metrics_day(symbol: str, day: str) -> dict | None:
    raw = get(f"{HOST}/data/futures/um/daily/metrics/{symbol}/{symbol}-metrics-{day}.zip")
    if raw is None:
        return None
    d = read_zip_csv(raw)
    if d.empty:
        return None
    return {
        "date": pd.Timestamp(day, tz="UTC"),
        "oi": float(d["sum_open_interest"].iloc[-1]),
        "oi_value": float(d["sum_open_interest_value"].iloc[-1]),
        "top_acc_ls": float(d["count_toptrader_long_short_ratio"].mean()),
        "top_pos_ls": float(d["sum_toptrader_long_short_ratio"].mean()),
        "glob_ls": float(d["count_long_short_ratio"].mean()),
        "taker_ls": float(d["sum_taker_long_short_vol_ratio"].mean()),
    }


def premium(symbol: str, months: list[str]) -> pd.Series:
    rows = []
    for m in months:
        raw = get(f"{HOST}/data/futures/um/monthly/premiumIndexKlines/{symbol}/1d/{symbol}-1d-{m}.zip")
        if raw is None:
            continue
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf, zf.open(zf.namelist()[0]) as fh:
                d = pd.read_csv(fh, header=None)
        except Exception:  # noqa: BLE001  empty / corrupt monthly file
            continue
        if d.empty:
            continue
        if not str(d.iloc[0, 0]).isdigit():
            d = d.iloc[1:]
        if d.empty:
            continue
        ts = d.iloc[:, 0].astype("int64")
        ts = ts.where(ts < 10**14, ts // 1000)
        rows.append(pd.Series(d.iloc[:, 4].astype(float).values,
                              index=pd.to_datetime(ts.values, unit="ms", utc=True)))
    return pd.concat(rows).sort_index() if rows else pd.Series(dtype=float)


def run_pair(pair: str, days: list[str], months: list[str], workers: int) -> str:
    base = pair.split("/")[0]
    symbol = f"{base}USDT"
    with ThreadPoolExecutor(workers) as ex:
        rows = [r for r in ex.map(lambda d: metrics_day(symbol, d), days) if r]
    df = pd.DataFrame(rows).set_index("date").sort_index() if rows else pd.DataFrame()
    prem = premium(symbol, months)
    if not prem.empty:
        prem.index = prem.index.normalize()
        df = df.join(prem.rename("premium"), how="outer") if not df.empty else prem.rename("premium").to_frame()
    if df.empty:
        return f"{pair}: no data"
    OUT.mkdir(parents=True, exist_ok=True)
    df.reset_index().rename(columns={"index": "date"}).to_feather(OUT / f"{base}_USDT-1d-metrics.feather")
    return f"{pair}: {len(df)} days, metrics from {df['oi'].first_valid_index() if 'oi' in df else None}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs-file", required=True)
    ap.add_argument("--start", default="2021-12-01")
    ap.add_argument("--end", default="2026-09-30")
    ap.add_argument("--workers", type=int, default=48)
    ap.add_argument("--overwrite", action="store_true")
    a = ap.parse_args()
    days = [d.strftime("%Y-%m-%d") for d in pd.date_range(a.start, a.end, freq="D")]
    months = [p.strftime("%Y-%m") for p in pd.period_range("2020-01", a.end[:7], freq="M")]
    for pair in json.load(open(a.pairs_file)):
        if (OUT / f"{pair.split('/')[0]}_USDT-1d-metrics.feather").exists() and not a.overwrite:
            continue  # resume
        print(run_pair(pair, days, months, a.workers), flush=True)


if __name__ == "__main__":
    main()
