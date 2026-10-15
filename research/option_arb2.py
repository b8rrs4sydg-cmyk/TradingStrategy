#!/usr/bin/env python3
"""
More options arbitrage / relative-value checks on the Binance EOH hourly snapshots
(BTC, ETH, 2023-05..10).  Complements research/option_arb.py (parity vs spot, boxes).

All checks use EXECUTABLE prices (buy at ask, sell at bid), the size at the touch,
Binance fees (0.03 % of underlying per option leg, capped at 10 % of premium;
0.015 % exercise on ITM legs; perp/futures 0.05 %), and count an opportunity only
if it is still there one hour later ("persistent") - a one-snapshot violation is
usually a stale quote that nobody could have hit.

A. Static no-arbitrage bounds (same snapshot, options only -> no timing error)
   A1 call/put monotonicity   C(K1) >= C(K2), P(K1) <= P(K2) for K1 < K2
   A2 vertical width          C(K1) - C(K2) <= K2 - K1  (same for puts)
   A3 butterfly convexity     lam*C(K1) + (1-lam)*C(K3) >= C(K2), adjacent strikes
   A4 calendar                C(K, T2) >= C(K, T1) for T1 < T2 (hedged with perp/spot at T1)
B. Synthetic forward vs quarterly delivery future (same 08:00 expiry)
   sell synthetic (sell C @bid, buy P @ask) + buy future   if K + C_bid - P_ask > F_ask
   buy synthetic  (buy C @ask, sell P @bid) + sell future  if F_bid > K + C_ask - P_bid
   payoff locked at expiry.  Futures leg: real best bid/ask from the bookTicker archive
   (scripts/download_binance_bookticker.py) at the snapshot minute; else 1h close +/- half-spread.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from option_arb import F_EX, F_OPT, load, opt_fee  # noqa: E402

F_FUT = 0.0005
HALF_SPREAD = {"BTC": 0.0001, "ETH": 0.0002}   # only when no bookTicker file
SNAP_MIN = 59
QUARTERLY = ("230630", "230929", "231229", "240329")


def _book(d):
    d = d[(d["best_bid_price"] > 0) | (d["best_ask_price"] > 0)].copy()
    d["bid"] = d["best_bid_price"].where(d["best_bid_price"] > 0)
    d["ask"] = d["best_ask_price"].where(d["best_ask_price"] > 0)
    return d


def _collect(rows, name, ts, exp, legs, edge, qty, S):
    rows.append(dict(check=name, ts=ts, expiry=exp, legs=legs, edge=edge, qty=qty, S=S))


def static_bounds(d: pd.DataFrame) -> pd.DataFrame:
    d = _book(d)
    rows = []
    for (ts, exp), g in d.groupby(["ts", "expiry"], sort=False):
        S = float(g["S"].iloc[0])
        for typ in ("C", "P"):
            o = g[g["type"] == typ].sort_values("K")
            K, bid, ask = o["K"].to_numpy(), o["bid"].to_numpy(), o["ask"].to_numpy()
            bq, aq = o["best_bid_qty"].to_numpy(), o["best_ask_qty"].to_numpy()
            n = len(K)
            for i in range(n - 1):
                for k in range(i + 1, min(i + 4, n)):           # nearby strikes only
                    lo_b, lo_a, hi_b, hi_a = bid[i], ask[i], bid[k], ask[k]
                    w = K[k] - K[i]
                    if typ == "C":
                        # A1: buy C(K1) @ask, sell C(K2) @bid; payoff >= 0
                        if lo_a == lo_a and hi_b == hi_b:
                            e = hi_b - lo_a - opt_fee(S, lo_a) - opt_fee(S, hi_b) - F_EX * S
                            _collect(rows, "A1 monotone", ts, exp, f"C{K[i]:.0f}/C{K[k]:.0f}", e, min(aq[i], bq[k]), S)
                        # A2: sell C(K1) @bid, buy C(K2) @ask, max loss = w
                        if lo_b == lo_b and hi_a == hi_a:
                            e = lo_b - hi_a - w - opt_fee(S, lo_b) - opt_fee(S, hi_a) - F_EX * S
                            _collect(rows, "A2 width", ts, exp, f"C{K[i]:.0f}/C{K[k]:.0f}", e, min(bq[i], aq[k]), S)
                    else:
                        if hi_a == hi_a and lo_b == lo_b:
                            e = lo_b - hi_a - opt_fee(S, lo_b) - opt_fee(S, hi_a) - F_EX * S
                            _collect(rows, "A1 monotone", ts, exp, f"P{K[i]:.0f}/P{K[k]:.0f}", e, min(aq[k], bq[i]), S)
                        if hi_b == hi_b and lo_a == lo_a:
                            e = hi_b - lo_a - w - opt_fee(S, hi_b) - opt_fee(S, lo_a) - F_EX * S
                            _collect(rows, "A2 width", ts, exp, f"P{K[i]:.0f}/P{K[k]:.0f}", e, min(bq[k], aq[i]), S)
            # A3: adjacent butterflies
            for i in range(n - 2):
                k1, k2, k3 = K[i], K[i + 1], K[i + 2]
                lam = (k3 - k2) / (k3 - k1)
                if ask[i] == ask[i] and ask[i + 2] == ask[i + 2] and bid[i + 1] == bid[i + 1]:
                    cost = lam * ask[i] + (1 - lam) * ask[i + 2] - bid[i + 1]
                    fees = (lam * opt_fee(S, ask[i]) + (1 - lam) * opt_fee(S, ask[i + 2]) + opt_fee(S, bid[i + 1])
                            + 2 * F_EX * S)
                    q = min(aq[i] / lam, aq[i + 2] / (1 - lam), bq[i + 1])
                    _collect(rows, "A3 butterfly", ts, exp, f"{typ}{k1:.0f}/{k2:.0f}/{k3:.0f}", -cost - fees, q, S)
    return pd.DataFrame(rows)


def calendars(d: pd.DataFrame) -> pd.DataFrame:
    """Buy the longer expiry @ask, sell the shorter @bid, same strike and type.
    At T1 an ITM short leg is covered by a perp (calls) / spot (puts) trade at S(T1), so the
    combined payoff at T2 is >= 0; costs: 4 option fees+exercise, 2 hedge fees, and for calls
    the perp funding over (T2 - T1) at 10 % p.a. on the hedge notional (worst case)."""
    d = _book(d)
    rows = []
    for ts, g in d.groupby("ts", sort=False):
        S = float(g["S"].iloc[0])
        for typ in ("C", "P"):
            o = g[g["type"] == typ]
            piv_b = o.pivot_table(index="K", columns="expiry", values="bid")
            piv_a = o.pivot_table(index="K", columns="expiry", values="ask")
            qb = o.pivot_table(index="K", columns="expiry", values="best_bid_qty")
            qa = o.pivot_table(index="K", columns="expiry", values="best_ask_qty")
            exps = sorted(set(piv_b.columns) & set(piv_a.columns))
            for a in range(len(exps) - 1):
                t1, t2 = exps[a], exps[a + 1]
                gap = (t2 - t1).total_seconds() / (365 * 86400)
                e = (piv_b[t1] - piv_a[t2] - opt_fee(S, piv_b[t1]) - opt_fee(S, piv_a[t2]) - F_EX * S
                     - 2 * F_FUT * S - (0.10 * gap * S if typ == "C" else 0.0))
                for K in e.dropna().index:
                    _collect(rows, "A4 calendar", ts, t1, f"{typ}{K:.0f} {t1:%m%d}/{t2:%m%d}", float(e[K]),
                             float(min(qb.get(t1, {}).get(K, 0.0), qa.get(t2, {}).get(K, 0.0))), S)
    return pd.DataFrame(rows)


def synth_vs_future(d: pd.DataFrame, coin: str, only_book: bool = False) -> pd.DataFrame:
    d = _book(d)
    d = d[d["symbol"].str.split("-").str[1].isin(QUARTERLY)]
    c = d[d["type"] == "C"].set_index(["ts", "expiry", "K"])
    p = d[d["type"] == "P"].set_index(["ts", "expiry", "K"])
    j = c.join(p, lsuffix="_c", rsuffix="_p", how="inner").reset_index()
    j = j[(j["K"] / j["S_c"] - 1).abs() < 0.10]                     # near the money: liquid strikes
    futs = []
    for code in QUARTERLY:
        exp = pd.Timestamp("20" + code, tz="UTC") + pd.Timedelta(hours=8)
        bt = Path(f"user_data/data/binance/bookticker/{coin}USDT_{code}-1m.feather")
        if bt.exists():
            # exact best bid/ask; the EOH snapshot of hour `ts` is taken at ~ts+59min (calibrated:
            # the option-implied forward tracks the futures mid most tightly at that minute)
            f = pd.read_feather(bt)
            f["ts"] = f["date"] - pd.Timedelta(minutes=SNAP_MIN)
            f = f[f["ts"].dt.minute == 0].rename(columns={"bid": "F_bid", "ask": "F_ask"})
        else:
            f = pd.read_feather(f"user_data/data/binance/delivery/um/{coin}USDT_{code}-1h.feather")
            f = f.rename(columns={"date": "ts"})
            f["F_bid"], f["F_ask"] = f["close"] * (1 - HALF_SPREAD[coin]), f["close"] * (1 + HALF_SPREAD[coin])
        f["expiry"] = exp
        f["src"] = "bookTicker" if bt.exists() else "kline"
        futs.append(f[["ts", "expiry", "F_bid", "F_ask", "src"]])
    j = j.merge(pd.concat(futs), on=["ts", "expiry"], how="inner")
    if only_book:
        j = j[j["src"] == "bookTicker"]
    print(f"   futures leg priced from: {j.groupby('src')['ts'].nunique().to_dict()} hours")
    S, K = j["S_c"], j["K"]
    F = (j["F_bid"] + j["F_ask"]) / 2
    fee = (opt_fee(S, j["bid_c"].fillna(0)) + opt_fee(S, j["ask_p"].fillna(0)) + F_EX * S + 2 * F_FUT * F)
    sell_syn = K + j["bid_c"] - j["ask_p"] - j["F_ask"] - fee
    fee2 = (opt_fee(S, j["ask_c"].fillna(0)) + opt_fee(S, j["bid_p"].fillna(0)) + F_EX * S + 2 * F_FUT * F)
    buy_syn = j["F_bid"] - (K + j["ask_c"] - j["bid_p"]) - fee2
    out = []
    for name, e, q in (("B sell synth + long fut", sell_syn, np.minimum(j["best_bid_qty_c"], j["best_ask_qty_p"])),
                       ("B buy synth + short fut", buy_syn, np.minimum(j["best_ask_qty_c"], j["best_bid_qty_p"]))):
        out.append(pd.DataFrame(dict(check=name, ts=j["ts"], expiry=j["expiry"], legs=j["K"].map(lambda k: f"K{k:.0f}"),
                                     edge=e, qty=q, S=S, tau=(j["expiry"] - j["ts"]).dt.total_seconds() / (365 * 86400))))
    # the mid-based option-implied basis vs the futures basis (no arbitrage, just the gap)
    mid = K + (j["bid_c"] + j["ask_c"]) / 2 - (j["bid_p"] + j["ask_p"]) / 2
    gap = (mid / F - 1).groupby(j["ts"]).median() * 1e4
    print(f"   option-implied forward minus quarterly future (mid, near ATM): median {gap.median():+.1f} bp, "
          f"p5 {gap.quantile(.05):+.1f}, p95 {gap.quantile(.95):+.1f}")
    return pd.concat(out)


def episodes(pos: pd.DataFrame) -> pd.DataFrame:
    """Collapse hourly repeats of the same violation (same check, expiry, legs, consecutive hours)
    into one episode; an episode can be captured ONCE, at its best edge x touch size."""
    pos = pos.sort_values(["check", "expiry", "legs", "ts"])
    key = pos[["check", "expiry", "legs"]].astype(str).agg("|".join, axis=1)
    new = (key != key.shift()) | (pos["ts"].diff() != pd.Timedelta(hours=1))
    pos = pos.assign(ep=new.cumsum(), usd=pos["edge"] * pos["qty"])
    return pos.groupby("ep").agg(check=("check", "first"), start=("ts", "first"), hours=("ts", "size"),
                                 usd=("usd", "max"), S=("S", "first"),
                                 edge=("edge", "max"), qty=("qty", "max"), legs=("legs", "first"),
                                 expiry=("expiry", "first"))


def report(df: pd.DataFrame, coin: str, keep: list) -> list[dict]:
    rows = []
    hours = df["ts"].nunique()
    for name, g in df.dropna(subset=["edge"]).groupby("check"):
        pos = g[g["edge"] > 0]
        ep = episodes(pos) if len(pos) else pd.DataFrame(columns=["hours", "usd", "edge", "S"])
        keep.append(ep.assign(coin=coin))
        pers = ep[ep["hours"] >= 2]
        rows.append(dict(check=name, checked=len(g), profitable=len(pos),
                         hours_with_opp=f"{pos['ts'].nunique()}/{hours}", episodes=len(ep), persistent_ep=len(pers),
                         median_edge_bp=round(float((ep["edge"] / ep["S"]).median() * 1e4), 1) if len(ep) else np.nan,
                         usd_once_per_ep=round(float(ep["usd"].sum())), usd_persistent_ep=round(float(pers["usd"].sum())),
                         top10_share=round(float(ep["usd"].nlargest(10).sum() / max(ep["usd"].sum(), 1e-9)), 2)))
    return rows


def main():
    allrows, keep = [], []
    for u in ("BTCUSDT", "ETHUSDT"):
        coin = u.removesuffix("USDT")
        d = load(u)
        print(f"\n===== {u}: {d['ts'].nunique():,} hourly snapshots")
        res = [static_bounds(d), calendars(d), synth_vs_future(d, coin)]
        for r in report(pd.concat(res, ignore_index=True), coin, keep):
            allrows.append(dict(coin=coin, **r))
    pd.set_option("display.width", 250)
    print("\n" + pd.DataFrame(allrows).to_string(index=False))
    print("\nepisode           = same violation in consecutive hourly snapshots, counted once"
          "\nusd_once_per_ep   = sum over episodes of (best edge x touch size): what one fill per episode would earn"
          "\nusd_persistent_ep = same, only episodes still there one hour later (one-snapshot ones are likely stale)"
          "\ntop10_share       = share of that total coming from the 10 biggest episodes")
    ep = pd.concat(keep, ignore_index=True)
    ep.to_pickle(Path(__file__).parent / "results" / "option_arb2_episodes.pkl")


if __name__ == "__main__":
    main()
