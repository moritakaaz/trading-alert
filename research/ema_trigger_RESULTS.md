# Testing TRIGGER = EMA20/50 Cross H1 (T1) vs Donchian Trigger v1.2 — Backtest Results (2026-10-07)

**User's question:** "when the EMA crosses it should give an entry alert (buy/sell)" — because on the 07 Oct 2026 chart the H1 cross (around $4160) preceded the Donchian SELL signal @$4082 by about ~$80. User approved "gas", tested fairly.
**Honest prior:** EMA-cross as a standalone trigger already LOST on all 6 symbols (early Oct 2026 research); F2 (fresh-cross as a filter) failed (PF 0.82). Expectation: likely to fail — but the test was still run fairly.

**Method:** harness `ema_trigger_backtest.py` (runner engine, live_pos gate, SL/TP1/48h-expiry resolution, intrabar SL priority — exactly `run_ema` in `ema_filter_backtest.py`). Binance PAXGUSDT M5 Jan–Oct 2026 data (XAUUSD proxy), re-downloaded from Binance Vision (monthly Jan–Sep + daily 01–06 Oct; the 07 Oct daily file was not yet published at test time).

**Precise T1 definition (no lookahead):**
- Cross detected on completed H1 bar `j`: `sign(EMA20−EMA50)` changes (exactly the F2 definition; requires `prev_sign != 0`, so the first cross from warmup is not counted).
- Entry = close of the FIRST M5 bar with `ts >= h1t[j]+3600` (the moment the cross is known).
- Cross up → BUY, cross down → SELL. One cross = one signal; a cross while a position is active = discarded (same as a Donchian signal while a position is active in v1.2).
- Risk management IDENTICAL to v1.2: SL 1.5×ATR(H1) (@cross bar), TP1 1R / TP2 1.5R / TP3 2R, TP1-touch → SL to breakeven, 48h expiry, one-position-at-a-time.
- Main variant T1+H4 (H4 SMA15 filter like v1.2, computed on cross bar `jc`); diagnostic variant T1 without H4 filter. The EMA-state filter is NOT used (redundant with the trigger).

**Validation:** the v1.2 baseline in this script (n=238, PF=1.38, totR=+42.2, maxDD=15.3) matches EXACTLY with `ema_filter_RESULTS.md` — numbers are comparable across variants.

## 1. Main results

| Variant | Jan–Oct n | win% | PF | avgR | totR | maxDD | Sep–Oct n | PF | totR |
|---|---|---|---|---|---|---|---|---|---|
| v1.2 baseline (Donchian trigger) | 238 | 33.6 | **1.38** | +0.18 | **+42.2** | 15.3 | 27 | 0.86 | -2.0 |
| **T1: EMA-cross trigger +H4** | 92 | 25.0 | **0.86** | -0.07 | **-6.4** | 12.1 | 17 | 0.93 | -0.6 |
| T1: EMA-cross trigger no-H4 | 92 | 21.7 | 0.68 | -0.17 | -15.4 | 19.7 | 17 | 0.60 | -3.6 |

- **T1 FAILS DECISIVELY.** PF 0.86 (< 1.0 = losing), totR −6.4R vs v1.2's +42.2R. Without the H4 filter it's worse (PF 0.68). Even in the latest Sep–Oct data it's not meaningfully better than v1.2 (0.93 vs 0.86, n=17 — noise in a small sample).
- Frequency: 99 H1 crosses in 9 months (98 events in the Jan–Oct period) → 92 trades taken (6 discarded by the one-position gate; the H4 filter didn't block a single one — an H1 cross is practically always aligned with H4). v1.2 gives 238 signals: T1 is ~60% rarer AND far worse.

## 2. Diagnostic: why it failed

| Metric (T1+H4, Jan–Oct) | Value |
|---|---|
| % of SLs hit within ≤12 H1 bars after entry (whipsaw) | **87%** |
| Average H1 bars entry → SL | 6.1 hours |
| Average H1 bars entry → TP1 touch | 10.1 hours |

- **Failure mechanism = whipsaw.** 87% of SLs are hit within the first 12 hours. An EMA cross is a lagging indicator: by the time it crosses, price has already moved far — and often immediately reverses.
- **Concrete example 02–03 Oct** (last 5 T1 trades in the data): SELL −1R → BUY −1R (3 hours later) → SELL −1R (2 hours later!) → BUY −1R → SELL +0.1R. **4 consecutive SLs in ~2 days** because the cross flip-flopped back and forth. This is what one pretty chart doesn't show.
- Irony worth noting: the 07 Oct chart that sparked this idea shows a "perfect" DOWN cross — but 9 months of data show such crosses are more often traps than blessings. One chart = anecdote; 99 crosses = data.

## 3. Honest conclusions & recommendation

**DO NOT switch the trigger to EMA cross.** The result isn't "neutral but interesting" — it's systematic loss (PF 0.86, −6.4R). This is the third confirmation after (a) standalone EMA-cross losing on 6 symbols and (b) F2 failing: **EMA cross cannot be used as an entry trigger.**

**Recommendation: stay on v1.2 (Donchian trigger + H4 filter + EMA-state H1 filter) as-is.** EMA20/50 stays in use — but as a FILTER (proven +0.15 PF), not as a TRIGGER. EMA's place in the system is correct: Donchian finds the breakout moment, EMA judges whether the breakout is aligned with the medium-term trend.

**Mandatory skepticism notes:**
- No spread/commission/slippage — live PF will be lower than all numbers above.
- Backtest feed (Binance) ≠ live feed (Twelve Data); 92 T1 trades = small-to-medium sample.
- The last cross in the data (BUY @ 07 Oct 01:00 WIB) is not in the results — the data ends at 06 Oct.

## File
- `~/workspace/trading-ea/research/ema_trigger_backtest.py` — T1 test script
- This report: `~/workspace/trading-ea/research/ema_trigger_RESULTS.md`
- Data: `/tmp/paxg_m5/` (ephemeral — re-download from Binance Vision if needed)
