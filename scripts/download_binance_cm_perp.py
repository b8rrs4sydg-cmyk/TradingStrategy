#!/usr/bin/env python3
"""
Download Binance COIN-margined perpetuals (<COIN>USD_PERP): 1h klines and funding rates.
Output: user_data/data/binance/cm_perp/<COIN>USD_PERP-1h.feather and -funding.feather

    python scripts/download_binance_cm_perp.py --coins BTC ETH SOL --start 2020-01 --end 2026-09
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

HOST = "https://s3.ap-northeast-1.amazonaws.com/data.binance.vision/data/futures/cm/monthly"
OUT = Path("user_data/data/binance/cm_perp")


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


def csv(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as zf, zf.open(zf.namelist()[0]) as fh:
        d = pd.read_csv(fh, header=None)
    if not str(d.iloc[0, 0]).isdigit():
        d = d.iloc[1:]
    return d


def coin(c, months):
    sym = f"{c}USD_PERP"
    kl, fu = [], []
    for m in months:
        raw = get(f"{HOST}/klines/{sym}/1h/{sym}-1h-{m}.zip")
        if raw:
            d = csv(raw).iloc[:, :6].astype(float)
            d.columns = ["date", "open", "high", "low", "close", "volume"]
            kl.append(d)
        raw = get(f"{HOST}/fundingRate/{sym}/{sym}-fundingRate-{m}.zip")
        if raw:
            d = csv(raw)
            fu.append(pd.DataFrame({"date": d.iloc[:, 0].astype("int64"), "rate": d.iloc[:, 2].astype(float)}))
    if not kl:
        return f"{sym}: no klines"
    OUT.mkdir(parents=True, exist_ok=True)
    k = pd.concat(kl)
    ts = k["date"].astype("int64")
    k["date"] = pd.to_datetime(ts.where(ts < 10**14, ts // 1000), unit="ms", utc=True)
    k.drop_duplicates("date").sort_values("date").reset_index(drop=True).to_feather(OUT / f"{sym}-1h.feather")
    if fu:
        f = pd.concat(fu)
        f["date"] = pd.to_datetime((f["date"] // 3_600_000) * 3_600_000, unit="ms", utc=True)
        f.drop_duplicates("date").sort_values("date").reset_index(drop=True).to_feather(OUT / f"{sym}-funding.feather")
    return f"{sym}: {len(k)} candles, {sum(len(x) for x in fu)} funding events"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", nargs="+", required=True)
    ap.add_argument("--start", default="2020-01")
    ap.add_argument("--end", default="2026-09")
    a = ap.parse_args()
    months = [p.strftime("%Y-%m") for p in pd.period_range(a.start, a.end, freq="M")]
    with ThreadPoolExecutor(12) as ex:
        for msg in ex.map(lambda c: coin(c, months), a.coins):
            print(msg, flush=True)


if __name__ == "__main__":
    main()
