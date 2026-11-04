# XAUUSD Telegram Alert

Manual-alert system for XAUUSD (gold). Watches the M5 chart, sends entry
signals to Telegram, journals every signal, and scores the results.

Not financial advice. Experimental — the account behind this is a small
cent account ("learning money").

## What it does

- Detects double top / double bottom patterns on M5, confirms on candle close
- Sends entry alerts to Telegram with SL/TP levels and a chart
- Tracks open signals until TP or SL, journals everything to CSV
- Daily scoreboard and a weekly review, both from the journal
- Optional MT5 executor (demo phase) — see `executor/`

M1 and M15 wrappers exist but are unvalidated and normally off.
M5 is the only live timeframe.

## Strategy (v2.7, live since 2026-10-19)

- Trigger: double top/bottom only. Fractal peaks/valleys (N=2), peaks
  within 0.25×ATR(H1), 5–50 bars apart, no higher-high/lower-low between
  peaks. A close beyond the neckline with the right candle color confirms.
- The Donchian(48) breakout trigger is disabled since v2.6 — it lost
  money live (−12.67R). Breakouts are still logged, not traded.
- No trend filter.
- SL = 1.5×ATR(14) on H1 (weekend bars filtered out first).
  TP1 = 1R (then SL to breakeven), TP2 = 1.5R, TP3 = 2R.
- Each pattern gets a quality grade (A/B/C). Shown in alerts and logged
  to the journal. Never used as a filter.
- 2h cooldown after an entry in the same direction.
- Multiple positions can be open at once; all are monitored every poll.

## Results

Live journal, snapshot 2026-11-04 (TP1 + breakeven scoring):

- v2.7: 59 closed, 57.6% win rate, **+10.94R**, PF 1.47, max drawdown 6R
- All-time: 141 closed, **−9.41R** — the loss comes from the old Donchian
  era (28 signals, −16.67R). Pattern-only eras: v2.5 +1.00R, v2.6 −4.68R,
  v2.7 +10.94R.

At a fixed 0.01 lot on a Rp100,000 deposit, v2.7 would be +Rp44,457 so
far. That is journal math, not broker PnL, and excludes spread/slippage.

Backtest of the pattern strategy (Jan–Oct 2026, 538 trades, PAXGUSDT M5):
PF 1.13, win rate 34.2%, max drawdown 26.7R. Details in `research/`.

Small samples everywhere. Nothing here is proven.

## Commands

- Alerts: `/alert_on_m5` `/alert_off_m5` `/alert_status` (same pattern for M1/M15)
- Status: `/check` `/chart` `/trend` `/history` `/export_journal`
- Trades: `/skip_trade` `/close_trade` `/cancel_trade` `/reset_trade`
- Account: `/set_balance` `/set_risk` `/set_lot` `/lot_calc`
- Executor: `/auto_on` `/auto_off` `/auto_status` (off by default)

## Layout

- `scripts/` — engine, command handler, charts, scoreboard, watchdog
- `data/` — price feed (Twelve Data, Kraken fallback), news, calendar
- `executor/` — MT5 executor and Windows bridge
- `research/` — backtests and results, failures included
- `tests/` — signal regression tests (8)

## Setup

Needs a Telegram bot token, a Twelve Data API key, and cron (or similar)
to run the pollers. Finnhub (news) and FRED (calendar) keys are optional.
Copy `.env.example` to `.env` and fill it in. Script paths default to
`~/hooks/` — adjust to your setup.

## Open issues

From the Oct 2026 code review, still open: B20, B21, B22, B32, B44, a
legacy M5 engine audit, and full command regression tests.

## License

MIT. The risk is yours.
