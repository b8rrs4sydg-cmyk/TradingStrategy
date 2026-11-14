"""Black-Scholes helpers (no rates: Binance options are USDT-settled, carry is ~0 at weekly tenors)."""
from __future__ import annotations

import numpy as np
from scipy.special import ndtr
from scipy.stats import norm


def price(S, K, T, sigma, is_call):
    S, K, T, sigma = map(np.asarray, (S, K, T, sigma))
    sq = sigma * np.sqrt(np.maximum(T, 1e-12))
    d1 = (np.log(S / K) + 0.5 * sigma ** 2 * T) / sq
    d2 = d1 - sq
    call = S * ndtr(d1) - K * ndtr(d2)
    return np.where(is_call, call, call - S + K)


def delta(S, K, T, sigma, is_call):
    sq = sigma * np.sqrt(np.maximum(T, 1e-12))
    d1 = (np.log(S / K) + 0.5 * sigma ** 2 * T) / sq
    return np.where(is_call, ndtr(d1), ndtr(d1) - 1)


def vega(S, K, T, sigma):
    sq = sigma * np.sqrt(np.maximum(T, 1e-12))
    d1 = (np.log(S / K) + 0.5 * sigma ** 2 * T) / sq
    return S * norm.pdf(d1) * np.sqrt(T)


def implied_vol(p, S, K, T, is_call, lo=0.01, hi=5.0, iters=60):
    """vectorised bisection"""
    p, S, K, T = map(lambda x: np.asarray(x, float), (p, S, K, T))
    is_call = np.asarray(is_call)
    a = np.full(p.shape, lo)
    b = np.full(p.shape, hi)
    for _ in range(iters):
        m = 0.5 * (a + b)
        too_high = price(S, K, T, m, is_call) > p
        b = np.where(too_high, m, b)
        a = np.where(too_high, a, m)
    iv = 0.5 * (a + b)
    intrinsic = np.where(is_call, np.maximum(S - K, 0), np.maximum(K - S, 0))
    return np.where((p > intrinsic) & (p > 0), iv, np.nan)
