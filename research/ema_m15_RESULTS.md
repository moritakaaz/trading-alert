# Testing EMA 20/50 on M15 as a Filter — Backtest Results (2026-10-07)

**User's question:** multi-timeframe stack — M5 for scalping entries, M15 to read the trend, H1 for confirmation. "It'd be good to also put it on M5 and test it." (M5 was already tested in F3: useless.)
**What was tested:** the EMA20/50 STATE filter on M15 on top of the v1.2 baseline (= v1.1 + EMA20/50 state filter @H1, live since 2026-10-07).
**Method:** harness `ema_m15_backtest.py` (the `run_ema` pattern from `ema_filter_backtest.py`, based on the validated `fix6sl_backtest.py`). M15 resampled from M5 bars (same pattern as H1 formation). No lookahead: for a signal at an M5 bar (open ts), the last closed M15 bar is used: `k = bisect_left(m15t, ts - ts%900) - 1`. Binance PAXGUSDT M5 Jan–Oct 2026 data (XAUUSD proxy). Suppressed signals were run as phantom trades per causing filter.
**Constraint:** no live files were changed. Script: `ema_m15_backtest.py`.

---

## 1. Main results

| Variant | Jan–Oct n | win% | PF | avgR | totR | maxDD | Sep–Oct n | PF | totR |
|---|---|---|---|---|---|---|---|---|---|
| v1.2 baseline (H4 + EMA-H1) | 238 | 33.6 | **1.38** | +0.18 | **+42.2** | 15.3 | 27 | 0.86 | -2.0 |
| **G1: v1.2 + EMA-M15** | 235 | 33.6 | 1.39 | +0.18 | +42.2 | 15.3 | 27 | 0.86 | -2.0 |
| **G2': v1.1 + EMA-M15 (replace H1)** | 261 | 31.4 | 1.24 | +0.12 | +30.1 | 19.1 | 31 | 0.75 | -4.0 |

Suppressed signals (phantom, Jan–Oct):

| Variant | supH1 n | PF supH1 | supM15 n | PF supM15 |
|---|---|---|---|---|
| v1.2 baseline | 52 | 0.20 | — | — |
| G1 | 52 | 0.20 | **4** | 0.67 |
| G2' | — | — | **4** | 0.67 |

- **G1: adds nothing.** PF 1.38→1.39 (noise), totR identical +42.2, maxDD identical. The M15 filter discards only 3 additional signals out of 238 — practically inert.
- **G2': M15 alone ≈ no filter.** PF 1.24 ≈ v1.1 (1.23), totR +30.1 ≈ +29.1. The H1 filter is doing all the work; M15 cannot replace it.
- In the latest Sep–Oct data, G1 is exactly identical to v1.2 (M15 discards not a single signal).

Harness validation: the v1.2 baseline in this script (n=238, PF=1.38, totR=+42.2, maxDD=15.3) **matches exactly** with `ema_filter_RESULTS.md` — numbers are comparable across variants.

## 2. Redundancy diagnostic (post-H4 candidate signals, Jan–Oct, n=290)

| | H1 passes | M15 discards among them | M15 passes | H1 discards among them | Both discard |
|---|---|---|---|---|---|
| v1.2 / G1 | 238 | **3 (1.3%)** | 286 | 51 (17.8%) | 1 |

Total asymmetry: M15 almost never blocks signals that pass H1 (1.3%), while H1 blocks 17.8% of those that pass M15. **M15 is not a two-way-redundant filter — it is a filter that almost never activates.** Of 290 candidate signals, M15 discards only 4.

## 3. Why M15 is useless (mechanical explanation)

When a Donchian breakout happens on the M5 close **and** the H1 trend (20–50 hours) is already aligned, the M15 trend (5–12.5 hours) is mechanically almost always aligned too — a fast MA cannot lag far behind at the exact moment of a strong breakout aligned with the medium trend. The M15 filter would only activate during micro-whipsaw moments where M15 briefly reverses — and the data shows those moments almost never coincide with a signal (4 out of 290). This is the same pattern as F3 (EMA @M5): **the faster the EMA's timeframe, the more it "always agrees" with the breakout on the trigger timeframe** — so as a filter it filters out nothing.

The full M5→M15→H1 stack has now all been tested: M5 useless (F3, 1/265 filtered), M15 useless (G1, 4/290), H1 is what works (F1, PF 1.23→1.38).

## 4. Honest conclusions & recommendation

**Do not add the EMA-M15 filter.** The result is neutral (not negative, not positive) — adding it only adds complexity without edge. Recommendation: stay on v1.2 (H4 + EMA-H1) as-is.

**Mandatory skepticism notes:**
- The user was confident "it'll be right again" after F1 won — but this is exactly where backtest discipline matters: even ideas that feel right must be tested, and this time the answer was "no".
- PF 1.39 vs 1.38 on G1 is noise (3 trades different out of 238), not an improvement.
- No spread/commission/slippage; backtest feed (Binance) ≠ live feed (Twelve Data); 265 trades = medium sample.

## File
- `~/workspace/trading-ea/research/ema_m15_backtest.py` — G1/G2' test script
- This report: `~/workspace/trading-ea/research/ema_m15_RESULTS.md`
- Data: `/tmp/paxg_m5/` (ephemeral — re-download from Binance Vision if needed)
