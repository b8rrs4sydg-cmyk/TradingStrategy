# Pre-registration: new-listing ("meme sniping", CEX version) and small-cap funding carry

Written and committed BEFORE any result was computed. Capital: ~1M TWD ≈ 31k USDT, so capacity of
~1–3k USDT per position is enough.

## Data
- All Binance USDT-M perpetuals ever listed (905 in the archive incl. delisted), 1d klines + funding.
- All Binance spot USDT pairs ever listed (760), 1d klines.
- Listing day = first daily candle; contracts whose first candle is the first archive month (2019-09
  for perps, 2017-08 for spot) are not new listings and are excluded.
- On-chain meme sniping (pump.fun / Raydium / Uniswap) cannot be tested here: no DEX or chain data is
  reachable from this environment.

## Splits (by listing date)
- In-sample (IS): listings 2020-01 .. 2023-12
- Out-of-sample (OOS): 2024-01 .. 2025-06
- Holdout: 2025-07 .. 2026-08 (positions still open at the end of data are closed at the last close)

## H1 "snipe long" (spot and perp)
Buy at the open of the first daily candle (the first traded price: optimistic for the buyer),
sell at the close of day h in {0, 1, 3, 7, 30}. Cost 0.1 % spot / 0.05 % perp per side + 0.5 % slippage
per side (listing-day books are thin and the first print is a spike). Reported: mean, median and
win rate per trade, by split. Expectation: negative mean (buying the hype).

## H2 "fade new perp listings" (short)
Short at the close of day d after listing, hold H days, funding paid/received included (shorts pay
when funding < 0, the usual case for crowded new-listing shorts), stop when the daily high reaches
entry x (1 + stop) (filled at that level + 1 % slippage). Cost 0.05 % per side + 0.2 % slippage.
Portfolio: each listing gets w of current equity as short notional (1x collateral), unlimited
concurrent positions, daily mark-to-market.
- PRIMARY (the one that is judged): d = 1, H = 30, stop = 100 %, w = 5 %.
- Grid shown only as a sensitivity map: d in {0,1,3}, H in {7,14,30,60}, stop in {50 %, 100 %, none}.
Pass criteria for the PRIMARY on OOS AND holdout: mean trade > 0 after costs, CAGR > 10 %, MDD < 15 %,
and a sign-flip permutation p < 0.05 on the trade returns.

## H3 small-cap funding carry
Delta-neutral long spot / short perp on ALL coins that have both a Binance spot and a USDT-M perp
(not just the 50 large caps of FundingCarry), daily: enter when the trailing-3-day mean funding
annualises above 20 %, exit when it falls below 5 %, at most 10 positions, equal weight,
costs 0.15 % spot + 0.05 % perp per side + 0.3 % slippage per side for coins outside the top 50.
Capital 2x notional (spot + perp margin). Pass criteria: OOS and holdout CAGR > FundingCarry's
(~5 %) and MDD < 15 %.
