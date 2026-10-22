# BUY-restriction variants — backtest results (2026-10-23)

User-approved research (no live change). Question, from the 2026-10-23 live
journal review: pattern-only (dtb) journal splits SELL +3.57R / PF 1.17
(n=46) vs BUY -6.25R / PF 0.56 (n=25) — should BUY be restricted?

Script: `buy_variants_backtest.py` (imports the validated
`double_top_bottom_backtest.py` harness; metadata scan asserted to
reproduce `scan_patterns` entry_of exactly — 1,093 confirmed signals).
Data: PAXGUSDT M5, Binance Vision, 2026-01-01 → 2026-10-21, 59,976 bars,
forex-hours filtered (loader). Proxy for XAUUSD; no spread/slippage.
Re-downloaded 2026-10-23 (original /tmp copy was wiped by a VM replace);
originals kept in `research/data/paxg_m5/`.

Harness validation: original script re-run on this data reproduces the
recorded v2.4 result — sep>=3: n=486 PF 1.24 totR +63.0 maxDD 22.7
(recorded Oct 8: n=460 PF 1.25 +63.3R maxDD 22.7; n differs because the
window now ends Oct 21 instead of ~Oct 8). Harness trusted.

Engine caveat: research engine is one-position-at-a-time; live is
multi-position since v2.4. Numbers are RELATIVE comparisons between
variants on the same engine, not live predictions.

## Results — full-runner model (primary; matches live TP1→BE + runner mgmt)

| Variant | n | Win% | PF | TotR | MaxDD | Sep–Oct PF / TotR |
|---|---|---|---|---|---|---|
| BASE (no filter) | 486 | 36.2 | **1.24** | **+63.0** | 22.7 | 0.97 / -1.4 |
| SELL-ONLY | 349 | 38.7 | 1.21 | +43.4 | 22.5 | **1.24 / +8.7** |
| BUY+EMA-H1 | 417 | 36.7 | 1.21 | +50.0 | 27.2 | 0.95 / -2.2 |
| EMA-BOTH | 336 | 33.6 | 1.11 | +22.0 | 29.9 | 0.85 / -6.1 |
| BUY+GRADE-AB | 425 | 36.7 | 1.19 | +48.1 | 24.5 | 1.03 / +1.3 |
| GRADE-AB-BOTH | 338 | 33.1 | 1.07 | +14.5 | 21.8 | 0.86 / -4.9 |

BASE by direction: BUY n=230 PF 1.29 +33.0R (TP1-hit 49.1%) ·
SELL n=256 PF 1.19 +30.0R. In the 10-month sample BUY is the STRONGER
side — the live BUY bleed is an October-regime effect, not structural.

BASE by grade: A (n=52) PF 1.42 +11.5R · B (n=184) PF 1.16 +17.4R ·
C (n=250) PF 1.26 +34.1R. Grade does NOT separate losers; C-grade trades
carry the largest share of profit. Grade-as-filter is rejected by this
data (grade stays informational; live grade logging added 2026-10-23
will let this be re-checked on live-feed data).

## Sensitivity — TP1 model (close everything at TP1 = +1R)

BASE PF 0.78 / -58.9R; every variant also < 1.0 (best EMA-BOTH 0.72 …
SELL-ONLY 0.62). The backtest edge lives in the runner (TP3 +2R after
TP1→BE), not in TP1 itself. Closing the whole position at TP1 turns the
strategy negative in every variant. (At 0.01 min lot he cannot partial,
so the full-runner model is the realistic one if he follows TP1→BE.)

## Verdict

- **Do NOT restrict BUY.** Every BUY restriction tested lowers full-sample
  profit (BASE +63.0R beats SELL-ONLY +43.4R, BUY+EMA +50.0R,
  BUY+GRADE-AB +48.1R). The October BUY losses are regime (gold downtrend,
  double bottoms failing into it), already visible in Sep–Oct where BASE
  is ~breakeven (-1.4R).
- SELL-ONLY is the only variant that improves Sep–Oct (+8.7R), at a
  -19.6R full-sample cost — a regime bet, not an edge. Not recommended
  as a standing rule.
- The cascade problem (stacked/clustered losses, worst days) is not a
  direction problem; the untested proposal that targets it directly is
  the daily loss brake (-3R/day pause), still awaiting a decision.
- No live change made or recommended from this test.
