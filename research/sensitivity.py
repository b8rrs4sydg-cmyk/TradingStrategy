#!/usr/bin/env python3
"""
One-at-a-time parameter sensitivity analysis.

Every parameter of the strategy is moved to its neighbouring values while all
others stay at default.  A robust (not over-fitted) strategy shows a *plateau*:
performance degrades gracefully instead of collapsing next to the chosen value.

    python research/sensitivity.py --strategy RotationDip --timerange 20200601-20240101
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from analyze import latest_zip, load, summarize  # noqa: E402

GRID = {
    "top_n": [5, 8, 10, 15, 20],
    "mom_hours": [72, 96, 120, 168, 240],
    "regime_sma": [30, 40, 50, 75, 100],
    "breadth_min": [0.4, 0.45, 0.5, 0.55, 0.6],
    "rsi_pullback": [30, 33, 35, 38, 40],
    "btc_rsi_guard": [0, 25, 30, 35],
    "breadth_exit": [0.3, 0.35, 0.4, 0.45, 0.5],
    "breadth_days": [10, 15, 20, 30, 40],
    "crash_breadth": [0.15, 0.2, 0.25, 0.3, 0.35],
    "stoploss": [-0.07, -0.08, -0.10, -0.12, -0.15],
    "roi0": [0.03, 0.04, 0.05, 0.06, 0.08],
    "max_trade_days": [5, 7, 10, 14, 20],
}
# the 4h research version used a momentum window in days
GRID_4H = {**{k: v for k, v in GRID.items() if k not in ("mom_hours", "breadth_days", "crash_breadth")},
           "mom_days": [10, 15, 20, 30, 45]}

# FundingCarry (delta-neutral funding carry)
GRID_CARRY = {
    "enter_rate": [0.0001, 0.00015, 0.0002, 0.0003, 0.0004],
    "lookback_h": [24, 48, 72, 120, 168],
    "stoploss": [-0.03, -0.05, -0.08, -0.15],
    # note: max_open_trades cannot be varied via --strategy-list (config wins);
    # slot counts are tested separately with --max-open-trades
}

VARIANTS_FILE = Path("user_data/strategies/_sensitivity_variants.py")


def build_variants(base: str, grid: dict) -> list[str]:
    lines = [f"from {base} import {base}\n"]
    names = []
    for param, values in grid.items():
        for v in values:
            tag = str(v).replace("-", "m").replace(".", "p")
            name = f"S_{param}_{tag}"
            body = []
            if param == "roi0":
                body.append(f"    minimal_roi = {{'0': {v}, '4320': {v / 2}, '7200': 0.0}}")
            else:
                body.append(f"    {param} = {v!r}")
            lines.append(f"\n\nclass {name}({base}):\n" + "\n".join(body) + "\n")
            names.append(name)
    VARIANTS_FILE.write_text("".join(lines))
    return names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", default="RotationDipH1")
    ap.add_argument("--grid", choices=["1h", "4h", "carry"], default="1h")
    ap.add_argument("--timerange", default="20200601-20240101")
    ap.add_argument("--config", default="configs/config_backtest.json")
    ap.add_argument("--out", default="research/results/sensitivity.json")
    ap.add_argument("--timeframe", default="1h")
    a = ap.parse_args()

    names = build_variants(a.strategy, {"1h": GRID, "4h": GRID_4H, "carry": GRID_CARRY}[a.grid])
    rows = []
    try:
        for i in range(0, len(names), 12):
            chunk = names[i:i + 12]
            cmd = [sys.executable, "scripts/ft_offline.py", "backtesting", "-c", a.config,
                   "--userdir", "user_data", "--timerange", a.timerange, "--cache", "none",
                   "--export", "trades", "--timeframe", a.timeframe, "--strategy-list", *chunk]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            res = load(latest_zip())
            for n in chunk:
                r = summarize(n, res[n])
                r.pop("yearly_%")
                rows.append(r)
                print(r, flush=True)
    finally:
        VARIANTS_FILE.unlink(missing_ok=True)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(rows, indent=1, default=float))


if __name__ == "__main__":
    main()
