# Changelog

Newest first. Strategy parameters never change without the owner's
explicit approval.

## 2026-11-04 — docs

- README and this changelog shortened and re-synced. README gains a
  dated live journal snapshot (v2.7: 59 closed, 57.6% win rate,
  +10.94R, PF 1.47) and the executor commands; the review-status text
  now lists what is still open (B20, B21, B22, B32, B44). No code change.

## 2026-11-01 — MT5 executor (owner-approved, off by default)

- `executor/`: dumb MT5 EA plus a Windows bridge. The bot publishes
  confirmed M5 entries (distances only, never the reference price) to a
  push channel only when the `auto_trade` flag is on.
  Commands: `/auto_on` `/auto_off` `/auto_status`.
- EA safety: SL/TP recomputed from the actual fill, fixed 0.01 lot,
  max 3 positions, max spread 0.60, full TP at TP1 distance, signal ids
  deduped at the bridge and again in the EA, failed orders recorded and
  never retried.
- Demo phase. Live use is a separate decision and needs a private
  transport first.

## 2026-10-23 — journal grade column

- The journal now stores each signal's grade (e.g. `B72`). Older rows
  stay empty — past grades were never recorded and are not reconstructed.
- Offline backtest (`research/buy_variants_*`): restricting BUY does not
  help; the base beats every variant (PF 1.24). October's BUY losses are
  a regime effect. No live change.

## v2.7 (2026-10-19)

- Weekend-bar filter: Twelve Data emits synthetic flat H1 bars while the
  market is closed; they collapsed ATR(14) to $2.10 and produced a $3
  stop. Weekend bars are now excluded before ATR/EMA/Donchian, and the
  H1 fetch went 80 → 200 bars.
- 2h same-direction entry cooldown. On 19 Oct, 7 stacked signals all hit
  SL (−7R); a journal simulation of the cooldown kept most of that loss
  out. Blocked patterns are consumed so they cannot fire late.
- Follow-up: the cooldown falls back to the journal when the state file
  has no last-entry time.

## v2.6 (2026-10-16)

- Donchian(48) entry trigger disabled (`DONCHIAN_TRIGGER_ENABLED =
  False`). Live journal: Donchian entries −12.67R (5 TP / 18 SL), still
  −5R after dedupe simulation; patterns were the only non-losing trigger.
  Breakouts still logged as `donchian-disabled`.

## Code review fixes (Oct 2026)

57 findings, P0–P3. Most are done:

- P0 (B01–B03, B05, B09–B11, B31): alert delivery, Setup Watch accuracy,
  per-TF state handling, dedupe markers saved only after a successful send.
- P1 (B04, B06, B07, B12–B14, B16, B17, B19, B26, B29, B30, B33, B36,
  B37, B48): price basis, version consistency, scoreboard accuracy,
  retries, token handling.
- P2 (B08, B15, B18, B23–B25, B28, B34, B35, B38–B47, B49–B52):
  cleanup, shared modules, docs.
- P3 (B54–B60): pure signal module (`signals.py`) with 8 regression
  tests, watchdog log pruning (14 days), this changelog.
- Still open: B20, B21, B22, B32, B44, legacy M5 engine audit, full
  command regression tests.

## v2.5 (2026-10-08)

- SL/TP and runner monitoring on every poll; liveness separated from
  the heartbeat gate.
- Scoreboard: TP1 + breakeven = +1R, closed bars only.
- Monitoring continues while alerts are off.
- `/history` pagination, `/export_journal`, Setup Watch as one message.

## v2.4 (2026-10-08)

- Multi-position: one-position suppression removed.
- Pattern quality score (Grade A/B/C) and the clean check between peaks.
- Heartbeat edits one Telegram message in place.
- Dark TradingView-style charts with pattern lines.

## v2.3 / v2.2 (2026-10-08)

- p1 = first valid peak/valley (fixes the greedy-nearest bug).
- Setup Watch: standby alert when a pattern is complete but unconfirmed.

## v2.1 (2026-10-08)

- Trend filter removed; Donchian restored as second trigger.
- Touch entry tried and reverted the same day (a wick that closes back
  means the level held).
- Multi-timeframe wrappers (M1/M5/M15) on one engine.

## v1.3 / v1.2 (2026-10-07)

- Runner tracking after TP1 (TP2/TP3/breakeven alerts).
- EMA20/50 H1 filter (backtest PF 1.23 → 1.38; removed later in v2.1).

## v1.1 / v1.0 (2026-10-05)

- H4 trend filter (v1.1); Donchian(48) H1 breakout on M5 (v1.0).
- Journal, scoreboard, watchdog, inline buttons, circuit-breaker
  warning (never auto-pauses), manual trade commands.
