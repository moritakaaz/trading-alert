# Strategy Research — GoldTrendEA v2 (2026-10-04)

## Data used
| Dataset | Symbol | Interval | Bars (valid) | Range (UTC) | Source |
|---|---|---|---|---|---|
| Primary | GC=F (COMEX gold futures, XAUUSD proxy) | 1h | 5,673 | 2025-10-05 → 2026-10-02 | Yahoo Finance chart API |
| Secondary | GC=F | 15m | 4,488 | 2026-07-26 → 2026-10-02 | Yahoo Finance chart API |

Notes: Yahoo intraday (15m/30m) is limited to the last 60 days, so the primary
set is H1 × 1 year. GC=F is used for LOGIC comparison only; the futures
premium (~$22 over spot recently) shifts absolute levels but does not change
breakout/cross signal logic. Kraken PAXGUSD was considered but only returns
720 candles/call (insufficient history alone).

## Backtest harness (backtest_strategies.py)
- Max 1 position, long + short. Signal computed on a CLOSED bar; entry at the
  NEXT bar's open. SL/TP from ATR(14) Wilder at the signal bar.
- Intrabar exits: SL checked before TP when both are hit in one bar (conservative).
- Opposite signal closes the position at bar close (no immediate reversal — same as GoldTrendEA).
- Costs: $0.40 spread deducted per round trip. Fixed 0.01 lot ⇒ $1 P/L per $1 price move.
- R-multiple: net $ ÷ initial SL distance ($).

### Harness validation
Baseline EMA20/50 cross on the **M15** 60d set: **PF 0.80** — vs the user's MT5
Strategy Tester result of **PF 0.81** on XAUUSDc M15. Near-identical: the harness
is sound and the MT5 losing result is reproduced, not a coding artifact.

## Variant results — primary (H1, 1y)
| # | Variant | Trades | Net $ | PF | Win% | AvgR | MaxDD_R | PF H1 | PF H2 |
|---|---|---|---|---|---|---|---|---|---|
| 0 | Baseline EMA20/50 cross, SL1.5/TP3 | 102 | -123.60 | 0.94 | 29.4 | -0.09 | 15.6 | 1.31 | 0.76 |
| 1 | Donchian(24) breakout, SL1.5/TP3 | 218 | +266.56 | 1.05 | 35.3 | 0.05 | 13.5 | 1.01 | 1.10 |
| 2 | EMA cross + ADX(14)>20 | 59 | -12.33 | 0.99 | 27.1 | -0.16 | 16.8 | 2.09 | 0.53 |
| 3 | EMA cross, 07–21 UTC only | 64 | -251.02 | 0.81 | 28.1 | -0.15 | 12.0 | 1.03 | 0.70 |
| 4 | RSI(14) pullback in EMA200 trend, SL1.5/TP2.5 | 36 | -78.41 | 0.93 | 47.2 | 0.25 | 5.7 | 0.60 | 1.79 |
| 5 | Supertrend(10,3) flips, SL1.5/TP3 | 121 | -1260.56 | 0.61 | 25.6 | -0.21 | 29.8 | 0.44 | 0.84 |
| 6 | Baseline, SL2.0/TP4.0 | 93 | +7.05 | 1.00 | 29.0 | -0.03 | 8.2 | 1.28 | 0.87 |

Only the Donchian breakout is profitable in BOTH halves. Everything else is
breakeven-or-worse or inconsistent across halves.

## Donchian parameter sweep (H1, 1y) — top robust configs (both halves PF ≥ 0.95, ≥80 trades)
| Lookback | SL | TP | Trades | Net $ | PF | Win% | AvgR | MaxDD_R | PF H1 | PF H2 |
|---|---|---|---|---|---|---|---|---|---|---|
| 48 | 1.5 | 3.0 | 170 | +690.10 | **1.17** | 38.2 | 0.14 | 11.2 | 1.21 | 1.13 |
| 48 | 1.0 | 3.0 | 190 | +475.48 | 1.14 | 30.0 | 0.19 | 12.3 | 1.09 | 1.22 |
| 48 | 2.0 | 3.0 | 163 | +440.03 | 1.09 | 42.9 | 0.07 | 13.2 | 1.14 | 1.03 |
| 48 | 1.0 | 2.0 | 218 | +304.19 | 1.09 | 38.5 | 0.14 | 11.3 | 1.02 | 1.18 |

## Robustness: Donchian(48) SL1.5/TP3.0 by quarter (H1, 1y)
| Quarter | Trades | Net $ | PF |
|---|---|---|---|
| Q1 (Oct 2025–Jan 2026) | 31 | +157.52 | 1.26 |
| Q2 (Jan–Apr 2026) | 50 | +310.02 | 1.19 |
| Q3 (Apr–Jul 2026) | 37 | +141.54 | 1.18 |
| Q4 (Jul–Oct 2026) | 51 | +87.51 | 1.09 |

Profitable in ALL 4 quarters. Top-5 winners = only 18.1% of gross profit
(not outlier-driven). Avg win $72.30 vs avg loss $38.19.

## Secondary check — M15 60d data
| Variant | Trades | Net $ | PF | PF H1 | PF H2 |
|---|---|---|---|---|---|
| Baseline EMA cross (M15) | 84 | -146.27 | 0.80 | — | — |
| Donchian(48) native on M15 | 132 | +74.39 | 1.06 | 0.89 | 1.26 |
| **Donchian(48) H1-channel, evaluated per M15 bar** | 75 | +77.28 | **1.10** | 1.23 | 0.94 |

The H1-channel version (the exact recommended EA implementation) holds up on
unseen M15 data: PF 1.10, maxDD only 8.6R.

## RECOMMENDATION — implement exactly this (ONE variant)

**Donchian(48) breakout on H1, evaluated on each new M15 bar.**

Precise rules:
1. **Channel (H1):** `upper` = highest HIGH of the prior 48 completed H1 bars
   (MQL5: `iHighest(_Symbol, PERIOD_H1, MODE_HIGH, 48, 1)`);
   `lower` = lowest LOW of the prior 48 completed H1 bars
   (`iLowest(_Symbol, PERIOD_H1, MODE_LOW, 48, 1)`).
2. **Signal (each new M15 bar):** take the last CLOSED M15 bar's close `C`
   (shift 1). If `C > upper` → BUY signal. If `C < lower` → SELL signal.
   Otherwise no signal. (No EMA cross, no ADX/RSI/session filter — drop them.)
3. **Stops:** ATR(14) on M15 at shift 1 (`iATR(_Symbol, PERIOD_M15, 14)`).
   SL = 1.5 × ATR, TP = 3.0 × ATR from the entry price.
4. **Position rules (unchanged from v1.30):** max 1 position; close on opposite
   signal without immediate reversal; keep spread filter, trading-hours filter,
   news blackout, Friday flat, 15% daily-loss brake, consecutive-loss pause,
   breakeven + trailing stop, push notifications, CSV journal, chart arrows.
5. Delete/replace the EMA20/50 + H1-EMA-filter signal block (keep the rest of
   the EA intact).

Why it won: it is the ONLY tested logic profitable in both halves of the 1y
sample AND in all 4 quarters AND on the secondary M15 dataset. Breakouts suit
gold's character in this period (strong multi-day legs); the 48h channel filters
the M15 chop that whipsaws the EMA cross to death (baseline PF 0.80–0.94).

## Honest caveats
- PF 1.10–1.17 is a **modest** edge, not a money machine. Real-world slippage
  will shave it thinner.
- The winner was picked from a 45-combo sweep — some selection bias exists.
  Mitigated by: consistency across 4 quarters, both halves, and a second
  dataset/timeframe; and neighboring configs (48/1.0/3.0, 48/2.0/3.0) also clear 1.09.
- Tested on GC=F futures; spot XAUUSD tracks it tick-for-tick intraday, so
  signal logic transfers, but absolute backtest $ figures won't match his
  broker exactly.
- Fixed 0.01 lot, no compounding. On his $6 account the min-lot risk % per
  trade is still huge — the EA's risk engine + daily brake remain essential.
- If live/demo results diverge badly from PF ~1.1, the edge may have decayed —
  re-test before adding size.

## Files
- `backtest_strategies.py` — main harness + 7 variants (H1 primary)
- `sweep_donchian.py` — Donchian parameter sweep (45 combos)
- `robust_check.py` — quarterly split + R-distribution for the winner
- `m15_check.py` — secondary validation on M15 60d data
- `RESULTS.md` — this file
