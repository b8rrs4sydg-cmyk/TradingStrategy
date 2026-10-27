#!/usr/bin/env python3
"""
Options arbitrage scanner on Binance European options (USDT-settled), using the
hourly EOH summaries (best bid/ask + size for every contract), 2023-05..2023-10.

Checks, with EXECUTABLE prices only (buy at ask, sell at bid) and real fees:

1. Put-call parity
   conversion : sell call @bid, buy put @ask, buy spot @S*(1+f_spot)   -> receives K at expiry
                profit = C_bid - P_ask - S_buy + K*DF
   reversal   : buy call @ask, sell put @bid, short perp @S*(1-f_perp) -> pays K at expiry
                profit = P_bid - C_ask + S_sell - K*DF
2. Box spread (K1 < K2, same expiry), payoff exactly (K2 - K1) at expiry
   long box  : buy C1, sell C2, sell P1, buy P2       profit = (K2-K1)*DF - cost
   short box : sell C1, buy C2, buy P1, sell P2       profit = credit - (K2-K1)*DF

DF discounts at `hurdle` p.a. (opportunity cost of capital: what the funding-carry
strategy earns), so a "profit" must beat simply running FundingCarry.

Fees (Binance options, VIP0): trade 0.03 % of underlying notional per contract
(capped at 10 % of premium), exercise 0.015 % of notional on ITM legs; spot 0.1 %,
perp 0.05 %.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

OPT = Path("user_data/data/binance/options")
SPOT = Path("user_data/data/binance")
F_OPT, F_EX, F_SPOT, F_PERP = 0.0003, 0.00015, 0.001, 0.0005


def opt_fee(S, premium):
    return np.minimum(F_OPT * S, 0.10 * premium)


def load(under: str) -> pd.DataFrame:
    d = pd.read_feather(OPT / f"{under}-EOH.feather")
    d["ts"] = pd.to_datetime(d["date"]) + pd.to_timedelta(d["hour"].astype(int), unit="h")
    d["ts"] = d["ts"].dt.tz_localize("UTC")
    d["expiry"] = pd.to_datetime(d["symbol"].str.split("-").str[1], format="%y%m%d").dt.tz_localize("UTC") + pd.Timedelta(hours=8)
    d["K"] = d["symbol"].str.split("-").str[2].astype(float)
    d["tau_y"] = (d["expiry"] - d["ts"]).dt.total_seconds() / (365 * 86400)
    spot = pd.read_feather(SPOT / f"{under.removesuffix('USDT')}_USDT-1h.feather").set_index("date")["close"]
    d["S"] = d["ts"].map(spot)
    d = d[(d["tau_y"] > 1 / 365) & d["S"].notna()]
    for c in ("best_bid_price", "best_ask_price", "best_bid_qty", "best_ask_qty"):
        d[c] = pd.to_numeric(d[c], errors="coerce").fillna(0.0)
    return d


def parity(d: pd.DataFrame, hurdle: float):
    c = d[d["type"] == "C"].set_index(["ts", "expiry", "K"])
    p = d[d["type"] == "P"].set_index(["ts", "expiry", "K"])
    j = c.join(p, lsuffix="_c", rsuffix="_p", how="inner")
    S, K, T = j["S_c"], j.index.get_level_values("K").to_numpy(), j["tau_y_c"]
    DF = np.exp(-hurdle * T)
    ok_conv = (j["best_bid_price_c"] > 0) & (j["best_ask_price_p"] > 0)
    conv = (j["best_bid_price_c"] - j["best_ask_price_p"] - S * (1 + F_SPOT) + K * DF
            - opt_fee(S, j["best_bid_price_c"]) - opt_fee(S, j["best_ask_price_p"])
            - F_EX * S - S * F_SPOT)                       # exercise one leg + sell spot at expiry
    ok_rev = (j["best_ask_price_c"] > 0) & (j["best_bid_price_p"] > 0)
    # A short PERP does not raise cash, so there is no discounting benefit on K; instead
    # perp margin (~20 % of S) and the short-put margin are tied up -> charge the hurdle on them.
    margin = 0.2 * S + 0.2 * S
    rev = (j["best_bid_price_p"] - j["best_ask_price_c"] + S * (1 - F_PERP) - K
           - opt_fee(S, j["best_ask_price_c"]) - opt_fee(S, j["best_bid_price_p"])
           - F_EX * S - S * F_PERP - hurdle * T * margin)
    out = pd.DataFrame({
        "conv_edge": conv.where(ok_conv), "rev_edge": rev.where(ok_rev),
        "conv_qty": np.minimum(j["best_bid_qty_c"], j["best_ask_qty_p"]),
        "rev_qty": np.minimum(j["best_ask_qty_c"], j["best_bid_qty_p"]),
        "S": S, "T": T,
    })
    return out


def boxes(d: pd.DataFrame, hurdle: float, max_pairs_per_expiry: int = 400):
    rows = []
    for (ts, exp), g in d.groupby(["ts", "expiry"]):
        c = g[g["type"] == "C"].set_index("K")
        p = g[g["type"] == "P"].set_index("K")
        ks = sorted(set(c.index) & set(p.index))
        if len(ks) < 2:
            continue
        S = float(g["S"].iloc[0])
        T = float(g["tau_y"].iloc[0])
        DF = np.exp(-hurdle * T)
        n = 0
        for i in range(len(ks)):
            for k in range(i + 1, len(ks)):
                K1, K2 = ks[i], ks[k]
                c1, c2, p1, p2 = c.loc[K1], c.loc[K2], p.loc[K1], p.loc[K2]
                fees4 = 4 * F_OPT * S + 2 * F_EX * S
                # long box
                if min(c1.best_ask_price, c2.best_bid_price, p1.best_bid_price, p2.best_ask_price) > 0:
                    cost = c1.best_ask_price - c2.best_bid_price - p1.best_bid_price + p2.best_ask_price
                    edge = (K2 - K1) * DF - cost - fees4
                    qty = min(c1.best_ask_qty, c2.best_bid_qty, p1.best_bid_qty, p2.best_ask_qty)
                    rows.append(("long", ts, exp, K1, K2, edge, qty, (K2 - K1), T))
                # short box
                if min(c1.best_bid_price, c2.best_ask_price, p1.best_ask_price, p2.best_bid_price) > 0:
                    credit = c1.best_bid_price - c2.best_ask_price - p1.best_ask_price + p2.best_bid_price
                    # selling a box requires collateral = max loss (K2-K1): no cash to invest,
                    # and that collateral earns nothing -> charge the hurdle on it
                    edge = credit - (K2 - K1) - fees4 - hurdle * T * (K2 - K1)
                    qty = min(c1.best_bid_qty, c2.best_ask_qty, p1.best_ask_qty, p2.best_bid_qty)
                    rows.append(("short", ts, exp, K1, K2, edge, qty, (K2 - K1), T))
                n += 1
                if n >= max_pairs_per_expiry:
                    break
    return pd.DataFrame(rows, columns=["side", "ts", "expiry", "K1", "K2", "edge", "qty", "width", "T"])


def summarise(name, edge, qty, notional, T):
    pos = edge > 0
    usd = (edge * qty)[pos]
    ann = (edge / notional / T)[pos]
    hours = edge[pos].index.get_level_values(0).nunique() if isinstance(edge.index, pd.MultiIndex) else None
    print(f"{name}: checked {int(edge.notna().sum()):,}  profitable {int(pos.sum()):,} "
          f"({pos.mean() * 100:.3f}%)  hours with >=1 opportunity: {hours}")
    if pos.any():
        print(f"   edge per unit: median {edge[pos].median():.2f} USDT, p90 {edge[pos].quantile(.9):.2f}; "
              f"annualised on notional: median {ann.median() * 100:.1f}%; size at touch: median {qty[pos].median():.3f}")
        print(f"   capturable USDT if every opportunity filled once at touch size: {usd.sum():,.0f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hurdle", type=float, default=0.10)
    a = ap.parse_args()
    for u in ("BTCUSDT", "ETHUSDT"):
        d = load(u)
        print(f"\n===== {u}: {d['ts'].nunique():,} hourly snapshots, {d['symbol'].nunique():,} contracts")
        par = parity(d, a.hurdle)
        summarise("conversion (sell C, buy P, buy spot)", par["conv_edge"], par["conv_qty"], par["S"], par["T"])
        summarise("reversal   (buy C, sell P, short perp)", par["rev_edge"], par["rev_qty"], par["S"], par["T"])
        bx = boxes(d[d["ts"].dt.hour % 6 == 0], a.hurdle)      # every 6th hour to keep it fast
        for side in ("long", "short"):
            b = bx[bx["side"] == side].set_index(["ts", "expiry", "K1", "K2"])
            summarise(f"{side} box (sampled every 6h)", b["edge"], b["qty"], b["width"], b["T"])


if __name__ == "__main__":
    main()
