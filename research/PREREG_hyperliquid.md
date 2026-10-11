# Pre-registration: Hyperliquid tests (written before any Hyperliquid data was downloaded)

Capital ~1M TWD ≈ 31k USDT; all trades are executed ON HYPERLIQUID (HL) unless a hedge leg on Binance
is stated.  Data: HL public info API (`scripts/download_hyperliquid.py`) + the Binance data already in
the repo.  Fees (HL base tier): perp taker 0.045 %, spot taker 0.07 %; Binance perp 0.05 %, spot 0.1 %.

## Splits (by date; HL perps start mid-2023)
- IS: start .. 2024-12-31   - OOS: 2025-01-01 .. 2025-12-31   - Holdout: 2026-01-01 .. end of data

## HL-A Options
HL had no native options market at the time of writing.  If `meta`/`spotMeta` list none, the options
part is reported as "not available on Hyperliquid" and nothing is fabricated.

## HL-B Multi-coin funding arbitrage (delta-neutral)
B1 cross-venue: for every coin with a perp on both HL and Binance USDT-M, hold short perp on the venue
   with the higher funding and long perp on the other.  Signal = trailing 3-day mean of the daily
   funding differential, annualised.  Enter > 15 %, exit < 3 %, max 10 positions, equal weight, daily.
   P&L = funding differential + relative price change of the two perps (daily closes) - costs.
   Costs per side per leg: fee + slippage (0.05 % for the top-50 coins, 0.2 % otherwise).
   Capital = 2x notional (1x margin on each venue).
B2 HL carry: long Binance spot + short HL perp, same signal on HL funding alone (enter > 15 %,
   exit < 3 %), same slots/costs/capital.
PRIMARY = B1.  Pass: OOS and holdout CAGR > 9 % (the coin-margined basis carry) and MDD < 15 %.

## HL-C New HL perp listings (meme "sniping" on HL perps)
Listing = first daily candle.  C1 long at the close of the first day (or the first hour where 1h data
exists), exit at close of day h in {1, 7, 30}; C2 short at close of day 1, hold 30 days, stop +100 %,
5 % of equity per listing, funding included.  Costs 0.045 % + 0.5 % slippage per side.
Pass: as for the Binance study (OOS and holdout CAGR > 10 %, MDD < 15 %, sign-flip p < 0.05).

## HL-D HIP-1 spot token launches (meme sniping on HL spot)
Buy every new HL spot token (quote USDC) at the close of its first hour (where 1h data exists) or of
its first day, exit at close of day h in {1, 7, 30}.  Costs 0.07 % + 1 % slippage per side.
Report mean / median / win rate per split; pass criteria as HL-C.
