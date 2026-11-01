# MT5 Executor (auto-trade) — DEMO FIRST

Turns confirmed M5 ENTRY signals from the alert bot into real orders on
an MT5 account. The strategy stays in the Python bot; the EA is a dumb
executor with no signal logic.

```
Alert bot (Python, v2.7) --publish--> push channel (ntfy)
      -> bridge.py (Windows PC, next to MT5)
      -> executor_signals.csv (MT5 Common Files)
      -> ExecutorEA.mq5 (attached to the XAUUSD chart)
      -> market order, SL/TP recomputed from the actual fill price
```

## Safety design

- Auto-trade is **OFF by default**. The bot only publishes signals after
  `/auto_on` is sent to the Telegram bot. `/auto_off` stops new
  executions (it does not close open positions).
- Only **M5** confirmed ENTRY signals are published. Setup watches are
  never published.
- Every signal carries a unique id. The bridge dedupes on write and the
  EA dedupes again via `executor_processed.csv`, so a restart can never
  re-execute an old signal.
- The EA recomputes SL/TP from the **actual fill price** using the
  signal's distances. It never trusts the bot's reference price.
- Guards inside the EA: max open executor positions (default 3), max
  spread (default 0.60), fixed lot (default 0.01).
- A failed order is recorded in `executor_results.csv` and never
  retried in a loop.
- At 0.01 lot a position cannot be split, so the EA takes profit in
  full at the TP1 distance (1R). This matches the journal model.

## Install (Windows PC with MT5)

1. **Demo account first.** Create an HFM demo account, log MT5 into it.
   Do not skip this step.
2. Copy `ExecutorEA.mq5` into the MT5 Experts folder
   (MT5: File > Open Data Folder > MQL5 > Experts), open it in
   MetaEditor and press **Compile (F7)**. It must compile with
   0 errors.
3. Attach the EA to the broker's gold chart (e.g. XAUUSDc, any
   timeframe) and enable **Algo Trading**.
4. Install Python 3 on the PC if needed. Put `bridge.py` and your
   `bridge_config.json` in one folder, then run:

   ```
   python bridge.py
   ```

   Keep that window open while trading. It writes incoming signals to
   the MT5 Common Files folder automatically.
5. **Chain test:** run `python bridge.py --test`. The EA should open
   one small demo BUY (SL/TP 10) within a few seconds. Close it
   manually. If nothing happens, check: bridge window output, EA
   Experts/Journal tabs, and that both use the same Common Files
   folder.
6. When the chain test passes, send `/auto_on` to the Telegram alert
   bot. Check status any time with `/auto_status`.

## Files the EA writes (MT5 Common Files)

- `executor_processed.csv` — ids already executed (dedupe record).
- `executor_results.csv` — one line per signal: fill, SL, TP, status
  (`FILLED`, `SKIP-...`, `FAIL-...`). Send this file when debugging.

## Going live (later, separate decision)

Do not point this at a live account until the demo has run at least
1–2 weeks and its fills match the bot journal. The push channel used
for the demo is a shared relay; moving to live requires the private
transport upgrade first.

## Troubleshooting

- **EA not executing:** Algo Trading off? EA smiley/status in the chart
  corner? Any errors in the Experts tab?
- **Bridge queues but EA sleeps:** the EA polls
  `executor_signals.csv` in the **Common** Files folder
  (`%APPDATA%\MetaQuotes\Terminal\Common\Files`). If `bridge.py` was
  started with `--files-dir`, make sure it points there.
- **Wrong-secret warnings in the bridge:** the config on the PC does
  not match the bot side. Ask for a fresh `bridge_config.json`.
