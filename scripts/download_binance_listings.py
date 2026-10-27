#!/usr/bin/env python3
"""
Fast download of DAILY klines (+ funding for perps) for every Binance symbol ever listed,
including delisted ones, for the new-listing study (research/listing_lab.py).

Instead of probing every month (mostly 404s), it lists the months each symbol actually has in the
public archive and fetches only those.  Output uses the same files as scripts/download_binance_data.py:
    spot : user_data/data/binance/<BASE>_USDT-1d.feather
    perp : user_data/data/binance/futures/<BASE>_USDT_USDT-1d-futures.feather (+ -1h-funding_rate)

    python scripts/download_binance_listings.py --market futures --missing-only
    python scripts/download_binance_listings.py --market spot --missing-only
"""
from __future__ import annotations

import argparse
import re
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from download_binance_data import fetch_month  # noqa: E402
from download_binance_delivery import get  # noqa: E402

LIST = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
DATA = Path("user_data/data/binance")


def ls(prefix: str) -> list[str]:
    """immediate children of an S3 prefix (directories and files)"""
    out, marker = [], ""
    while True:
        q = urllib.parse.urlencode(dict(prefix=prefix, delimiter="/", marker=marker))
        raw = get(f"{LIST}?{q}")
        if raw is None:
            return out
        x = raw.decode()
        dirs = re.findall(r"<Prefix>([^<]*)</Prefix>", x)[1:]
        keys = re.findall(r"<Key>([^<]*)</Key>", x)
        out += dirs + keys
        if "<IsTruncated>true" not in x:
            return out
        marker = (re.findall(r"<NextMarker>([^<]*)</NextMarker>", x) or [(dirs + keys)[-1]])[0]


def months_of(prefix: str) -> list[str]:
    return sorted({m for k in ls(prefix) for m in re.findall(r"-(\d{4}-\d{2})\.zip$", k)})


def one(market: str, sym: str) -> str:
    base = sym[:-4]
    jobs = []
    if market == "spot":
        jobs.append(("spot", f"data/spot/monthly/klines/{sym}/1d/", DATA / f"{base}_USDT-1d.feather"))
    else:
        jobs.append(("futures", f"data/futures/um/monthly/klines/{sym}/1d/",
                     DATA / "futures" / f"{base}_USDT_USDT-1d-futures.feather"))
        jobs.append(("funding_rate", f"data/futures/um/monthly/fundingRate/{sym}/",
                     DATA / "futures" / f"{base}_USDT_USDT-1h-funding_rate.feather"))
    msg = []
    for ds, prefix, out in jobs:
        months = months_of(prefix)
        frames = [f for m in months if (f := fetch_month(sym, "1d" if ds != "funding_rate" else "1h", m, ds)) is not None]
        if not frames:
            msg.append(f"{ds}: none")
            continue
        df = pd.concat(frames).drop_duplicates("date").sort_values("date").reset_index(drop=True)
        df.to_feather(out)
        msg.append(f"{ds}: {len(df)} {df.date.iloc[0]:%Y-%m-%d}")
    return f"{sym} " + " | ".join(msg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=["spot", "futures"], required=True)
    ap.add_argument("--missing-only", action="store_true")
    ap.add_argument("--workers", type=int, default=32)
    a = ap.parse_args()
    root = "data/spot/monthly/klines/" if a.market == "spot" else "data/futures/um/monthly/klines/"
    syms = [p[len(root):-1] for p in ls(root)]
    syms = [s for s in syms if s.endswith("USDT")]
    if a.missing_only:
        have = (lambda s: (DATA / f"{s[:-4]}_USDT-1d.feather").exists()) if a.market == "spot" else \
               (lambda s: (DATA / "futures" / f"{s[:-4]}_USDT_USDT-1d-futures.feather").exists())
        syms = [s for s in syms if not have(s)]
    print(f"{len(syms)} symbols", flush=True)
    (DATA / "futures").mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(a.workers) as ex:
        for m in ex.map(lambda s: one(a.market, s), syms):
            print(m, flush=True)


if __name__ == "__main__":
    main()
