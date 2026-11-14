#!/usr/bin/env bash
# Reproduce all FundingCarry results from scratch.
#
#   bash scripts/reproduce.sh            # download data + all backtests
#   SKIP_DOWNLOAD=1 bash scripts/reproduce.sh
#
# If your machine can reach the Binance API you may replace `python scripts/ft_offline.py`
# with plain `freqtrade`.
set -euo pipefail
cd "$(dirname "$0")/.."

FT="python scripts/ft_offline.py"
R=research/results
mkdir -p "$R"

if [ -z "${SKIP_DOWNLOAD:-}" ]; then
  # spot 1h (+1d) and USDT-M futures 1h incl. mark price and funding rates
  python scripts/download_binance_data.py --pairs-file configs/pairs_universe.json --timeframes 1h 1d --start 2019-09 --end 2026-09
  python scripts/download_binance_data.py --pairs-file configs/pairs_holdout_b.json --timeframes 1h 1d --start 2019-09 --end 2026-09
  python scripts/download_binance_data.py --market futures --pairs-file configs/pairs_universe_futures.json --timeframes 1h 1d --start 2019-09 --end 2026-09
  python scripts/download_binance_data.py --market futures --pairs-file configs/pairs_holdout_b_futures.json --timeframes 1h 1d --start 2019-09 --end 2026-09
fi

# synthetic delta-neutral carry instruments (<COIN>CARRY/USDT)
python scripts/build_carry_data.py --pairs-file configs/pairs_universe.json --out-pairs configs/pairs_carry.json
python scripts/build_carry_data.py --pairs-file configs/pairs_holdout_b.json --out-pairs configs/pairs_carry_holdout_b.json

bt() {  # config timerange name [extra args]
  $FT backtesting -c "$1" --userdir user_data --strategy FundingCarry --timerange "$2" \
      --cache none --export trades --backtest-filename "$3" "${@:4}" > /dev/null
  python research/analyze.py | tee "$R/$3.txt"
}

bt configs/config_carry.json           20200601-20240101 carry_is          # in-sample
bt configs/config_carry.json           20240101-20261001 carry_oos         # out-of-sample
bt configs/config_carry_holdout_b.json 20200601-20261001 carry_holdout_b   # unseen coins
bt configs/config_carry.json           20200601-20261001 carry_full        # full period
python research/analyze.py --plot "$R/carry_full_equity.png" > /dev/null
python research/monte_carlo.py --runs 5000 | tee "$R/carry_full_montecarlo.txt"
bt configs/config_carry.json           20200601-20261001 carry_full_fee2x --fee 0.002

# bias checks
python research/pit_check.py | tail -2 | tee "$R/carry_pit_check.txt"
$FT recursive-analysis -c configs/config_carry.json --userdir user_data --strategy FundingCarry \
    --timerange 20210101-20210401 --startup-candle 100 200 500

# parameter sensitivity (in-sample)
python research/sensitivity.py --strategy FundingCarry --grid carry --config configs/config_carry.json \
    --timerange 20200601-20240101 --out "$R/sensitivity_carry_is.json"
