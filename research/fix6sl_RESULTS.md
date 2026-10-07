# Investigating 6 Consecutive XAUUSD SLs — Research Results (2026-10-06)

**User's question:** "fix the signals" after 6 consecutive SLs (-6R, ~-112 USC ≈ 19% of capital).
**Method:** reconstructing the context of the 6 trades + re-backtesting v1.1 on the latest data + testing 3 fix candidates.
**Constraint:** no live files were changed. All numbers from the PAXGUSDT backtest (Binance spot, XAUUSD proxy).

---

## 1. The 6-loss pattern (journal 2026-10-05 to 2026-10-06)

| # | Signal | Time (WIB) | Session | H4 | Outcome |
|---|---|---|---|---|---|
| 1 | BUY @4162.15 | 05 Oct 14:50 | London | (v1.0, no filter) | SL -1R |
| 2 | BUY @4168.28 | 05 Oct 15:10 | London | (v1.0) | SL -1R |
| 3 | BUY @4165.04 | 05 Oct 15:45 | London | (v1.0) | SL -1R |
| 4 | SELL @4126 | 06 Oct 00:10 | New York | BEARISH ✓ | SL -1R |
| 5 | SELL @4125 | 06 Oct 09:35 | Asia | BEARISH ✓ | SL -1R |
| 6 | BUY @4177 | 06 Oct 19:00 | London | BULLISH ✓ | SL -1R |

**Pattern findings:**
- **All six never touched TP1** (max MFE 0.89R, two of them 0.00R — immediately reversed). This is a "clean" loss mode: fake breakouts, not near-profits.
- **3 of the 6 were stacked v1.0 signals** (trades 1–3, 20–35 minutes apart). The one-position-at-a-time rule in v1.1 (already live) would suppress trades 2 and 3. Under the current live logic, the streak is only 4 SLs (-4R), not 6.
- **No session pattern** (London 4×, NY 1×, Asia 1×). The H4 filter worked as designed (all signals trend-aligned) but didn't save them — trend-aligned breakouts can whipsaw too.
- **No FRED economic releases** (NFP/CPI/PPI/GDP) within ±1 day of all six signals. FOMC is indeed not covered by the calendar (a known structural blind spot).
- **Feed caveat:** the Binance PAXGUSDT data contains a $4230 wick on 2 Oct that (judging by live signals that still fired) is absent from the Twelve Data XAU/USD feed. As a result, the Donchian boundary in the backtest ≠ the live boundary for borderline signals — reconstructing per-trade live signal conditions in Binance data is not 100% accurate. The backtest remains valid as a *strategy* test, but not as a 1:1 replica of live signals.

**Is a 6-SL streak anomalous?** No. In the v1.1 Jan–Oct backtest (265 trades), the longest SL streak = **exactly 6**, and streaks of ≥6 SLs occurred **3× in 9 months**. What the user experienced = the known worst-case scenario, not a broken strategy.

---

## 2. Re-backtesting v1.1 on the latest data (Sep–Oct 2026)

Faithful replica of the live logic (Donchian(48) H1, M5 trigger, SL 1.5×ATR H1, transition-only, H4 filter, one-position). Harness validated: the `m5_check2.py` replica yields n=529/PF=1.09 vs the research reference n=520/PF=1.10 (match).

| Period | n | Win% | PF | avgR | Total R | MaxDD |
|---|---|---|---|---|---|---|
| v1.1 Jan–Oct 2026 | 265 | 31.3 | **1.23** | +0.11 | +29.1 | 19.1 |
| v1.1 **Sep–Oct 2026** | 31 | 19.4 | **0.75** | -0.13 | -4.0 | 11.0 |

**The edge weakened in the latest data** (PF 0.75, n=31). But this is consistent with earlier research findings (Q3 2026 PF 0.94 — red quarters do happen). The Sep–Oct sample is small (31 trades); not enough evidence to declare the edge permanently gone.

By month (v1.1): Jan PF 2.91 → Feb 1.17 → Mar 1.39 → Apr 1.08 → May 1.00 → Jun 1.68 → **Jul 0.48** → Aug 1.08 → **Sep 0.86** → Oct 0.00 (n=3). Trend-following system: harvests when trending (Jan, Jun), bleeds when choppy (Jul, Sep).

---

## 3. Testing fix candidates (max 3)

All tested on the SAME data (Sep–Oct and Jan–Oct). Previously rejected ideas (session filter, 2.0× SL, 0.75R TP1) were not re-tested.

### C1: Minimum breakout depth requirement (depth ≥ 0.3×ATR) — ❌ REJECTED DECISIVELY
Initial reasoning: the six losses looked like "thin" breakouts. Results:

| Period | Baseline v1.1 | C1 |
|---|---|---|
| Sep–Oct | PF 0.75 (n=31) | PF **0.50** (n=14) |
| Jan–Oct | PF 1.23 (n=265) | PF **0.93** (n=117) |

Additional diagnostics: trades with depth < 0.3 ATR actually had **PF 1.49** (n=171), while depth ≥ 0.3 ATR had **PF 0.83** (n=94). Median depth of WIN trades (0.14 ATR) < LOSS trades (0.21 ATR). **This strategy's edge is precisely in the thin, early breakouts** — waiting for deeper confirmation means entering late. This is a textbook example of why filters must never be designed from 6 trades.

### C2: 12-hour cooldown after SL — ⚠️ INTERESTING, but thin
Reasoning: losses cluster when the market is choppy; a pause after an SL avoids follow-on whipsaw.

| Period | Baseline v1.1 | C2 (12h) |
|---|---|---|
| Sep–Oct | PF 0.75, totR -4.0 (n=31) | PF **0.86**, totR -2.0 (n=27) |
| Jan–Oct | PF 1.23, totR +29.1 (n=265) | PF **1.31**, totR +30.6 (n=213) |

Parameter robustness (chosen arbitrarily before testing, then bracketed): 6h → PF 1.24/0.80; 24h → PF 1.37/1.00. The direction of improvement is consistent across all parameters and both periods — not a cherry-picked single number. Price: trade frequency down ~20%.

### C3: Skip during volatility explosions (ATR > 2× 20-median) — ❌ USELESS
Almost no signals were filtered (n=264 vs 265). The condition practically never occurs in 9 months of data. Rejected.

---

## 4. Proposals (max 2, honest numbers)

### Proposal A: Add 12-hour post-SL cooldown (needs discussion + approval)
- Backtest expectation: PF 1.23 → ~1.31 (Jan–Oct), Sep–Oct drawdown -4.0R → -2.0R. A **small** improvement (+0.08 PF), not a miracle cure.
- Mechanism makes sense (avoid post-loss chop), consistent at 6h/12h/24h — but it could still be noise. Not a profit promise.
- Cost: ~20% fewer signals. Doesn't change the signal definition, only the pause between trades after a loss — a risk-management overlay, not fiddling with entry logic.
- **Not yet implemented.** Awaiting the user's explicit approval per the rules.

### Proposal B: Change nothing (a valid option)
- 6 SLs = the worst streak *expected* ~3×/year per the 9-month backtest. The system is behaving per its distribution.
- 2 of the 6 losses came from v1.0 stacking, already fixed by one-position-at-a-time in v1.1.
- The Sep–Oct weakness (PF 0.75) is consistent with the known red Q3; n=31 is too small to declare "edge gone".
- Let the learning loop (Sunday review) judge with more data.

---

## 5. Overfitting warnings & caveats
- **6 trades = anecdotal sample.** C1 is the proof: a pattern that looked "obvious" in 6 trades reversed in 265 trades. Never tune from a streak.
- The C2 gain (+0.08 PF) is thin and could be noise; don't oversell.
- Backtest feed (Binance PAXGUSDT) ≠ live feed (Twelve Data XAU/USD); boundary-touching signals may differ.
- No spread/commission/slippage — live PF will be lower than all numbers above.
- 265 trades is still a medium sample; the edge can vanish for months (proven by Jul & Sep).

## File
- `~/workspace/trading-ea/research/fix6sl.py` — reconstructing the context of the 6 trades (Part A)
- `~/workspace/trading-ea/research/fix6sl_backtest.py` — v1.1 backtest harness (validated vs m5_check2: n=529/PF=1.09 ≈ reference 520/1.10)
- `~/workspace/trading-ea/research/fix6sl_candidates.py` — C1/C2/C3 testing + diagnostics
- This report: `~/workspace/trading-ea/research/fix6sl_RESULTS.md`
- Data: `/tmp/paxg_m5/` (ephemeral — re-download from Binance Vision if needed)
