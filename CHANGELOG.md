# Changelog — trading-alert

All notable changes, newest first. Strategy parameters (ATR 14, N=2,
5–50 bars, Donchian 48, SL 1.5×ATR, TP 1R/1.5R/2R) are never changed
without the owner's explicit approval.

## Unreleased (P3)

- B54: `scripts/signals.py` — pure signal functions (`detect_dtb`,
  `detect_setup`, `score_pattern`, `rsi_series`) extracted from the
  engine heredoc; importable and pytest-covered (`tests/test_signals.py`,
  8 regression tests incl. cases A/B/C + BUY mirrors).
- B56: watchdog skips the command-handler staleness check when the
  tg-cmd log file does not exist yet (fresh install).
- B57: `prune_logs()` in watchdog — jsonl logs rotated to last 14 days
  on every run (idempotent); `log_maintenance.py` default tightened
  30 → 14 days.
- B58: verified `signals.py` has zero I/O (AST check: no `open`,
  `subprocess`, `urllib`, `os.*` in signal functions).
- B59: `.gitignore` narrowed — `*.csv`/`*.png` no longer ignored
  repo-wide, only under `state/` and `charts/`.
- B60: this changelog created; inline history comments kept concise.

## P2 (2026-10-08)

B08, B15, B18, B23–B25, B28, B34, B35, B38–B47, B49–B52 — labels,
consistency, data quality: chart/trend "now" labels, dead code removal,
chart bar window, archive of unused `xauusd_entry_m5.sh`, chart dir via
config, setup PNG pruning, per-TF status counts, shared forex-hours
module, watchdog state file, HTTPError handling, HELP sync, unified
`/chart` handler, README command list, crontab docs, requirements,
shared state helper, log-read performance, scoreboard date-range fetch,
Donchian docs, news formatting, news age param, calendar window param.

## P1 (2026-10-08)

B04, B06, B07, B12–B14, B16, B17, B19, B26, B29, B30, B33, B36, B37, B48 —
entry/SL/TP price basis docs, 2-decimal neckline display, single
`STRATEGY_VERSION`, `/trend` filter text removed, expired counted in
scoreboard, `/close_trade be` = +1R, history shows stored `r_multiple`,
newest-first pattern iteration, setup chart TF + signal time, HTML
escaping in `send_tg.py`, offset advance after success + retry counter,
token via config file, M5 poll 60s with bar-finality wait, watchdog log
format alignment, calendar UTC dates, news regex narrowed, Kraken
fallback no longer sends ENTRY.

## P0 (2026-10-08)

- B01: `tg_send` sends full text via `sendMessage` first (checked
  `"ok":true`); photo sent separately with short caption. Alerts no
  longer lost when `sendPhoto` fails (caption 1024-char limit).
- B02: SETUP WATCH text rewritten — entry confirmed ONLY on
  close + correct candle color; stop orders can fill on wick touch.
  Added "NECKLINE TERSENTUH (belum close)" intrabar notification,
  once per pattern.
- B03: `detect_setup` distance check is now two-sided
  (SELL: `0 <= sc - neck <= 0.5*ATR`), fixing case B where price
  already broke the neckline but a green candle still sent SETUP WATCH.
- B05: neckline displayed with 2 decimals (`$4121.50`, not `$4122`).
- B09: alert inline buttons carry TF (`pause_1h:m1`, `alert_off:m15`);
  handlers update the correct TF state; pause no longer re-enables OFF TFs.
- B10: `/skip|close|cancel|reset_trade` clear `active_trade` in the
  correct TF's state (from the journal row's timeframe).
- B11: self-heal filters journal rows by timeframe.
- B31: `last_bar`/`pattern_p2_t` dedupe markers saved only after a
  successful `tg_send`; failed sends are retried next poll.

## v2.5 (2026-10-08)

- Fixed R1 regression: `last_run` (liveness, every poll) separated from
  `last_heartbeat` (5-min Telegram gate); SL/TP + runner monitoring runs
  on EVERY poll.
- Telegram poller: per-update try/except, offset advances per update.
- Journal lifecycle commands fall back to newest open row on desync.
- Scoreboard: TP1+BE = +1R (full-position model), closed bars only.
- SL/TP monitoring continues when alerts are off (owner decision).
- `/history` pagination (10/page, Next/Prev buttons).
- `/export_journal` — CSV export by day/week/month/year.
- SETUP WATCH: single message (photo+caption), Entry/SL/TP levels,
  BUY STOP/SELL STOP guidance, 2-decimal neckline.
- `/alert_on|off` renamed `/alert_on_m5|/alert_off_m5` (backward compat).
- Fixed `/alert_on_m5` dead code; `/alert_status` (concise) vs `/check`
  (detailed) differentiated.
- Poller: offset advanced BEFORE processing (fixes `continue` skipping it).

## v2.4 (2026-10-08)

- Multi-position: one-position suppression removed; new signals fire
  even with open trades (owner request).
- Quality score 0–100 (Grade A/B/C): peak match 25 + RSI div 20 +
  height 15 + symmetry 10 + prior trend 15 (adapted from Neblok).
- Clean check: no higher-high / lower-low between p1 and p2.
- Heartbeat edits previous Telegram message in place (owner idea).
- Dark TradingView-style charts, M/W pattern lines + dots, y-axis from
  2nd/98th percentiles.

## v2.3 (2026-10-08)

- p1 = first-valid peak/valley forming a valid pattern (fixed
  greedy-nearest bug the owner spotted).

## v2.2 (2026-10-08)

- SETUP WATCH: early "standby" alert when pattern geometry is complete
  but not confirmed (owner request).

## v2.1 "BRUTAL" (2026-10-08)

- Trend filter REMOVED; Donchian(48) H1 restored as second trigger
  (pattern takes priority on same bar). Touch entry tried and REVERTED
  same day (owner's catch: wick that closes back = level held).
- Multi-timeframe: M1/M5/M15 wrappers via `xauusd_entry_tf.sh`.

## v1.3 (2026-10-07)

- Runner tracking: post-TP1 monitoring for TP2/TP3/breakeven
  (owner spotted the gap). System release number only; strategy v1.2.

## v1.2 (2026-10-07)

- EMA20/50 H1 directional filter (owner's idea from TradingView).
  Backtest PF 1.23 → 1.38. Live as strategy v1.2.

## v1.1 / v1.0 (2026-10-05)

- H4 trend filter (v1.1), Donchian(48) H1 breakout on M5 (v1.0).
- Journal, scoreboard, watchdog, inline keyboards, circuit breaker,
  manual trade lifecycle, Telegram retry, fallback transparency.
