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


def _synthetic_markets() -> dict:
    markets = {}
    for f in DATA_DIR.glob("*.feather"):
        m = re.match(r"^([A-Z0-9]+)_([A-Z0-9]+)-\w+\.feather$", f.name)
        if not m:
            continue
        base, quote = m.groups()
        symbol = f"{base}/{quote}"
        markets[symbol] = {
            "id": f"{base}{quote}", "symbol": symbol, "base": base, "quote": quote,
            "baseId": base, "quoteId": quote, "settle": None, "settleId": None,
            "type": "spot", "spot": True, "margin": False, "swap": False, "future": False,
            "option": False, "contract": False, "linear": None, "inverse": None,
            "active": True, "taker": 0.001, "maker": 0.001, "contractSize": None,
            "expiry": None, "expiryDatetime": None, "strike": None, "optionType": None,
            "precision": {"amount": 1e-8, "price": 1e-8, "cost": None, "base": None, "quote": None},
            "limits": {
                "amount": {"min": 1e-8, "max": 1e12},
                "price": {"min": 1e-8, "max": 1e9},
                "cost": {"min": 5.0, "max": None},
                "leverage": {"min": None, "max": None},
            },
            "created": None, "info": {},
        }
    return markets


async def _offline_reload_markets(self, reload: bool = False) -> None:  # noqa: ARG001
    self._api_async.set_markets(_synthetic_markets())


ft_exchange.Exchange._api_reload_markets = _offline_reload_markets
ft_exchange.Exchange.fetch_trading_fees = lambda self: {}

if __name__ == "__main__":
    from freqtrade.main import main

    sys.exit(main(sys.argv[1:]))
