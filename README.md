# XAUUSD Telegram Manual-Alert System

> ⚠️ **Not financial advice.** An experimental project — the funds used are
> "learning money" (a small cent account). Do not use for live trading
> without understanding the risks.

An **XAUUSD (M5)** entry-alert system that pushes signals to Telegram:
Donchian breakouts with trend filters, automatic journaling, entry charts,
position monitoring (TP1/TP2/TP3 + breakeven), and weekly performance reviews.

## Strategy (v1.3, live)

| Component | Detail |
|---|---|
| Trigger | Donchian(48) breakout on completed H1 bars, evaluated on each M5 close |
| Stop loss | 1.5 × ATR(14) H1 |
| Take profit | TP1 1R → SL to breakeven, TP2 1.5R, TP3 2R (runner) |
| H4 trend filter | Hard filter — signals must align with the H4 trend (SMA15) |
| EMA 20/50 filter | Hard filter — BUY only if EMA20 > EMA50 on H1 (and vice versa) |
| Management | One position at a time; no signal stacking |

**Honest backtest results** (9 months, Jan–Oct 2026, 265 trades, PAXGUSDT M5 data):

| Metric | Value |
|---|---|
| Profit Factor | **1.38** |
| Win rate | 33.6% |
| Average / trade | +0.18R |
| Max drawdown | 15.3R |

Honest notes: Q3 2026 was a losing quarter. Excludes spread/commission/slippage —
live results **will be worse**. 265 trades is a medium sample. These numbers
are not a promise.

## Architecture

```
scripts/
├── xauusd_entry_m5.sh    # Core engine: 5-min polling, signal detection, alerts
├── xauusd_tg_cmd.sh      # Telegram command handler (/check, /chart, /history, ...)
├── make_chart.py         # Entry chart renderer (matplotlib): Donchian + SL/TP levels
├── entry_scoreboard.py   # Learning loop: scores every signal, weekly review
├── xauusd_watchdog.py    # Dead man's switch: keeps the system alive
└── send_tg.py            # Telegram sender (direct Bot API)

data/
├── xauusd_ohlc.py        # XAU/USD price feed (Twelve Data, Kraken PAXGUSD fallback)
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
4. Run `scripts/xauusd_entry_m5.sh` every 5 minutes via cron/systemd.

> Note: the scripts were built for a specific VM setup with a custom credential
> pattern (`dynamic_credentials` surrogate). On other environments, replace the
> API calls in `data/*.py` with your API key from `.env` directly.

## Telegram Commands

`/alert_on` `/alert_off` `/alert_status` `/check` `/chart` `/trend` `/history`
`/set_balance` `/skip_trade` `/close_trade` `/cancel_trade` `/reset_trade`

## License

MIT — use, modify, and share freely. The risk is yours.
