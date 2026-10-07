# Testing EMA 20/50 as a Filter — Backtest Results (2026-10-07)

**User's question:** "should we add an indicator when EMA 20 and 50 cross?" (after seeing a chart with an "interesting" cross).
**What was tested:** EMA20/50 as an ADDITIONAL directional filter on the live v1.1 strategy — NOT a standalone strategy (that was already tested in Oct 2026 and lost on all symbols).
**Method:** harness `fix6sl_backtest.py` (validated: replica n=529/PF=1.09 ≈ reference 520/1.10). Binance PAXGUSDT M5 Jan–Oct 2026 data (XAUUSD proxy). All variants tested on the SAME data. Suppressed signals were run as "phantom trades" to measure their PF.
**Constraint:** no live files were changed. Script: `ema_filter_backtest.py`.

---

## 1. Main results

| Variant | Jan–Oct n | win% | PF | avgR | totR | maxDD | Sep–Oct n | PF | totR | Suppress n | PF suppress |
|---|---|---|---|---|---|---|---|---|---|---|---|
| v1.1 baseline | 265 | 31.3 | **1.23** | +0.11 | +29.1 | 19.1 | 31 | 0.75 | -4.0 | 0 | — |
| **F1: EMA20/50 state @H1** | 238 | 33.6 | **1.38** | +0.18 | **+42.2** | **15.3** | 27 | **0.86** | **-2.0** | 52 | **0.20** |
| F2: EMA fresh-cross @H1 | 100 | 24.0 | 0.82 | -0.10 | -10.0 | 12.0 | 14 | 0.40 | -6.0 | 378 | 1.37 |
| F3: EMA20/50 state @M5 | 265 | 31.3 | 1.23 | +0.11 | +29.1 | 19.1 | 31 | 0.75 | -4.0 | 1 | — |

- **F1 WINS CLEARLY.** PF 1.23→1.38, total R +29.1→+42.2, maxDD 19.1→15.3. The discarded signals were genuinely bad (PF 0.20) — the filter throws away the rotten ones, not the good ones. Consistent in the latest Sep–Oct data too (0.75→0.86, loss -4.0R→-2.0R). Cost: ~10% fewer signals.
- **F2 REJECTED DECISIVELY.** A "fresh" cross instead discards the good trades (suppress PF 1.37!) and keeps the bad ones (PF 0.82). Classic over-constraint.
- **F3 USELESS.** M5 EMA is almost always aligned with the M5 breakout — only 1 signal filtered. Too fast a timeframe to act as a filter.

## 2. F1 robustness (is it just a 20/50 fluke?)

| EMA pair | Jan–Oct PF | totR | Suppress n | PF suppress | Sep–Oct PF |
|---|---|---|---|---|---|
| 10/30 | 1.27 | +33.1 | 12 | 0.28 | 0.80 |
| 12/26 | 1.27 | +33.1 | 12 | 0.28 | 0.80 |
| **20/50 (user's suggestion)** | **1.38** | **+42.2** | 52 | 0.20 | **0.86** |
| 20/100 | 1.49 | +48.7 | 98 | 0.45 | 0.91 |
| 50/200 | 1.61 | +47.3 | 194 | 0.86 | 1.00 |

The direction of improvement is CONSISTENT across all pairs — the mechanism (breakouts aligned with the medium-term trend = higher quality) is generally valid, not an artifact of one number. Honest note: slower pairs give higher PF BUT kill a larger share of trades (50/200 discards 40% of signals). 20/50 was the user's a-priori choice, not an optimization result — so no cherry-picking. Don't be tempted to switch to 50/200 just because it has the best backtest numbers.

F1(20/50) by month vs baseline: improved/same in 8 of 10 months (Feb 1.30, Mar 1.61, Apr 1.56, May 1.40, Jun 1.59, Aug 1.03, Sep 1.00; Jan 2.73 vs 2.91 slightly down; Jul 0.61 vs 0.48 still red but better; Oct n=2 too small).

## 3. Diagnostic: yesterday's 6 live losses vs F1

| Live signal | EMA20/50 H1 at signal time | F1 |
|---|---|---|
| BUY @4162.15, 4168.28, 4165.04 (05 Oct) | -9.00 / -8.19 (bearish) | SUPPRESSED ×3 |
| SELL @4126 (05 Oct), @4125 (06 Oct) | -8.18 / -8.72 (bearish) | PASSES (still a loss) |
| BUY @4177 (06 Oct) | -8.72 (bearish) | SUPPRESSED |

4 of the 6 losses would have been suppressed — the -6R streak becomes -2R. Breakouts against the medium-term trend are indeed the main source of whipsaw.

## 4. Honest conclusions & recommendation

**F1 (EMA20/50 state filter on H1) adds real, consistent edge.** It is a medium-term trend filter that complements (not duplicates) the existing H4 filter: H4 = large trend, EMA20/50 = medium trend. The mechanism makes sense; results are consistent across periods and parameters.

**Mandatory skepticism notes:**
- This idea was born from 1 pretty chart — but it was validated on 9 months of data + a robustness bracket, not 6 trades. That is what separates it from overfitting.
- No spread/commission/slippage — live PF will be lower than all numbers above.
- Backtest feed (Binance) ≠ live feed (Twelve Data); 265 trades = medium sample.
- F1 did not save the 2 losing SELLs — the filter reduces whipsaw, it doesn't eliminate it.

**Recommendation: DEPLOY F1** — with the user's explicit approval (this is a signal-logic change). Lightweight implementation: 1 additional condition in the signal filter function (`diff = ema20-ema50 > 0` for BUY). Estimated cost: ~10% fewer signals. Do not deploy F2 or F3.
