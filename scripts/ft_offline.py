#!/usr/bin/env python3
"""
Run freqtrade without access to the exchange API (backtesting / lookahead-analysis /
recursive-analysis / webserver only).

Freqtrade always loads the exchange's market list at start-up, even for
backtesting.  In restricted networks that call fails, so this wrapper replaces
the market loading with a synthetic list of spot markets built from the
locally available data files (user_data/data/<exchange>/*.feather).

Usage (same arguments as the freqtrade CLI):
    python scripts/ft_offline.py backtesting -c configs/config_backtest.json ...

If your machine can reach the exchange, simply use `freqtrade ...` instead.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from freqtrade.exchange import exchange as ft_exchange

DATA_DIR = Path("user_data/data/binance")


def _market(base: str, quote: str, settle: str | None) -> dict:
    swap = settle is not None
    symbol = f"{base}/{quote}:{settle}" if swap else f"{base}/{quote}"
    return {
            "id": f"{base}{quote}", "symbol": symbol, "base": base, "quote": quote,
            "baseId": base, "quoteId": quote, "settle": settle, "settleId": settle,
            "type": "swap" if swap else "spot", "spot": not swap, "margin": False,
            "swap": swap, "future": False, "option": False, "contract": swap,
            "linear": True if swap else None, "inverse": False if swap else None,
            "active": True, "taker": 0.001, "maker": 0.001, "contractSize": 1.0 if swap else None,
            "expiry": None, "expiryDatetime": None, "strike": None, "optionType": None,
            "precision": {"amount": 1e-8, "price": 1e-8, "cost": None, "base": None, "quote": None},
            "limits": {
                "amount": {"min": 1e-8, "max": 1e12},
                "price": {"min": 1e-8, "max": 1e9},
                "cost": {"min": 5.0, "max": None},
                "leverage": {"min": 1, "max": 20} if swap else {"min": None, "max": None},
            },
            "created": None, "info": {},
    }


def _synthetic_markets() -> dict:
    markets = {}
    for f in DATA_DIR.glob("*.feather"):
        m = re.match(r"^([A-Z0-9]+)_([A-Z0-9]+)-\w+\.feather$", f.name)
        if m:
            mk = _market(m.group(1), m.group(2), None)
            markets[mk["symbol"]] = mk
    for f in (DATA_DIR / "futures").glob("*-futures.feather"):
        m = re.match(r"^([A-Z0-9]+)_([A-Z0-9]+)_([A-Z0-9]+)-\w+-futures\.feather$", f.name)
        if m:
            mk = _market(*m.groups())
            markets[mk["symbol"]] = mk
    return markets


async def _offline_reload_markets(self, reload: bool = False) -> None:  # noqa: ARG001
    self._api_async.set_markets(_synthetic_markets())


_orig_fill_tiers = ft_exchange.Exchange.fill_leverage_tiers


def _fill_tiers_with_default(self) -> None:
    """Bundled Binance tiers (dry-run file) + a conservative default for delisted pairs."""
    _orig_fill_tiers(self)
    default = [{"minNotional": 0.0, "maxNotional": None, "maintenanceMarginRate": 0.01,
                "maxLeverage": 20.0, "maintAmt": 0.0}]
    for sym, mk in self._api_async.markets.items():
        if mk.get("swap") and sym not in self._leverage_tiers:
            self._leverage_tiers[sym] = default


ft_exchange.Exchange._api_reload_markets = _offline_reload_markets
ft_exchange.Exchange.fill_leverage_tiers = _fill_tiers_with_default
ft_exchange.Exchange.fetch_trading_fees = lambda self: {}

if __name__ == "__main__":
    from freqtrade.main import main

    sys.exit(main(sys.argv[1:]))
