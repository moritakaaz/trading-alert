#!/bin/bash
# Telegram command handler for XAUUSD alerts on the dedicated alert bot
# (@ahsudahlah_bot — no other poller on this token, so no update conflicts).
# Polls getUpdates (own offset), handles /start /alert_on /alert_off
# /alert_status /check /chart for Faqih only.
# Replies go via Telegram Bot API directly; this hook NEVER wakes a worker.
STATE_FILE="$HOME/hooks/state/xauusd_entry_m5.json"
OFFSET_FILE="$HOME/hooks/state/tg_cmd_offset.json"
ALERT_LOG="$HOME/hooks/logs/xauusd-entry-m5.jsonl"
JOURNAL="$HOME/hooks/state/entry_journal.csv"
mkdir -p "$(dirname "$STATE_FILE")"

python3 - "$STATE_FILE" "$OFFSET_FILE" "$ALERT_LOG" "$JOURNAL" <<'PYEOF'
import json, sys, time, subprocess, urllib.request, urllib.parse, datetime, os, csv

STATE_FILE, OFFSET_FILE, ALERT_LOG, JOURNAL = sys.argv[1:5]
DRY = os.environ.get("HATCH_HOOK_DRY_RUN") == "1"
ENV_FILE = os.path.expanduser("~/.tg-alert-bot/.env")  # dedicated alert bot
TD_CLI = os.path.expanduser("~/workspace/skills/twelve-data/bin/xauusd_ohlc.py")
CHART_PY = os.path.expanduser("~/hooks/scripts/make_chart.py")

def tg_creds():
    tok, cid = None, None
    with open(ENV_FILE) as f:
        for line in f:
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                tok = line.strip().split("=", 1)[1]
            elif line.startswith("TELEGRAM_CHAT_ID="):
                cid = line.strip().split("=", 1)[1]
    if not tok or not cid:
        raise RuntimeError("no tg creds")
    return tok, cid

def out(decision, reason, payload=None):
    print("HATCH_HOOK_RESULT:" + json.dumps(
        {"decision": decision, "reason": reason, "payload": payload or {}}))
    sys.exit(0)

def log(msg, reason):
    print("HATCH_HOOK_LOG:" + json.dumps({"message": msg, "reason": reason}),
          file=sys.stderr)

def tg_api(method, params=None, timeout=25):
    # B38: catch HTTPError so one bad API call doesn't kill the whole poll
    tok, _ = tg_creds()
    url = f"https://api.telegram.org/bot{tok}/{method}"
    data = urllib.parse.urlencode(params or {}).encode() if params else None
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "Mozilla/5.0"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=timeout))
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode()[:200]
        except Exception:
            body = ""
        log("xauusd-tg-cmd", f"tg-http-error:{method}:{e.code}:{body[:80]}")
        return {"ok": False, "error_code": e.code, "description": body}

def tg_send(chat_id, text, keyboard=None):
    if DRY:
        return
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if keyboard:
        payload["reply_markup"] = json.dumps(keyboard, separators=(",", ":"))
    tg_api("sendMessage", payload)

def _curl_noleak(url, args, timeout=45):
    """B30 (P1): run curl without exposing the bot token in process argv."""
    import tempfile
    _cfg = tempfile.NamedTemporaryFile(mode="w", suffix=".curlcfg", delete=False)
    try:
        _cfg.write('url = "%s"\n' % url.replace('"', "%22"))
        _cfg.close()
        return subprocess.run(["curl", "-K", _cfg.name] + args,
                              capture_output=True, timeout=timeout)
    finally:
        try:
            os.unlink(_cfg.name)
        except Exception:
            pass

def tg_send_photo(chat_id, photo_path, caption):
    # photo upload via curl (multipart); token stays in the URL, never logged.
    # NOTE: caption must already be valid HTML (with <b> etc.) — do NOT
    # escape it here, or the tags break and Telegram truncates the caption.
    if DRY:
        return
    tok, _ = tg_creds()
    if not os.path.isfile(photo_path):
        return
    _curl_noleak(f"https://api.telegram.org/bot{tok}/sendPhoto",
                   ["-s", "-m", "40",
                    "-F", "chat_id=" + chat_id,
                    "-F", "photo=@" + photo_path,
                    "-F", "caption=" + caption,
                    "-F", "parse_mode=HTML"],
                   timeout=45)

def tg_send_document(chat_id, doc_path, caption):
    # document upload via curl (multipart)
    if DRY:
        return
    tok, _ = tg_creds()
    if not os.path.isfile(doc_path):
        return
    _curl_noleak(f"https://api.telegram.org/bot{tok}/sendDocument",
                   ["-s", "-m", "60",
                    "-F", "chat_id=" + chat_id,
                    "-F", "document=@" + doc_path,
                    "-F", "caption=" + caption],
                   timeout=65)

def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def load_state():
    try:
        return json.load(open(STATE_FILE))
    except Exception:
        return {}

def save_state(st):
    if not DRY:
        # re-read fresh to avoid clobbering the alert script's fields;
        # exclusive lock on separate .lock file + atomic write.
        # (Lock must be on separate file because os.replace() swaps inode.)
        import fcntl, tempfile
        lock_path = STATE_FILE + ".lock"
        with open(lock_path, "a+") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                try:
                    with open(STATE_FILE) as f:
                        cur = json.load(f)
                except Exception:
                    cur = {}
                cur.update(st)
                d = os.path.dirname(STATE_FILE) or "."
                fd, tmp = tempfile.mkstemp(dir=d, prefix=".state_tmp_")
                try:
                    with os.fdopen(fd, "w") as tf:
                        json.dump(cur, tf)
                    os.replace(tmp, STATE_FILE)
                except Exception:
                    try:
                        os.unlink(tmp)
                    except Exception:
                        pass
                    raise
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)

# ---- multi-TF alert switches (v2.1): each TF has its own state file
# with its own alert_on flag. /alert_on|off = M5 (legacy behavior unchanged).
TF_STATE_FILES = {
    "m1": os.path.expanduser("~/hooks/state/xauusd_entry_m1.json"),
    "m5": os.path.expanduser("~/hooks/state/xauusd_entry_m5.json"),
    "m15": os.path.expanduser("~/hooks/state/xauusd_entry_m15.json"),
}

def load_tf_state(tf):
    try:
        return json.load(open(TF_STATE_FILES[tf]))
    except Exception:
        return {}

def save_tf_state(tf, updates):
    if DRY:
        return
    import fcntl, tempfile
    sf = TF_STATE_FILES[tf]
    lock_path = sf + ".lock"
    with open(lock_path, "a+") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            try:
                with open(sf) as f:
                    cur = json.load(f)
            except Exception:
                cur = {}
            cur.update(updates)
            d = os.path.dirname(sf) or "."
            fd, tmp = tempfile.mkstemp(dir=d, prefix=".state_tmp_")
            try:
                with os.fdopen(fd, "w") as tf_:
                    json.dump(cur, tf_)
                os.replace(tmp, sf)
            except Exception:
                try:
                    os.unlink(tmp)
                except Exception:
                    pass
                raise
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)

JOURNAL_FILE = os.path.expanduser("~/hooks/state/entry_journal.csv")

def save_journal_rows(update_fn):
    # Locked read-modify-write for the journal CSV.
    # Prevents lost updates when alert script, command handler,
    # and scoreboard write concurrently. Atomic write ensures
    # lock-free readers see old OR new, never partial.
    if DRY:
        return False
    import fcntl, tempfile
    lock_path = JOURNAL_FILE + ".lock"
    with open(lock_path, "a+") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            rows = []
            fieldnames = None
            if os.path.exists(JOURNAL_FILE):
                with open(JOURNAL_FILE, newline="") as jf:
                    reader = csv.DictReader(jf)
                    fieldnames = reader.fieldnames
                    rows = list(reader)
            if update_fn(rows) is False:
                return False
            if fieldnames and "strategy_v" not in fieldnames:
                fieldnames = fieldnames + ["strategy_v"]
                for r in rows:
                    r.setdefault("strategy_v", "1.0")
            if not fieldnames and rows:
                fieldnames = list(rows[0].keys())
            if fieldnames:
                d = os.path.dirname(JOURNAL_FILE) or "."
                fd, tmp = tempfile.mkstemp(dir=d, prefix=".journal_tmp_")
                try:
                    with os.fdopen(fd, "w", newline="") as jf:
                        w = csv.DictWriter(jf, fieldnames=fieldnames)
                        w.writeheader()
                        w.writerows(rows)
                    os.replace(tmp, JOURNAL_FILE)
                except Exception:
                    try:
                        os.unlink(tmp)
                    except Exception:
                        pass
                    raise
            return True
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)

def get_offset():
    try:
        return int(json.load(open(OFFSET_FILE)))
    except Exception:
        return 0

def set_offset(n):
    if not DRY:
        json.dump(n, open(OFFSET_FILE, "w"))

def status_text():
    # B28: per-TF status shown below; M5-only 'on' var removed (unused)
    st = load_state()
    WIB = datetime.timezone(datetime.timedelta(hours=7))
    last_poll, n_today = "-", 0
    try:
        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        with open(os.path.expanduser(ALERT_LOG)) as f:
            for line in f:
                try:
                    e = json.loads(line)
                    ts = e.get("started_at_ms", 0) / 1000
                    if datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%d") == today:
                        n_today += 1
                        last_poll = datetime.datetime.fromtimestamp(
                            e["started_at_ms"] / 1000, WIB).strftime("%H:%M")
                except Exception:
                    pass
    except Exception:
        pass
    last_sig = "none yet"
    try:
        with open(os.path.expanduser(JOURNAL)) as f:
            rows = list(csv.DictReader(f))
            if rows:
                r = rows[-1]
                try:
                    dt = datetime.datetime.strptime(
                        r['alert_time_utc'][:19], "%Y-%m-%dT%H:%M:%S"
                    ).replace(tzinfo=datetime.timezone.utc)
                    t_wib = dt.astimezone(WIB).strftime("%d %b %H:%M")
                except Exception:
                    t_wib = r['alert_time_utc'][:16]
                last_sig = (f"{r['signal']} @ ~${r['entry_ref']} "
                            f"({t_wib} WIB, {r['status']}/{r['outcome'] or '-'})")
    except Exception:
        pass
    on = st.get("alert_on", True)
    emoji = "🟢" if on else "🔴"
    at = st.get("active_trade")
    pos_line = ""
    if at:
        tp1_px = round(at["entry"] + at["tp1_d"] * (1 if at["signal"] == "BUY" else -1), 2)
        pos_line = f"\n📌 {at['signal']} position @ ~${at['entry']} still open (TP1 ${tp1_px})"
    _m = st.get("modal") or {"amount": 600, "currency": "usc"}
    _mu = "USC" if (_m.get("currency") or "usc") == "usc" else "USD"
    # multi-TF switches (v2.1)
    _tf_lines = []
    for _tf in ("m1", "m5", "m15"):
        _s = load_tf_state(_tf)
        _on = _s.get("alert_on", True)
        _e = "🟢" if _on else "🔴"
        _tf_lines.append(f"{_e} {_tf.upper()}: {'ON' if _on else 'OFF'}")
    _tf_block = "\n".join(_tf_lines)
    return (f"🤖 <b>XAUUSD alerts by timeframe</b>\n{_tf_block}\n"
            f"💰 Balance: {_m.get('amount')} {_mu} (/set_balance to change)\n"
            f"📊 M5: {n_today}x checks today (last {last_poll} WIB)\n"
            f"🚨 Last signal: {esc(last_sig)}{pos_line}")

HELP = ("🤖 <b>XAUUSD alert bot commands</b>\n"
        "/menu — interactive button menu\n"
        "/alert_on_m5 — turn M5 alerts on\n"
        "/alert_off_m5 — turn M5 alerts off\n"
        "/alert_on_m1 — turn M1 alerts on\n"
        "/alert_off_m1 — turn M1 alerts off\n"
        "/alert_on_m15 — turn M15 alerts on\n"
        "/alert_off_m15 — turn M15 alerts off\n"
        "/alert_status — system status (all TFs)\n"
        "/check — status + last signal\n"
        "/chart — live XAUUSD chart + data\n"
        "/trend — current H1 & M15 trend\n"
        "/history — signals + results (paginated)\n"
        "/export_journal — export CSV by day/week/month/year\n"
        "/set_balance — set balance (e.g. /set_balance 600 usc)\n"
        "/set_risk — set max risk % per trade (e.g. /set_risk 2)\n"
        "/set_lot — set lot size for risk calc (e.g. /set_lot 0.01)\n"
        "/lot_calc — lot size recommender (balance+Risk+ATR)\n"
        "/skip_trade — skip signal (no entry)\n"
        "/close_trade — close manually (sl|tp1|tp2|tp3|be|manual)\n"
        "/cancel_trade — cancel signal (invalid)\n"
        "/reset_trade — reset a stuck active position (emergency)")

def history_text(page=0):
    """Journaled signals with outcomes, newest first. Times in WIB. 10 per page."""
    try:
        with open(os.path.expanduser(JOURNAL)) as f:
            rows = list(csv.DictReader(f))
    except Exception:
        return "❌ No history yet.", False, False
    if not rows:
        return "❌ No history yet.", False, False
    PER_PAGE = 10
    total_pages = (len(rows) + PER_PAGE - 1) // PER_PAGE
    page = max(0, min(page, total_pages - 1))
    start = len(rows) - (page + 1) * PER_PAGE
    end = len(rows) - page * PER_PAGE
    page_rows = rows[max(0, start):end][::-1]
    WIB = datetime.timezone(datetime.timedelta(hours=7))
    def wib(iso):
        try:
            dt = datetime.datetime.strptime(
                (iso or "")[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)
            return dt.astimezone(WIB).strftime("%d %b %H:%M")
        except Exception:
            return (iso or "")[:16]
    lines = [f"📜 <b>History</b> (page {page+1}/{total_pages})", ""]
    for r in page_rows:
        sig_emoji = "🟢" if r["signal"] == "BUY" else "🔴"
        try:
            e = float(r["entry_ref"]); m = 1 if r["signal"] == "BUY" else -1
            sl = int(round(e - m * float(r["sl_d"])))
            t1 = int(round(e + m * float(r["tp1_d"])))
            t2 = int(round(e + m * float(r["tp2_d"])))
            t3 = int(round(e + m * float(r["tp3_d"])))
            lv = f"SL ${sl} · TP1 ${t1} · TP2 ${t2} · TP3 ${t3}"
        except Exception:
            lv = ""
        oc = (r.get("outcome") or "").strip()
        rm = (r.get("r_multiple") or "").strip()
        if r["status"] == "open":
            res = "⏳ open"
        elif oc == "SL":
            res = "🛑 SL (-1R)"
        elif oc.startswith("TP"):
            rtag = ""
            try:
                rtag = f" ({float(rm):+g}R)" if rm else ""
            except ValueError:
                pass
            res = f"🎯 {oc}{rtag}"
        elif oc == "expired":
            # B14 (P1): show stored r_multiple, not hardcoded 0R
            try:
                rtag = f" ({float(rm):+g}R)" if rm else ""
            except ValueError:
                rtag = ""
            res = f"⌛ expired{rtag}"
        elif oc == "skipped":
            res = "⏭️ skipped"
        elif oc == "cancelled":
            res = "❌ cancelled"
        elif oc == "manual":
            res = "👤 manual (0R)"
        else:
            res = esc(oc) if oc else "-"
        t = wib(r.get("alert_time_utc"))
        lines.append(f"{sig_emoji} <b>{r['signal']} @ ${r['entry_ref']}</b> ({t}) → {res}")
        if lv:
            lines.append(f"   ┗ {lv}")
    has_prev = page > 0
    has_next = page < total_pages - 1
    return "\n".join(lines), has_prev, has_next

def send_history_page(chat_id, page=0):
    """Send history page with pagination buttons."""
    text, has_prev, has_next = history_text(page)
    kb = None
    if has_prev or has_next:
        buttons = []
        if has_prev:
            buttons.append({"text": "« Prev", "callback_data": f"hist:{page-1}"})
        if has_next:
            buttons.append({"text": "Next »", "callback_data": f"hist:{page+1}"})
        kb = {"inline_keyboard": [buttons]}
    tg_send(chat_id, text, keyboard=kb)

def send_export_picker(chat_id):
    """Show day/week/month/year picker for journal export."""
    kb = {"inline_keyboard": [
        [{"text": "📅 Day", "callback_data": "export:day"},
         {"text": "📊 Week", "callback_data": "export:week"}],
        [{"text": "📆 Month", "callback_data": "export:month"},
         {"text": "🗓️ Year", "callback_data": "export:year"}],
    ]}
    tg_send(chat_id, "📤 <b>Export journal</b>\nChoose period:", keyboard=kb)

def export_journal(period):
    """Export journal filtered by period. Returns (filepath, count) or (None, 0)."""
    import tempfile
    try:
        with open(os.path.expanduser(JOURNAL)) as f:
            rows = list(csv.DictReader(f))
    except Exception:
        return None, 0
    if not rows:
        return None, 0
    now = datetime.datetime.now(datetime.timezone.utc)
    def in_period(iso):
        try:
            dt = datetime.datetime.strptime(
                (iso or "")[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)
        except Exception:
            return False
        if period == "day":
            return dt.date() == now.date()
        elif period == "week":
            # last 7 days
            return (now - dt).days < 7
        elif period == "month":
            return dt.year == now.year and dt.month == now.month
        elif period == "year":
            return dt.year == now.year
        return False
    filtered = [r for r in rows if in_period(r.get("alert_time_utc", ""))]
    if not filtered:
        return None, 0
    # write to temp file
    fd, path = tempfile.mkstemp(suffix=f"_journal_{period}.csv", prefix="export_")
    with os.fdopen(fd, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(filtered)
    return path, len(filtered)

def td_ohlc(interval, n):
    r = subprocess.run([TD_CLI, "--interval", interval, "--outputsize", str(n)],
                       capture_output=True, text=True, timeout=40)
    d = json.loads(r.stdout or "{}")
    if "values" not in d:
        raise RuntimeError(d.get("error", "no values"))
    return [(v["t"], v["o"], v["h"], v["l"], v["c"]) for v in d["values"]]

def trend_text():
    # Trend context (info only since v2.1 — no filter).
    try:
        h1 = td_ohlc("1h", 80)
        m5 = td_ohlc("5min", 300)
    except Exception as ex:
        return f"❌ Failed to fetch price data: {esc(str(ex)[:60])}"
    h1c = [b[4] for b in h1]
    if len(h1c) < 55:
        return "❌ Not enough H1 data to compute trend."
    # M15 resample from M5
    _m15 = []
    _bkt = None
    for _b in m5:
        _mb = _b[0] - (_b[0] % 900)
        if _bkt is None or _bkt[0] != _mb:
            if _bkt:
                _m15.append(_bkt)
            _bkt = [_mb, _b[1], _b[2], _b[3], _b[4]]
        else:
            _bkt[2] = max(_bkt[2], _b[2])
            _bkt[3] = min(_bkt[3], _b[3])
            _bkt[4] = _b[4]
    if _bkt:
        _m15.append(_bkt)
    _now15 = int(time.time()) - (int(time.time()) % 900)
    m15c = [_b[4] for _b in _m15 if _b[0] < _now15]
    if len(m15c) < 55:
        return "❌ Not enough M15 data to compute trend."
    def _ema(vals, period):
        _k = 2.0 / (period + 1)
        _e = sum(vals[:period]) / period
        for _v in vals[period:]:
            _e = _v * _k + _e * (1 - _k)
        return _e
    h1_d = _ema(h1c, 20) - _ema(h1c, 50)
    m15_d = _ema(m15c, 20) - _ema(m15c, 50)
    h1_trend = "BULLISH" if h1_d > 0 else "BEARISH"
    m15_trend = "BULLISH" if m15_d > 0 else "BEARISH"
    now_px = h1c[-1]
    # B08: this is last CLOSED H1 bar, not live price
    WIB = datetime.timezone(datetime.timedelta(hours=7))
    _h1_t = datetime.datetime.fromtimestamp(h1[-1][0], datetime.timezone.utc).astimezone(WIB).strftime("%H:%M")
    e1 = "🟢" if h1_trend == "BULLISH" else "🔴"
    em = "🟢" if m15_trend == "BULLISH" else "🔴"
    # B07 (P1): trend filter was REMOVED in v2.1 — show as info only
    return (f"📊 <b>Current XAUUSD trend</b>\n\n"
            f"{e1} <b>H1: {h1_trend}</b> (EMA20/50)\n"
            f"{em} <b>M15: {m15_trend}</b> (EMA20/50)\n"
            f"   → info only, does not filter signals\n\n"
            f"💰 Last H1 close: <b>${now_px:,.2f}</b> ({_h1_t} WIB)\n"
            f"[strat v2.5]")

def last_signal():
    """Last journaled signal (the durable source of truth for /chart),
    or None if no signals yet."""
    try:
        with open(os.path.expanduser(JOURNAL)) as f:
            rows = list(csv.DictReader(f))
        return rows[-1] if rows else None
    except Exception:
        return None

def handle_chart():
    """Render a live XAUUSD M5 chart showing the LAST signal's entry/SL/TP
    levels (from the journal) + NOW price.
    Open signals: solid lines. Closed signals: dimmed dashed + outcome label.
    No signals yet: NOW mode (current price only).
    Returns (photo_path_or_None, caption_or_error)."""
    try:
        m5 = td_ohlc("5min", 80)
        h1 = td_ohlc("1h", 70)
    except Exception:
        return None, "❌ Failed to fetch price data, try again shortly."
    now_ts = int(time.time())
    m5b = now_ts - (now_ts % 300)
    closed5 = [b for b in m5 if b[0] < m5b]
    if len(closed5) < 3:
        return None, "❌ Not enough M5 data."
    sig_bar = closed5[-1]
    hour_start = sig_bar[0] - (sig_bar[0] % 3600)
    h1c = [b for b in h1 if b[0] < hour_start]
    if len(h1c) < 62:
        return None, "❌ Not enough H1 data."
    trs = []
    for k in range(len(h1c) - 14, len(h1c)):
        h, l, pc = h1c[k][2], h1c[k][3], h1c[k - 1][4]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    a1 = sum(trs) / len(trs)
    cur = int(round(closed5[-1][4]))
    WIB = datetime.timezone(datetime.timedelta(hours=7))
    wib_s = datetime.datetime.fromtimestamp(
        sig_bar[0], datetime.timezone.utc).astimezone(WIB).strftime("%d %b %H:%M")
    row = last_signal()
    chart_dir = os.path.expanduser("~/workspace/trading-ea/charts")
    os.makedirs(chart_dir, exist_ok=True)
    chart_path = os.path.join(chart_dir, "now_%d.png" % sig_bar[0])
    bars_in = [{"t": b[0], "o": b[1], "h": b[2], "l": b[3], "c": b[4]}
               for b in closed5[-72:]]
    atr_cap = f"📏 H1 ATR ${int(round(a1))}"
    def signal_age(iso):
        try:
            dt = datetime.datetime.strptime(
                (iso or "")[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)
            secs = max(0, int(time.time()) - int(dt.timestamp()))
            h, rem = divmod(secs, 3600); m = rem // 60
            return f"{h}h {m}m ago" if h else f"{m}m ago"
        except Exception:
            return ""
    if row:
        sig = row["signal"]
        m = 1 if sig == "BUY" else -1
        try:
            e = float(row["entry_ref"])
            s_d = float(row["sl_d"]); t1d = float(row["tp1_d"])
            t2d = float(row["tp2_d"]); t3d = float(row["tp3_d"])
        except (ValueError, KeyError):
            return None, "❌ Signal data corrupted."
        is_open = row["status"] == "open"
        try:
            sig_epoch = int(datetime.datetime.strptime(
                row["alert_time_utc"][:19], "%Y-%m-%dT%H:%M:%S"
            ).replace(tzinfo=datetime.timezone.utc).timestamp())
        except Exception:
            sig_epoch = None
        chart_in = {"bars": bars_in,
                    "signal": sig, "entry": e,
                    "sl": s_d, "tp1": t1d, "tp2": t2d, "tp3": t3d,
                    "bar_time_wib": wib_s, "out": chart_path,
                    "entry_line": True, "hist": not is_open,
                    "sig_t": sig_epoch}
        sl_px = int(round(e - m * s_d)); tp1_px = int(round(e + m * t1d))
        age = signal_age(row.get("alert_time_utc"))
        age_s = f" ⏳ signal {age}" if age else ""
        if is_open:
            pnl = int(round((cur - e) * m))
            cap = (f"📊 <b>{sig} @ ${int(round(e))}</b> — now ${cur} ({pnl:+d}){age_s}\n"
                   f"🛑 SL ${sl_px} | 🎯 TP1 ${tp1_px}\n"
                   f"{atr_cap}")
        else:
            oc = (row.get("outcome") or "").strip()
            rm = (row.get("r_multiple") or "").strip()
            rtag = ""
            try:
                rtag = f" ({float(rm):+g}R)" if rm else ""
            except ValueError:
                pass
            chart_in["hist_label"] = f"→ {oc}{rtag}" if oc else ""
            cap = (f"📊 <b>Last signal: {sig} @ ${int(round(e))}</b> → {oc}{rtag}\n"
                   f"{atr_cap}")
    else:
        chart_in = {"bars": bars_in,
                    "signal": "NOW", "entry": cur,
                    "bar_time_wib": wib_s, "out": chart_path}
        cap = (f"📊 <b>XAUUSD ${cur}</b> ({wib_s} WIB)\n"
               f"{atr_cap}")
    try:
        tmp_in = chart_path + ".json"
        json.dump(chart_in, open(tmp_in, "w"))
        r = subprocess.run([sys.executable, CHART_PY, tmp_in],
                           capture_output=True, text=True, timeout=60)
        os.remove(tmp_in)
        if not os.path.exists(chart_path):
            return None, "❌ Failed to render chart."
        # keep only the 20 newest now_*.png (entry charts are pruned separately)
        import glob as _glob
        files = sorted(_glob.glob(os.path.join(chart_dir, "now_*.png")),
                       key=os.path.getmtime)
        for old in files[:-20]:
            os.remove(old)
    except Exception:
        return None, "❌ Failed to render chart."
    return chart_path, cap

def send_chart(chat_id):
    """B40: unified chart sender — single place for /chart logic."""
    photo, cap_or_err = handle_chart()
    if photo:
        tg_send_photo(chat_id, photo, cap_or_err)
    else:
        tg_send(chat_id, cap_or_err)

def handle_callback(data):
    # inline-keyboard taps from alert messages; mirrors the / commands
    _, chat_id = tg_creds()
    # B09: chart callback may include TF (e.g. "chart:m1")
    if data == "chart" or data.startswith("chart:"):
        send_chart(chat_id)  # B40: unified
    elif data == "status":
        tg_send(chat_id, status_text())
    elif data.startswith("hist:"):
        # history pagination
        try:
            _page = int(data.split(":", 1)[1])
            send_history_page(chat_id, _page)
        except Exception:
            pass
    elif data.startswith("export:"):
        # journal export by period
        _period = data.split(":", 1)[1]
        _path, _count = export_journal(_period)
        if _path and _count > 0:
            # send as document
            try:
                tg_send_document(chat_id, _path,
                    f"📤 Journal export ({_period}): {_count} trades")
            except Exception as e:
                tg_send(chat_id, f"❌ Export failed: {str(e)[:60]}")
            finally:
                try:
                    os.unlink(_path)
                except Exception:
                    pass
        else:
            tg_send(chat_id, f"❌ No trades found for period: {_period}")
    elif data.startswith("bal:cur:"):
        # User tapped a currency -> prompt for amount
        _cur = data.split(":", 2)[2]
        _unit = {"idr": "IDR", "usd": "USD", "usc": "USDc"}[_cur]
        save_state({"_pending_balance_cur": _cur})
        tg_send(chat_id,
                f"💵 Enter balance amount for <b>{_unit}</b>:\n"
                f"(just type the number, e.g. <code>1500000</code>)")
    elif data == "bal:del":
        # Show delete options
        st0 = load_state()
        bals = st0.get("balances") or {}
        _btns = []
        for _c in ("idr", "usd", "usc"):
            if _c in bals:
                _u = {"idr": "IDR", "usd": "USD", "usc": "USDc"}[_c]
                _btns.append({"text": f"🗑️ {_u} ({bals[_c]:,})",
                              "callback_data": f"bal:del:{_c}"})
        _kb_rows = [[b] for b in _btns]
        _kb_rows.append([{"text": "🗑️ Delete ALL", "callback_data": "bal:del:all"}])
        _kb_rows.append([{"text": "« Cancel", "callback_data": "bal:cancel"}])
        tg_send(chat_id, "🗑️ <b>Delete which balance?</b>",
                keyboard={"inline_keyboard": _kb_rows})
    elif data.startswith("bal:del:"):
        _target = data.split(":", 2)[2]
        st0 = load_state()
        bals = st0.get("balances") or {}
        if _target == "all":
            save_state({"balances": {"usc": 600},
                       "modal": {"amount": 600, "currency": "usc"},
                       "active_currency": "usc",
                       "_pending_balance_cur": None})
            tg_send(chat_id, "🗑️ <b>All balances deleted.</b> Reset to default 600 USDc.")
        elif _target in bals:
            _u = {"idr": "IDR", "usd": "USD", "usc": "USDc"}[_target]
            del bals[_target]
            # If deleted active, fall back to usc default
            _active = st0.get("active_currency", "usc")
            if _active == _target:
                _active = "usc"
                _modal = {"amount": 600, "currency": "usc"}
            else:
                _modal = {"amount": bals.get(_active, 600), "currency": _active}
            save_state({"balances": bals, "active_currency": _active,
                       "modal": _modal})
            tg_send(chat_id, f"🗑️ <b>{_u} balance deleted.</b>")
        else:
            tg_send(chat_id, "❌ Nothing to delete.")
    elif data == "bal:cancel":
        tg_send(chat_id, "Cancelled.")
    elif data.startswith("bal:active:"):
        _cur = data.split(":", 2)[2]
        st0 = load_state()
        bals = st0.get("balances") or {}
        if _cur in bals:
            _unit = {"idr": "IDR", "usd": "USD", "usc": "USDc"}[_cur]
            save_state({"active_currency": _cur,
                       "modal": {"amount": bals[_cur], "currency": _cur},
                       "_pending_balance_cur": None})
            tg_send(chat_id, f"✅ <b>Active currency: {_unit} ({bals[_cur]:,})</b>\n"
                            f"Risk calculations now use this balance.")
        else:
            tg_send(chat_id, "❌ No balance set for this currency.")
    # B09: parse TF from callback_data (e.g. "pause_1h:m1", "alert_off:m15")
    # Pause must NOT change alert_on. Each TF's state is modified independently.
    elif data == "pause_1h" or data.startswith("pause_1h:"):
        _action, _, _tf = data.partition(":")
        _tf = _tf or "m5"
        save_tf_state(_tf, {"paused_until": int(time.time()) + 3600})
        tg_send(chat_id,
                f"⏸️ <b>{_tf.upper()} alerts paused for 1 hour.</b>\n"
                f"Entry signals paused, heartbeat still running.\n"
                f"Send /alert_on_{_tf} to resume sooner.")
    elif data == "alert_off" or data.startswith("alert_off:"):
        _action, _, _tf = data.partition(":")
        _tf = _tf or "m5"
        save_tf_state(_tf, {"alert_on": False, "paused_until": 0})
        tg_send(chat_id,
                f"🔴 <b>XAUUSD {_tf.upper()} alerts turned off.</b>\n"
                f"Send /alert_on_{_tf} to turn them on again.")
    elif data.startswith("menu:"):
        # interactive menu navigation (v2.4)
        _m = data.split(":", 1)[1]
        _kb, _txt = build_menu(_m)
        # edit the menu message in place
        try:
            # get message_id from callback query - need to pass it
            # for now, send new message (simpler, robust)
            tg_send(chat_id, _txt, keyboard=_kb)
        except Exception:
            pass
    elif data.startswith("cmd:"):
        # execute a command from menu button
        _cmd = data.split(":", 1)[1]
        if _cmd == "/chart":
            send_chart(chat_id)  # B40: unified
        else:
            reply = handle(_cmd)
            if reply:
                if reply.startswith("HISTORY:"):
                    _page = int(reply.split(":", 1)[1])
                    send_history_page(chat_id, _page)
                elif reply == "EXPORT_PICKER":
                    send_export_picker(chat_id)
                else:
                    tg_send(chat_id, reply)

def build_menu(section="main"):
    # v2.4: interactive categorized menu
    if section == "alerts":
        kb = {"inline_keyboard": [
            [{"text": "🟢 M5 ON", "callback_data": "cmd:/alert_on_m5"},
             {"text": "🔴 M5 OFF", "callback_data": "cmd:/alert_off_m5"}],
            [{"text": "🟢 M1 ON", "callback_data": "cmd:/alert_on_m1"},
             {"text": "🔴 M1 OFF", "callback_data": "cmd:/alert_off_m1"}],
            [{"text": "🟢 M15 ON", "callback_data": "cmd:/alert_on_m15"},
             {"text": "🔴 M15 OFF", "callback_data": "cmd:/alert_off_m15"}],
            [{"text": "📊 Status", "callback_data": "cmd:/alert_status"}],
            [{"text": "« Back", "callback_data": "menu:main"}],
        ]}
        return kb, "🚨 <b>Alerts</b> — on/off per timeframe"
    elif section == "info":
        kb = {"inline_keyboard": [
            [{"text": "✅ Check", "callback_data": "cmd:/check"},
             {"text": "📈 Chart", "callback_data": "cmd:/chart"}],
            [{"text": "📊 Trend", "callback_data": "cmd:/trend"},
             {"text": "📜 History", "callback_data": "cmd:/history"}],
            [{"text": "« Back", "callback_data": "menu:main"}],
        ]}
        return kb, "📊 <b>Info</b> — status, charts, history"
    elif section == "risk":
        kb = {"inline_keyboard": [
            [{"text": "💰 Balance", "callback_data": "cmd:/set_balance"},
             {"text": "⚖️ Risk %", "callback_data": "cmd:/set_risk"}],
            [{"text": "📐 Lot size", "callback_data": "cmd:/set_lot"},
             {"text": "🧮 Lot calc", "callback_data": "cmd:/lot_calc"}],
            [{"text": "« Back", "callback_data": "menu:main"}],
        ]}
        return kb, "⚖️ <b>Risk</b> — balance, risk %, lot size"
    elif section == "trade":
        kb = {"inline_keyboard": [
            [{"text": "⏭️ Skip", "callback_data": "cmd:/skip_trade"},
             {"text": "✅ Close", "callback_data": "cmd:/close_trade"}],
            [{"text": "❌ Cancel", "callback_data": "cmd:/cancel_trade"},
             {"text": "🔄 Reset", "callback_data": "cmd:/reset_trade"}],
            [{"text": "« Back", "callback_data": "menu:main"}],
        ]}
        return kb, "🔧 <b>Trade</b> — manage positions"
    else:  # main
        kb = {"inline_keyboard": [
            [{"text": "🚨 Alerts", "callback_data": "menu:alerts"},
             {"text": "📊 Info", "callback_data": "menu:info"}],
            [{"text": "⚖️ Risk", "callback_data": "menu:risk"},
             {"text": "🔧 Trade", "callback_data": "menu:trade"}],
        ]}
        return kb, "🤖 <b>Menu</b> — choose a category:"

def handle(text):
    cmd = text.strip().split()[0].split("@")[0].lower()
    # Pending balance amount: user tapped a currency button, now types the number
    if not cmd.startswith("/"):
        st0 = load_state()
        _pending = st0.get("_pending_balance_cur")
        if _pending:
            _txt = text.strip().replace(",", "").replace(".", "", 1) if "." in text.strip() else text.strip().replace(",", "")
            # Allow decimals
            try:
                _clean = text.strip().replace(",", "")
                amount = float(_clean)
            except ValueError:
                return "❌ Please enter a valid number, or /set_balance to cancel."
            if amount <= 0:
                return "❌ Amount must be greater than 0."
            bals = st0.get("balances") or {}
            bals[_pending] = int(amount) if amount == int(amount) else round(amount, 2)
            _unit = {"idr": "IDR", "usd": "USD", "usc": "USDc"}[_pending]
            save_state({"balances": bals, "active_currency": _pending,
                       "modal": {"amount": bals[_pending], "currency": _pending},
                       "_pending_balance_cur": None})
            return (f"✅ <b>Balance set: {bals[_pending]:,} {_unit}</b>\n"
                    f"This is now the active currency for risk calculations.")
    if cmd == "/start":
        return HELP
    if cmd == "/menu":
        # v2.4: interactive categorized menu (returns special marker)
        return "MENU:main"
    if cmd == "/set_balance":
        # Interactive: /set_balance -> currency buttons -> enter amount
        # Also supports: /set_balance 600 usc (legacy)
        parts = text.strip().split()
        # Legacy direct: /set_balance <amount> [currency]
        if len(parts) >= 2 and parts[1].replace(".","",1).replace("-","",1).isdigit():
            try:
                amount = float(parts[1])
            except ValueError:
                return "❌ Amount must be a number."
            if amount <= 0:
                return "❌ Amount must be greater than 0."
            st0 = load_state()
            bals = st0.get("balances") or {}
            active = st0.get("active_currency", "usc")
            if len(parts) > 2:
                cur = parts[2].lower().replace("usdc","usc")
                if cur not in ("idr", "usd", "usc"):
                    return "❌ Currency must be: idr, usd, or usc."
                active = cur
            bals[active] = int(amount) if amount == int(amount) else round(amount, 2)
            save_state({"balances": bals, "active_currency": active,
                       "modal": {"amount": bals[active], "currency": active}})
            unit = {"idr": "IDR", "usd": "USD", "usc": "USC"}[active]
            return (f"✅ <b>Balance set: {bals[active]:,} {unit}</b>\n"
                    f"Risk % in alerts now uses this figure.")
        # Interactive mode: show currency picker
        st0 = load_state()
        bals = st0.get("balances") or {}
        active = st0.get("active_currency", "usc")
        lines = ["💰 <b>Balance Setup</b>", ""]
        for c in ("idr", "usd", "usc"):
            unit = {"idr": "IDR", "usd": "USD", "usc": "USC"}[c]
            amt = bals.get(c, "—")
            mark = " ✅" if c == active else ""
            lines.append(f"• {unit}: {amt:,}{mark}" if isinstance(amt,(int,float)) else f"• {unit}: —{mark}")
        lines.append("")
        lines.append("Tap a currency to set its balance, or 🗑️ to delete.")
        kb_rows = [
            [{"text": "💵 IDR", "callback_data": "bal:cur:idr"},
             {"text": "💵 USD", "callback_data": "bal:cur:usd"},
             {"text": "💵 USDc", "callback_data": "bal:cur:usc"}],
        ]
        # Set active currency buttons (only for currencies with balance set)
        _active_btns = []
        for _c in ("idr", "usd", "usc"):
            if _c in bals and _c != active:
                _u = {"idr": "IDR", "usd": "USD", "usc": "USDc"}[_c]
                _active_btns.append({"text": f"✅ {_u}", "callback_data": f"bal:active:{_c}"})
        if _active_btns:
            kb_rows.append(_active_btns)
        kb_rows.append([{"text": "🗑️ Delete balance", "callback_data": "bal:del"}])
        kb = {"inline_keyboard": kb_rows}
        return ("\n".join(lines), kb)
    if cmd == "/set_risk":
        # /set_risk 2  -> max 2% risk per trade
        parts = text.strip().split()
        if len(parts) < 2:
            st0 = load_state()
            _rp = st0.get("risk_pct_limit", 2.0)
            return (f"⚖️ Current max risk: <b>{_rp}%</b> per trade\n"
                    f"Usage: /set_risk &lt;percent&gt;\n"
                    f"Example: /set_risk 2")
        try:
            pct = float(parts[1])
        except ValueError:
            return "❌ Percent must be a number. Example: /set_risk 2"
        if pct <= 0 or pct > 100:
            return "❌ Percent must be between 0 and 100."
        save_state({"risk_pct_limit": pct})
        return (f"✅ <b>Max risk set: {pct}%</b> per trade\n"
                f"Alerts will warn when a signal exceeds this.")
    if cmd == "/set_lot":
        # /set_lot 0.01 -> lot size for risk calculations
        parts = text.strip().split()
        if len(parts) < 2:
            st0 = load_state()
            _ls = st0.get("lot_size", 0.01)
            return (f"📐 Current lot size: <b>{_ls}</b>\n"
                    f"Usage: /set_lot &lt;size&gt;\n"
                    f"Example: /set_lot 0.01")
        try:
            ls = float(parts[1])
        except ValueError:
            return "❌ Lot size must be a number. Example: /set_lot 0.01"
        if ls < 0.01 or ls > 100:
            return "❌ Lot size must be between 0.01 and 100."
        save_state({"lot_size": ls})
        return (f"✅ <b>Lot size set: {ls}</b>\n"
                f"Risk calculations in alerts now use this.")
    if cmd == "/lot_calc":
        # Calculate recommended & max lot based on balance, risk%, and current ATR
        st0 = load_state()
        modal = st0.get("modal") or {"amount": 600, "currency": "usc"}
        bal = float(modal.get("amount") or 600)
        unit = "USC" if (modal.get("currency") or "usc") == "usc" else "USD"
        risk_lim = float(st0.get("risk_pct_limit") or 2.0)
        # B26 (P1): get live H1 ATR from engine state (saved each poll)
        try:
            _m5s = {}
            _mp = os.path.expanduser("~/hooks/state/xauusd_entry_m5.json")
            if os.path.isfile(_mp):
                with open(_mp) as _f:
                    _m5s = json.load(_f)
            atr = float(_m5s.get("last_atr_h1") or 12.0)
        except Exception:
            atr = 12.0  # fallback only if state unreadable
        sl_d = 1.5 * atr
        max_risk_usc = bal * (risk_lim / 100)
        # lot for exact risk%: L = max_risk / (SL_d * 100)
        rec_lot = max_risk_usc / (sl_d * 100) if sl_d > 0 else 0.01
        # round down to 0.01 step
        import math as _math
        rec_lot = max(0.01, _math.floor(rec_lot * 100) / 100)
        # max lot: 1.5x recommended (aggressive) - still within 1.5x risk
        max_lot = _math.floor(rec_lot * 1.5 * 100) / 100
        lines = [f"📐 <b>Lot Calculator</b>",
                 f"💰 Balance: {bal:.0f} {unit} | Risk: {risk_lim}%",
                 f"📊 Est. SL: ${sl_d:.0f} (1.5×ATR~${atr:.0f})",
                 f"",
                 f"✅ <b>Recommended: {rec_lot:.2f} lot</b> (= {risk_lim}% risk)",
                 f"⚠️ <b>Maximum: {max_lot:.2f} lot</b> (= {risk_lim*1.5:.1f}% risk)",
                 f"",
                 f"Lot → Risk:"]
        for _l in [0.01, 0.02, 0.03, 0.05, 0.10]:
            _r = sl_d * (_l / 0.01) / bal * 100 if bal > 0 else 0
            _mark = " ← you" if abs(_l - float(st0.get("lot_size") or 0.01)) < 0.005 else ""
            lines.append(f"  {_l:.2f} lot → {_r:.1f}%{_mark}")
        return "\n".join(lines)
    if cmd in ("/alert_on", "/alert_on_m5"):
        save_state({"alert_on": True, "paused_until": 0})
        return ("🟢 <b>XAUUSD M5 alerts turned on.</b>\n"
                "BUY/SELL signals + 5-min heartbeat active.")
    if cmd in ("/alert_off", "/alert_off_m5"):
        save_state({"alert_on": False})
        return ("🔴 <b>XAUUSD M5 alerts turned off.</b>\n"
                "Send /alert_on_m5 to turn them on again.")
    if cmd in ("/alert_on_m1", "/alert_off_m1",
               "/alert_on_m15", "/alert_off_m15"):
        # multi-TF switches (v2.1): independent on/off per timeframe
        _tf = "m1" if cmd.endswith("_m1") else "m15"
        _turn_on = cmd.startswith("/alert_on")
        save_tf_state(_tf, {"alert_on": _turn_on,
                            "paused_until": 0} if _turn_on else {"alert_on": False})
        _e = "🟢" if _turn_on else "🔴"
        _w = "on" if _turn_on else "off"
        return (f"{_e} <b>XAUUSD {_tf.upper()} alerts turned {_w}.</b>\n"
                f"Send /alert_{'off' if _turn_on else 'on'}_{_tf} to turn them "
                f"{'off' if _turn_on else 'on'} again.")
    if cmd == "/alert_status":
        # concise: TF on/off only
        _lines = ["🤖 <b>XAUUSD alerts</b>"]
        for _tf in ("m1", "m5", "m15"):
            _s = load_tf_state(_tf)
            _on = _s.get("alert_on", True)
            _e = "🟢" if _on else "🔴"
            _lines.append(f"{_e} {_tf.upper()}: {'ON' if _on else 'OFF'}")
        return "\n".join(_lines)
    if cmd == "/check":
        return status_text()
    if cmd == "/history":
        return "HISTORY:0"  # special marker, handled in poller loop with pagination
    if cmd == "/export_journal":
        return "EXPORT_PICKER"  # special marker, shows day/week/month/year picker
    if cmd == "/trend":
        return trend_text()
    if cmd in ("/skip_trade", "/close_trade", "/cancel_trade"):
        # Manual trade lifecycle: user didn't take the signal (/skip_trade),
        # closed it manually with an outcome (/close_trade sl|tp1|tp2|tp3|be|manual),
        # or the signal was invalid (/cancel_trade).
        # All clear active_trade AND mark the journal so self-healing
        # doesn't resurrect a trade the user already handled.
        st0 = load_state()
        at = st0.get("active_trade")
        # also check journal for open entries (in case state desynced)
        jpath = os.path.expanduser("~/hooks/state/entry_journal.csv")
        open_rows = []
        try:
            with open(jpath) as jf:
                open_rows = [r for r in csv.DictReader(jf)
                             if r.get("status") == "open"]
        except Exception:
            pass
        if not at and not open_rows:
            return ("ℹ️ No active position.\n"
                    "Nothing to skip/close/cancel.")
        outcome_map = {
            "/skip_trade": ("skipped", "skipped", "0",
                            "Trade skipped — no entry."),
            "/cancel_trade": ("cancelled", "cancelled", "0",
                              "Trade cancelled — signal marked invalid."),
        }
        if cmd == "/close_trade":
            parts = text.strip().split()
            o = (parts[1] if len(parts) > 1 else "manual").lower()
            # standard outcome format for /history + scoreboard
            omap = {"sl": ("closed", "SL", "-1"),
                    "tp1": ("closed", "TP1", "1"),
                    "tp2": ("closed", "TP2", "1.5"),
                    "tp3": ("closed", "TP3", "2"),
                    "be": ("closed", "TP1+BE", "1"),  # B13 (P1): full-position model
                    "manual": ("closed", "manual", "0")}
            if o not in omap:
                return ("❌ Outcome must be: sl | tp1 | tp2 | tp3 | be | manual\n"
                        "Example: /close_trade tp1")
            _st, _oc, _rm = omap[o]
            outcome_map[cmd] = (_st, _oc, _rm,
                                f"Trade closed manually ({o}).")
        status, outcome, rmult, desc = outcome_map[cmd]
        # target ONLY the active trade's journal row (see CHANGELOG P0/B10)
        _target_iso = None
        if at and at.get("bar_ts"):
            try:
                _target_iso = datetime.datetime.fromtimestamp(
                    at["bar_ts"], datetime.timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                pass
        # v2.5: if no active_trade (state desync), target only the NEWEST open row
        if _target_iso is None and open_rows:
            _target_iso = max(r.get("alert_time_utc", "") for r in open_rows)
        # update journal under lock
        # B10: capture the target row's timeframe to clear the correct TF's state
        _target_tf = ["m5"]
        def _lifecycle_update(rows):
            _done = False
            for r in rows:
                if r.get("status") != "open":
                    continue
                # if we have a target, only close that specific row
                if _target_iso and r.get("alert_time_utc") != _target_iso:
                    continue
                r["status"] = status
                r["outcome"] = outcome
                r["closed_time_utc"] = datetime.datetime.now(
                    datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                r["r_multiple"] = rmult
                # B10: capture timeframe from the target row
                _target_tf[0] = r.get("timeframe", "m5") or "m5"
                _done = True
                if _target_iso:
                    break  # only one row matches
            return True
        try:
            save_journal_rows(_lifecycle_update)
        except Exception as ex:
            log("xauusd-tg-cmd", f"lifecycle-journal-fail:{str(ex)[:40]}")
        # B10: clear active_trade in the correct TF's state (not just M5)
        save_tf_state(_target_tf[0], {"active_trade": None})
        sig_txt = f"{at.get('signal')} @ ${at.get('entry')}" if at else \
            f"{len(open_rows)} journal open"
        log("xauusd-tg-cmd", f"{cmd}:{sig_txt}")
        return (f"✅ <b>{desc}</b>\n"
                f"Position: {sig_txt}\n"
                f"Monitoring new signals again.")
    # (duplicate handlers removed; see CHANGELOG)
    if cmd == "/reset_trade":
        # Emergency reset: clear a stuck active_trade (e.g. state desync
        # where the journal says open but no position is actually tracked,
        # or a trade that should have resolved but didn't).
        # B10: check ALL TF states (not just M5) and clear any stuck trades.
        _found = []
        for _tf in ("m1", "m5", "m15"):
            _st = load_tf_state(_tf)
            _at = _st.get("active_trade")
            if _at:
                save_tf_state(_tf, {"active_trade": None})
                _found.append(f"{_tf.upper()}: {_at.get('signal')} @ ~${_at.get('entry')}")
                log("xauusd-tg-cmd", f"reset-trade:{_tf}:{_at.get('signal')}@{_at.get('entry')}")
        if not _found:
            return ("ℹ️ No active position to reset.\n"
                    "The system is already monitoring new signals.")
        return (f"🔄 <b>active_trade reset.</b>\n"
                f"Cleared: {'; '.join(_found)}\n"
                f"The system is monitoring new signals again.")
    if cmd.startswith("/"):
        return "❓ Unknown command.\n" + HELP
    return None

try:
    _, CHAT_ID = tg_creds()
    offset = get_offset()
    # NOTE: timeout=0 (no long-poll). This bot token has no other poller,
    # so updates are never eaten by a competing client.
    d = tg_api("getUpdates", {"offset": offset, "timeout": 0,
                              "allowed_updates": json.dumps(["message", "callback_query"])})
    if not d.get("ok"):
        raise RuntimeError(str(d)[:100])
    max_id = offset
    # B29 (P1): per-update retry counter (max 3). Offset advances only after
    # successful processing or 3 failed attempts.
    _retry_file = os.path.expanduser("~/hooks/state/tg_retry.json")
    def _get_retries():
        try:
            with open(_retry_file) as _rf:
                return json.load(_rf)
        except Exception:
            return {}
    def _save_retries(_d):
        try:
            with open(_retry_file, "w") as _rf:
                json.dump(_d, _rf)
        except Exception:
            pass
    _retries = _get_retries()
    for u in d.get("result", []):
        uid = u.get("update_id", 0)
        max_id = max(max_id, uid + 1)
        try:
            try:
                # inline-keyboard taps arrive as callback_query
                cq = u.get("callback_query")
                if cq:
                    cq_chat = str((cq.get("message") or {}).get("chat", {}).get("id"))
                    if cq_chat == CHAT_ID:
                        # DRY-guard: dry runs must not send real Telegram API calls
                        if os.environ.get("HATCH_HOOK_DRY_RUN") != "1":
                            try:
                                tg_api("answerCallbackQuery",
                                       {"callback_query_id": cq.get("id")})
                            except Exception:
                                pass
                        handle_callback(cq.get("data", ""))
                        log("xauusd-tg-cmd", f"handled-callback:{cq.get('data', '')}")
                    continue
                m = u.get("message") or {}
                if str(m.get("chat", {}).get("id")) != CHAT_ID:
                    continue
                text = (m.get("text") or "").strip()
                if not text.startswith("/"):
                    # Allow plain numbers when waiting for balance amount
                    _st_chk = load_state()
                    if not _st_chk.get("_pending_balance_cur"):
                        continue
                    # Fall through to handle() for pending balance input
                cmd = text.split()[0].split("@")[0].lower()
                if cmd == "/chart":
                    send_chart(CHAT_ID)  # B40: unified
                    log("xauusd-tg-cmd", "handled:/chart")
                    continue
                reply = handle(text)
                if reply:
                    if isinstance(reply, tuple):
                        # (text, keyboard) tuple - e.g. /set_balance currency picker
                        _txt, _kb = reply
                        tg_send(CHAT_ID, _txt, keyboard=_kb)
                    elif reply.startswith("MENU:"):
                        # v2.4: interactive menu - send with keyboard
                        _section = reply.split(":", 1)[1]
                        _kb, _txt = build_menu(_section)
                        tg_send(CHAT_ID, _txt, keyboard=_kb)
                    elif reply.startswith("HISTORY:"):
                        # paginated history
                        _page = int(reply.split(":", 1)[1])
                        send_history_page(CHAT_ID, _page)
                    elif reply == "EXPORT_PICKER":
                        send_export_picker(CHAT_ID)
                    else:
                        tg_send(CHAT_ID, reply)
                    log("xauusd-tg-cmd", f"handled:{text.split()[0]}")
            finally:
                # success path (inner try completed without exception,
                # even via 'continue'): clear retry count, advance offset
                _retries.pop(str(uid), None)
                _save_retries(_retries)
                set_offset(max_id)
        except Exception as _uex:
            _cnt = _retries.get(str(uid), 0) + 1
            if _cnt >= 3:
                log("xauusd-tg-cmd", f"update-gave-up:{uid} after 3 tries: {str(_uex)[:60]}")
                _retries.pop(str(uid), None)
                _save_retries(_retries)
                set_offset(max_id)  # skip it permanently
            else:
                _retries[str(uid)] = _cnt
                _save_retries(_retries)
                log("xauusd-tg-cmd", f"update-fail:{uid}:{str(_uex)[:60]} (try {_cnt}/3)")
                break  # retry next poll; keep order
    log("xauusd-tg-cmd", "poll-ok")
except Exception as ex:
    log("xauusd-tg-cmd", f"fail:{str(ex)[:80]}")
out("silent", "tg-cmd-poll")
PYEOF
echo "HATCH_HOOK_LOG:{\"message\":\"xauusd-tg-cmd\",\"reason\":\"script-end\"}" >&2
