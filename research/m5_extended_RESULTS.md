# M5 Entry Strategy — Extended Backtest (2026-10-05)

## Why this was run
User hit 3 consecutive live SLs and questioned the strategy (38% win rate).
Prior research (`m5_check2.py`) claimed PF 1.25 on only 52 trades (Jul–Oct 2026).
This extends to **9 months, 214 trades** and tests 4 proposed improvements.

## Data
| Item | Detail |
|---|---|
| Symbol | PAXGUSDT (Binance spot, XAUUSD proxy) |
| Interval | M5 |
| Range | 2026-01-01 → 2026-10-04 UTC |
| M5 bars | 56,256 (forex-hours filtered) |
| H1 bars | 4,688 (resampled) |
| Source | Binance Vision monthly/daily zips |

## Harness validation
`m5_check2.py` logic (M5-based ATR) re-run on 9 months: **PF 1.10, n=520**
(vs claimed 1.25 on 52 trades). The original claim was optimistic due to small
sample — but note the original code used M5 ATR, **not** H1 ATR as documented.
The live system uses H1 ATR, so the BASE below is the correct benchmark.

**Discrepancy found:** `m5_check.py` / `m5_check2.py` docstrings claim
"SL/TP from H1 ATR(14)" but the code computes ATR on M5 bars. The live alert
system correctly uses H1 ATR. All BASE/variant numbers below use H1 ATR.

## Method
- Signal: Donchian(48) on completed H1 bars, evaluated on each M5 close.
- Entry at M5 close. SL = mult × ATR(14) on H1. Max 1 position.
- **Full-runner model:** single TP at 2R (TP = 3.0×ATR when SL = 1.5×ATR).
  R = +2.0 (TP) or −1.0 (SL). SL priority on same-bar hits.
- **Breakeven model:** TP1 hit → SL moved to entry; runner to TP3 (2R).
  R = −1.0 (SL pre-TP1), 0.0 (TP1 then BE), +2.0 (TP3). This matches the live
  alert instruction "TP1 → SL ke breakeven".
- Costs: none modeled beyond the R-multiple (same as prior research;
  spread/slippage would shave all PFs thinner in live trading).

## Results — full-runner model (hold to 2R)

| Variant | Trades | Win% | PF | AvgR | TotalR | MaxDD_R | PF H1 | PF H2 |
|---|---|---|---|---|---|---|---|---|
| **BASE** (SL1.5/TP3.0) | 214 | 38.3 | **1.24** | +0.15 | +32.0 | 12.0 | 1.40 | 1.10 |
| A: H4 trend filter | 195 | 39.0 | 1.28 | +0.17 | +33.0 | 12.0 | 1.46 | 1.11 |
| B: session 07–21 UTC | 148 | 39.2 | 1.29 | +0.18 | +26.0 | 11.0 | 1.70 | **0.96** |
| C: wider SL 2.0× | 160 | 36.2 | 1.14 | +0.09 | +14.0 | 13.0 | 1.20 | 1.08 |
| D: H4 + session | 133 | 39.8 | 1.32 | +0.20 | +26.0 | 9.0 | 1.88 | **0.91** |

## Results — breakeven model (live management: TP1 → BE)

| Variant | Trades | Win%¹ | BE% | PF | AvgR | TotalR | MaxDD_R | PF H1 | PF H2 |
|---|---|---|---|---|---|---|---|---|---|
| **BE live** (TP1=1.0R) | 227 | 27.3 | 25.6 | **1.16** | +0.07 | +17.0 | 11.0 | 1.27 | 1.04 |
| BE TP1=0.75R (tighter) | 245 | 22.0 | 36.3 | 1.06 | +0.02 | +6.0 | 14.0 | 1.07 | 1.04 |
| BE + H4 filter | 206 | 27.7 | 26.2 | 1.20 | +0.09 | +19.0 | 11.0 | 1.39 | 1.00 |

¹ Win% = trades with R > 0 (excludes 0R breakevens).

## Quarterly robustness (BASE, full-runner)

| Quarter | Trades | PF | Total R |
|---|---|---|---|
| Q1 2026 | 77 | 1.67 | +28.0 |
| Q2 2026 | 67 | 1.19 | +8.0 |
| Q3 2026 | 69 | **0.94** | −3.0 |
| Q4 2026 | 1 | — | (insufficient data) |

## TP1 touch rate (BASE): 50.9%
About half of all trades reach 1R before exiting. The other half go straight
to SL. This is why the breakeven instruction matters — and why it costs PF
(1.24 → 1.16): moving to BE too early cuts winners that would have hit 2R.

## Headline findings

1. **The PF 1.25 claim VALIDATES on a large sample.** BASE (correct H1-ATR
   logic) gives PF **1.24** on 214 trades over 9 months, positive in both
   halves (1.40 / 1.10). The edge is real but **modest**.
2. **No variant is clearly better.** H4 filter helps marginally (+0.04 PF in
   both models, both halves positive) but is not a game-changer. Session
   filter and H4+session look good on headline PF but **fail the second-half
   test** (H2 < 1.0) — likely overfit. Wider SL and tighter TP1 are both
   worse than base. **Do not implement B, C, D, or tighter TP1.**
3. **The live breakeven instruction costs ~0.08 PF** (1.24 → 1.16). This is
   the price of the psychological comfort of "risk-free after TP1". Still
   positive both halves (1.27 / 1.04), but thinner.
4. **Q3 2026 was a losing quarter** (PF 0.94). The strategy goes through
   drawdowns lasting months. Three consecutive SLs — or even 5–6 — is
   statistically normal for a 38% win-rate system (maxDD was 12R ≈ 12
   consecutive full losses in the worst case).
5. **The strategy is viable but it is a grind**, not a money machine.
   Expected: ~38% win rate, PF ~1.16–1.24, frequent losing streaks, months
   that go nowhere (Q3). Anyone trading it needs the position sizing and
   circuit breaker to survive the psychology.

## Recommendation
- Keep the live signal logic **unchanged**. No variant justifies a change.
- Optionally add the H4 trend filter as a **hard filter** (not just a label):
  expected gain is small (+0.04 PF) but it is consistent across both models
  and both halves. **Needs user approval** — it reduces trade frequency
  (~10% fewer signals).
- Do NOT tighten TP1 to 0.75R — it demonstrably hurts (PF 1.16 → 1.06).
- The circuit breaker (2× consecutive SL warning) is well-justified by this
  data: losing streaks are the norm, not the exception.

## Honest caveats
- Backtest is on PAXGUSDT (Binance spot); live is XAUUSD via Twelve Data.
  Tracks within a few dollars intraday; signal logic transfers.
- No spread/commission/slippage modeled. Live PF will be lower than backtest.
- 214 trades is better than 52 but still a moderate sample. Q3 shows the
  edge can vanish for months.
- The H4-filter improvement (+0.04) may be noise. Do not oversell it.
- Never promise profit. This is "uang belajar" money — size accordingly.

## Files
- `/tmp/m5_extended.py` — full-runner model: base + 4 variants + sanity check
- `/tmp/m5_breakeven.py` — breakeven model: TP1=1.0R vs 0.75R, ±H4
- `/tmp/paxg_m5/` — 13 zips, Jan–Oct 2026 (ephemeral; re-download if needed)
- This file: `~/workspace/trading-ea/research/m5_extended_RESULTS.md`
