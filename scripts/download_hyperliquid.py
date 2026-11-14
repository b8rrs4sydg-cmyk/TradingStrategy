#!/usr/bin/env python3
"""
Download Hyperliquid market data from the public info API (POST https://api.hyperliquid.xyz/info,
no key needed) into user_data/data/hyperliquid/:

    meta.json, spot_meta.json                       universe (perps incl. delisted flag, spot pairs)
    perp/<COIN>-1d.feather                          daily candles (full history: <= 5000 bars)
    perp/<COIN>-1h.feather                          hourly candles (API keeps only the last 5000 bars)
    perp/<COIN>-funding.feather                     hourly funding history (paginated, full history)
    spot/<TOKEN>-1d.feather, spot/<TOKEN>-1h.feather  HIP-1 spot tokens (pair "@<index>" / PURR/USDC)
    predicted_fundings.json                         current funding on Hyperliquid vs Binance / Bybit

    python scripts/download_hyperliquid.py                    # everything
    python scripts/download_hyperliquid.py --only meta        # quick connectivity check
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd

API = "https://api.hyperliquid.xyz/info"
OUT = Path("user_data/data/hyperliquid")
START_MS = int(pd.Timestamp("2023-01-01", tz="UTC").timestamp() * 1000)


def post(body: dict, retries: int = 5):
    data = json.dumps(body).encode()
    for i in range(retries):
        try:
            req = Request(API, data=data, headers={"Content-Type": "application/json", "User-Agent": "hl-research"})
            with urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except Exception as e:  # noqa: BLE001  (429 rate limit / transient)
            if i == retries - 1:
                raise
            time.sleep(2 ** i + (5 if "429" in str(e) else 0))


def candles(coin: str, interval: str, start_ms: int = START_MS) -> pd.DataFrame:
    now = int(time.time() * 1000)
    rows, t = [], start_ms
    while t < now:
        r = post({"type": "candleSnapshot", "req": {"coin": coin, "interval": interval, "startTime": t, "endTime": now}})
        if not r:
            break
        rows += r
        last = max(c["t"] for c in r)
        if last <= t or len(r) < 2:
            break
        t = last + 1
    if not rows:
        return pd.DataFrame()
    d = pd.DataFrame(rows).drop_duplicates("t").sort_values("t")
    out = pd.DataFrame({"date": pd.to_datetime(d["t"], unit="ms", utc=True)})
    for k, c in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"), ("v", "volume")):
        out[c] = d[k].astype(float).to_numpy()
    out["trades"] = d["n"].astype(int).to_numpy() if "n" in d else 0
    return out.reset_index(drop=True)


def funding(coin: str) -> pd.DataFrame:
    rows, t = [], START_MS
    now = int(time.time() * 1000)
    while t < now:
        r = post({"type": "fundingHistory", "coin": coin, "startTime": t, "endTime": now})
        if not r:
            break
        rows += r
        last = max(x["time"] for x in r)
        if last <= t:
            break
        t = last + 1
        time.sleep(0.3)
    if not rows:
        return pd.DataFrame()
    d = pd.DataFrame(rows).drop_duplicates("time").sort_values("time")
    return pd.DataFrame({"date": pd.to_datetime(d["time"], unit="ms", utc=True),
                         "funding": d["fundingRate"].astype(float).to_numpy(),
                         "premium": d["premium"].astype(float).to_numpy()}).reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["meta", "perp", "spot", "funding"], default=None)
    ap.add_argument("--coins", nargs="*", default=None, help="restrict perps to these coins")
    a = ap.parse_args()
    (OUT / "perp").mkdir(parents=True, exist_ok=True)
    (OUT / "spot").mkdir(parents=True, exist_ok=True)

    meta = post({"type": "meta"})
    spot_meta = post({"type": "spotMeta"})
    (OUT / "meta.json").write_text(json.dumps(meta))
    (OUT / "spot_meta.json").write_text(json.dumps(spot_meta))
    try:
        (OUT / "predicted_fundings.json").write_text(json.dumps(post({"type": "predictedFundings"})))
    except Exception as e:  # noqa: BLE001
        print("predictedFundings failed:", e)
    perps = [u["name"] for u in meta["universe"]]
    print(f"perps {len(perps)} (delisted {sum(bool(u.get('isDelisted')) for u in meta['universe'])}), "
          f"spot pairs {len(spot_meta['universe'])}", flush=True)
    if a.only == "meta":
        return
    if a.coins:
        perps = [p for p in perps if p in a.coins]

    if a.only in (None, "perp", "funding"):
        for i, c in enumerate(perps):
            msg = [c]
            if a.only in (None, "perp"):
                for tf in ("1d", "1h"):
                    d = candles(c, tf)
                    if len(d):
                        d.to_feather(OUT / "perp" / f"{c}-{tf}.feather")
                        msg.append(f"{tf} {len(d)} from {d.date.iloc[0]:%Y-%m-%d}")
            if a.only in (None, "funding"):
                f = funding(c)
                if len(f):
                    f.to_feather(OUT / "perp" / f"{c}-funding.feather")
                    msg.append(f"funding {len(f)}")
            print(f"[{i + 1}/{len(perps)}] " + " | ".join(msg), flush=True)

    if a.only in (None, "spot"):
        tokens = {t["index"]: t["name"] for t in spot_meta["tokens"]}
        for u in spot_meta["universe"]:
            pair = u["name"]                              # "PURR/USDC" or "@<index>"
            name = tokens.get(u["tokens"][0], pair)
            if tokens.get(u["tokens"][1]) != "USDC":
                continue
            msg = [f"{name} ({pair})"]
            for tf in ("1d", "1h"):
                d = candles(pair, tf)
                if len(d):
                    d.to_feather(OUT / "spot" / f"{name.replace('/', '_')}-{tf}.feather")
                    msg.append(f"{tf} {len(d)} from {d.date.iloc[0]:%Y-%m-%d}")
            print(" | ".join(msg), flush=True)


if __name__ == "__main__":
    main()
