#!/usr/bin/env python3
"""
Download Binance quarterly DELIVERY futures (USDT-margined 'um' and coin-margined
'cm') klines (default 1d) from the public archive.

Output: user_data/data/binance/delivery/<um|cm>/<SYMBOL>-<tf>.feather
        e.g. BTCUSDT_240329-1d.feather, ETHUSD_230630-1d.feather

    python scripts/download_binance_delivery.py --contracts-file um.txt --market um
"""
from __future__ import annotations

import argparse
import io
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pandas as pd

HOST = "https://s3.ap-northeast-1.amazonaws.com/data.binance.vision"
COLS = ["date", "open", "high", "low", "close", "volume"]


def get(url):
    for _ in range(3):
        try:
            with urlopen(Request(url, headers={"User-Agent": "ft-data"}), timeout=60) as r:
                return r.read()
        except HTTPError as e:
            if e.code in (403, 404):
                return None
        except Exception:  # noqa: BLE001
            continue
    return None


def contract(market: str, sym: str, out: Path, tf: str = "1d") -> str:
    # contract code YYMMDD -> listed at most ~9 months before expiry
    exp = pd.Timestamp("20" + sym.split("_")[1])
    months = pd.period_range(exp - pd.DateOffset(months=10), exp, freq="M")
    frames = []
    for m in months:
        raw = get(f"{HOST}/data/futures/{market}/monthly/klines/{sym}/{tf}/{sym}-{tf}-{m}.zip")
        if raw is None:
            continue
        with zipfile.ZipFile(io.BytesIO(raw)) as zf, zf.open(zf.namelist()[0]) as fh:
            d = pd.read_csv(fh, header=None, usecols=range(6))
        if not str(d.iloc[0, 0]).isdigit():
            d = d.iloc[1:]
        d = d.astype(float)
        d.columns = COLS
        ts = d["date"].astype("int64")
        d["date"] = pd.to_datetime(ts.where(ts < 10**14, ts // 1000), unit="ms", utc=True)
        frames.append(d)
    if not frames:
        return f"{sym}: no data"
    df = pd.concat(frames).drop_duplicates("date").sort_values("date").reset_index(drop=True)
    df.to_feather(out / f"{sym}-{tf}.feather")
    return f"{sym} {tf}: {len(df)} rows {df.date.iloc[0]:%Y-%m-%d} -> {df.date.iloc[-1]:%Y-%m-%d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--contracts-file", required=True)
    ap.add_argument("--market", choices=["um", "cm"], required=True)
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--timeframe", default="1d")
    a = ap.parse_args()
    out = Path("user_data/data/binance/delivery") / a.market
    out.mkdir(parents=True, exist_ok=True)
    syms = [s.strip() for s in open(a.contracts_file) if s.strip()]
    with ThreadPoolExecutor(a.workers) as ex:
        for msg in ex.map(lambda s: contract(a.market, s, out, a.timeframe), syms):
            print(msg, flush=True)


if __name__ == "__main__":
    main()
