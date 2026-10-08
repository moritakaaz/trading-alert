# XAUUSD Telegram Manual-Alert System

> ⚠️ **Not financial advice.** An experimental project — the funds used are
> "learning money" (a small cent account). Do not use for live trading
> without understanding the risks.

An **XAUUSD** multi-timeframe entry-alert system that pushes signals to Telegram:
pattern breakouts + Donchian breakouts, automatic journaling, entry charts,
position monitoring (TP1/TP2/TP3 + breakeven), and weekly performance reviews.

Three independent alert systems: **M1** (1-min poll), **M5** (5-min poll),
**M15** (5-min poll). Each has its own on/off switch and journal.

## Strategy (v2.4, live)

> Experimental — no trend filter, dual trigger, high frequency, quality-scored.

| Component | Detail |
|---|---|
| Trigger 1 (priority) | Double top/bottom on signal TF: M5 fractal peaks/valleys (N=2), \|p1-p2\| ≤ 0.25×ATR(H1), 5–50 bars apart, intervening extreme ≥3 bars from each side, no higher-high/lower-low between peaks (clean check), confirmation = close beyond neckline with right color. p1 = nearest peak forming a valid pattern |
| Trigger 2 | Donchian(48) breakout on completed H1 bars, evaluated on signal-TF close (no EMA filter) |
| Quality score | Every pattern scored 0-100 (Grade A/B/C): peak match 25 + RSI divergence 20 + height 15 + symmetry 10 + prior trend 15. Shown in alerts, informational only |
| Stop loss | 1.5 × ATR(14) H1 |
| Take profit | TP1 1R → SL to breakeven, TP2 1.5R, TP3 2R (runner) |
| Trend filter | **REMOVED** — all signals fire, both directions |
| Management | One position at a time per timeframe; no signal stacking |

**Honest backtest results** (double top/bottom v2.3, first-valid p1, 9 months
Jan–Oct 2026, 538 trades, PAXGUSDT M5 data):

| Metric | Value |
|---|---|
| Profit Factor | **1.13** |
| Win rate | 34.2% |
| Average / trade | +0.08R |
| Total | +40.4R |
| Max drawdown | 26.7R |
| Frequency | 1.92 trades/day |

Honest notes: the no-filter + dual-trigger combo was NOT backtested — only the
close-confirmed pattern version above (touch entry was tried and reverted:
a wick that closes back means the level held). Sep–Oct 2026 was weak
(PF 0.79, −8.9R). v2.4's clean check is not yet backtested. Q3 2026 was a
losing quarter. Excludes spread/commission/slippage — live results **will be
worse**. These numbers are not a promise. The journal judges.

Superseded: v1.2 (Donchian + H4 + EMA-H1 filter, PF 1.38), v2.0
(double top/bottom with M15+H1 EMA agreement filter, PF 1.22),
v2.1 (greedy-nearest p1, PF 1.18, n=259).

## Architecture

```
scripts/
├── xauusd_entry_m5.sh    # M5 engine (legacy single-TF; kept for compatibility)
├── xauusd_entry_tf.sh    # Core engine: parameterized by TF env var (m1/m5/m15)
├── xauusd_entry_m1.sh    # M1 wrapper (TF=m1, 60s poll)
├── xauusd_entry_m15.sh   # M15 wrapper (TF=m15, 300s poll)
├── xauusd_tg_cmd.sh      # Telegram command handler (/check, /chart, /history, ...)
├── make_chart.py         # Entry chart renderer: pattern/Donchian + SL/TP levels
├── entry_scoreboard.py   # Learning loop: scores every signal, weekly review
├── xauusd_watchdog.py    # Dead man's switch: keeps the system alive
└── send_tg.py            # Telegram sender (direct Bot API)

data/
├── xauusd_ohlc.py        # XAU/USD price feed (Twelve Data 1min/5min/15min/1h, Kraken fallback)
├── forex_news.py         # Forex news headlines (Finnhub) — keyword warnings
└── release_calendar.py   # Economic calendar: NFP/CPI/PPI/GDP (FRED)

research/                 # Backtests + result reports (failures documented too)
```

**Tested and REJECTED** (so you don't repeat them): EMA-cross as entry trigger,
session filter, 2.0×ATR stop loss, 0.75R TP1, breakout-depth filter, volatility
filter, M5/M15 EMA as filters, post-SL cooldown. See `research/*_RESULTS.md`.

## Installation

```bash
git clone <repo-url>
cd xauusd-telegram-alert
cp .env.example .env
# fill in TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TWELVE_DATA_API_KEY in .env
```

1. Create a bot via [@BotFather](https://t.me/BotFather), note the token and your chat ID.
2. Get a free API key from [Twelve Data](https://twelvedata.com) (primary feed).
   Optional: [Finnhub](https://finnhub.io) (news), [FRED](https://fred.stlouisfed.org) (calendar).
3. Adjust the state/log paths in the scripts to your environment
   (defaults point to `~/hooks/state/` and `~/hooks/logs/`).
4. Run the alert pollers via cron/systemd:
   - `scripts/xauusd_entry_m1.sh` every 1 minute (M1)
   - `scripts/xauusd_entry_m5.sh` every 5 minutes (M5)
   - `scripts/xauusd_entry_m15.sh` every 5 minutes (M15)
   Each is independent — enable only the timeframes you want.

> Note: the scripts were built for a specific VM setup with a custom credential
> pattern (`dynamic_credentials` surrogate). On other environments, replace the
> API calls in `data/*.py` with your API key from `.env` directly.

## Telegram Commands

**Alerts (per timeframe, independent):**
`/alert_on` `/alert_off` — M5 (default)
`/alert_on_m1` `/alert_off_m1` — M1
`/alert_on_m15` `/alert_off_m15` — M15
`/alert_status` — status of all three

**Info & management:**
`/check` `/chart` `/trend` `/history` `/set_balance`
`/skip_trade` `/close_trade` `/cancel_trade` `/reset_trade`

## License

MIT — use, modify, and share freely. The risk is yours.
