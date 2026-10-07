#!/bin/bash
# Telegram command handler for XAUUSD alerts on the dedicated alert bot
# (@ahsudahlah_bot — no other poller on this token, so no update conflicts).
# Polls getUpdates (own offset), handles /start /alert_on /alert_off
# /alert_status /cek /chart for Faqih only.
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
    tok, _ = tg_creds()
    url = f"https://api.telegram.org/bot{tok}/{method}"
    data = urllib.parse.urlencode(params or {}).encode() if params else None
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))

def tg_send(chat_id, text):
    if DRY:
        return
    tg_api("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "HTML"})

def tg_send_photo(chat_id, photo_path, caption):
    # photo upload via curl (multipart); token stays in the URL, never logged.
    # NOTE: caption must already be valid HTML (with <b> etc.) — do NOT
    # escape it here, or the tags break and Telegram truncates the caption.
    if DRY:
        return
    tok, _ = tg_creds()
    if not os.path.isfile(photo_path):
        return
    subprocess.run(["curl", "-s", "-m", "40",
                    "-F", "chat_id=" + chat_id,
                    "-F", "photo=@" + photo_path,
                    "-F", "caption=" + caption,
                    "-F", "parse_mode=HTML",
                    f"https://api.telegram.org/bot{tok}/sendPhoto"],
                   capture_output=True, timeout=45)

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
    st = load_state()
    on = st.get("alert_on", True)
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
    last_sig = "belum ada"
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
    emoji = "🟢" if on else "🔴"
    at = st.get("active_trade")
    pos_line = ""
    if at:
        tp1_px = round(at["entry"] + at["tp1_d"] * (1 if at["signal"] == "BUY" else -1), 2)
        pos_line = f"\n📌 Posisi {at['signal']} @ ~${at['entry']} masih jalan (TP1 ${tp1_px})"
    _m = st.get("modal") or {"amount": 600, "currency": "usc"}
    _mu = "USC" if (_m.get("currency") or "usc") == "usc" else "USD"
    return (f"{emoji} <b>Alert XAUUSD M5: {'AKTIF' if on else 'MATI'}</b>\n"
            f"💰 Modal: {_m.get('amount')} {_mu} (/set_modal untuk ubah)\n"
            f"📊 {n_today}x cek hari ini (terakhir {last_poll} WIB)\n"
            f"🚨 Sinyal terakhir: {esc(last_sig)}{pos_line}")

HELP = ("🤖 <b>Perintah bot alert XAUUSD</b>\n"
        "/alert_on — nyalakan alert\n"
        "/alert_off — matikan alert\n"
        "/alert_status — status sistem\n"
        "/cek — status + sinyal terakhir\n"
        "/chart — chart XAUUSD live + data\n"
        "/trend — trend H4 & H1 saat ini\n"
        "/riwayat — 10 sinyal terakhir + hasil\n"
        "/set_modal — set modal (contoh: /set_modal 600 usc)\n"
        "/skip_trade — skip sinyal (nggak entry)\n"
        "/close_trade — tutup manual (sl|tp1|tp2|tp3|be|manual)\n"
        "/cancel_trade — batalkan sinyal (invalid)\n"
        "/reset_trade — reset posisi aktif yg tersangkut (darurat)")

def history_text():
    """Last 10 journaled signals with outcomes, newest first. Times in WIB."""
    try:
        with open(os.path.expanduser(JOURNAL)) as f:
            rows = list(csv.DictReader(f))
    except Exception:
        return "❌ Belum ada riwayat."
    if not rows:
        return "❌ Belum ada riwayat."
    WIB = datetime.timezone(datetime.timedelta(hours=7))
    def wib(iso):
        try:
            dt = datetime.datetime.strptime(
                (iso or "")[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)
            return dt.astimezone(WIB).strftime("%d %b %H:%M")
        except Exception:
            return (iso or "")[:16]
    lines = ["📜 <b>10 sinyal terakhir</b>", ""]
    for r in rows[-10:][::-1]:
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
            res = "⌛ expired (0R)"
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
    return "\n".join(lines)

def td_ohlc(interval, n):
    r = subprocess.run([TD_CLI, "--interval", interval, "--outputsize", str(n)],
                       capture_output=True, text=True, timeout=40)
    d = json.loads(r.stdout or "{}")
    if "values" not in d:
        raise RuntimeError(d.get("error", "no values"))
    return [(v["t"], v["o"], v["h"], v["l"], v["c"]) for v in d["values"]]

def trend_text():
    # Current trend: H4 (the signal filter) + H1 (short-term context).
    # Same H4 logic as the alert script: H1 resampled to H4, SMA(15).
    try:
        h1 = td_ohlc("1h", 80)
    except Exception as ex:
        return f"❌ Gagal ambil data harga: {esc(str(ex)[:60])}"
    closes = [b[4] for b in h1]
    if len(closes) < 60:
        return "❌ Data H1 kurang untuk hitung trend."
    # H4: resample 4x H1 -> H4 closes
    h4 = []
    for i in range(0, len(h1) - 3, 4):
        grp = h1[i:i + 4]
        h4.append(grp[-1][4])
    h4_sma = sum(h4[-15:]) / 15
    h4_trend = "BULLISH" if h4[-1] > h4_sma else "BEARISH"
    # H1 short-term: price vs SMA(20)
    h1_sma = sum(closes[-20:]) / 20
    h1_trend = "BULLISH" if closes[-1] > h1_sma else "BEARISH"
    now_px = closes[-1]
    e4 = "🟢" if h4_trend == "BULLISH" else "🔴"
    e1 = "🟢" if h1_trend == "BULLISH" else "🔴"
    sig_ok = "BUY" if h4_trend == "BULLISH" else "SELL"
    return (f"📊 <b>Trend XAUUSD saat ini</b>\n\n"
            f"{e4} <b>H4: {h4_trend}</b> (SMA15 ${h4_sma:,.0f})\n"
            f"   → filter sinyal: hanya <b>{sig_ok}</b> yang lolos\n\n"
            f"{e1} H1: {h1_trend} (SMA20 ${h1_sma:,.0f})\n\n"
            f"💰 Harga: <b>${now_px:,.2f}</b>\n"
            f"[strat v1.1]")

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
    levels (from the journal) + NOW price + Donchian channel.
    Open signals: solid lines. Closed signals: dimmed dashed + outcome label.
    No signals yet: NOW mode (Donchian + current price only).
    Returns (photo_path_or_None, caption_or_error)."""
    try:
        m5 = td_ohlc("5min", 80)
        h1 = td_ohlc("1h", 70)
    except Exception:
        return None, "❌ Gagal ambil data harga, coba lagi sebentar."
    now_ts = int(time.time())
    m5b = now_ts - (now_ts % 300)
    closed5 = [b for b in m5 if b[0] < m5b]
    if len(closed5) < 3:
        return None, "❌ Data M5 kurang."
    sig_bar = closed5[-1]
    hour_start = sig_bar[0] - (sig_bar[0] % 3600)
    h1c = [b for b in h1 if b[0] < hour_start]
    if len(h1c) < 62:
        return None, "❌ Data H1 kurang."
    win = h1c[-48:]
    upper = max(b[2] for b in win)
    lower = min(b[3] for b in win)
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
    du, dl = int(round(upper - cur)), int(round(cur - lower))
    donchian_cap = (f"🔼 Upper ${int(round(upper))} (${du} lagi) | "
                    f"🔽 Lower ${int(round(lower))} (${dl} lagi)\n"
                    f"📏 ATR H1 ${int(round(a1))}")
    def signal_age(iso):
        try:
            dt = datetime.datetime.strptime(
                (iso or "")[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)
            secs = max(0, int(time.time()) - int(dt.timestamp()))
            h, rem = divmod(secs, 3600); m = rem // 60
            return f"{h}j {m}m lalu" if h else f"{m}m lalu"
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
            return None, "❌ Data sinyal rusak."
        is_open = row["status"] == "open"
        try:
            sig_epoch = int(datetime.datetime.strptime(
                row["alert_time_utc"][:19], "%Y-%m-%dT%H:%M:%S"
            ).replace(tzinfo=datetime.timezone.utc).timestamp())
        except Exception:
            sig_epoch = None
        chart_in = {"bars": bars_in, "upper": upper, "lower": lower,
                    "signal": sig, "entry": e,
                    "sl": s_d, "tp1": t1d, "tp2": t2d, "tp3": t3d,
                    "bar_time_wib": wib_s, "out": chart_path,
                    "entry_line": True, "hist": not is_open,
                    "sig_t": sig_epoch}
        sl_px = int(round(e - m * s_d)); tp1_px = int(round(e + m * t1d))
        age = signal_age(row.get("alert_time_utc"))
        age_s = f" ⏳ sinyal {age}" if age else ""
        if is_open:
            pnl = int(round((cur - e) * m))
            cap = (f"📊 <b>{sig} @ ${int(round(e))}</b> — sekarang ${cur} ({pnl:+d}){age_s}\n"
                   f"🛑 SL ${sl_px} | 🎯 TP1 ${tp1_px}\n"
                   f"{donchian_cap}")
        else:
            oc = (row.get("outcome") or "").strip()
            rm = (row.get("r_multiple") or "").strip()
            rtag = ""
            try:
                rtag = f" ({float(rm):+g}R)" if rm else ""
            except ValueError:
                pass
            chart_in["hist_label"] = f"→ {oc}{rtag}" if oc else ""
            cap = (f"📊 <b>Sinyal terakhir: {sig} @ ${int(round(e))}</b> → {oc}{rtag}\n"
                   f"{donchian_cap}")
    else:
        chart_in = {"bars": bars_in, "upper": upper, "lower": lower,
                    "signal": "NOW", "entry": cur,
                    "bar_time_wib": wib_s, "out": chart_path}
        cap = (f"📊 <b>XAUUSD ${cur}</b> ({wib_s} WIB)\n"
               f"{donchian_cap}")
    try:
        tmp_in = chart_path + ".json"
        json.dump(chart_in, open(tmp_in, "w"))
        r = subprocess.run([sys.executable, CHART_PY, tmp_in],
                           capture_output=True, text=True, timeout=60)
        os.remove(tmp_in)
        if not os.path.exists(chart_path):
            return None, "❌ Gagal render chart."
        # keep only the 20 newest now_*.png (entry charts are pruned separately)
        import glob as _glob
        files = sorted(_glob.glob(os.path.join(chart_dir, "now_*.png")),
                       key=os.path.getmtime)
        for old in files[:-20]:
            os.remove(old)
    except Exception:
        return None, "❌ Gagal render chart."
    return chart_path, cap

def handle_callback(data):
    # inline-keyboard taps from alert messages; mirrors the / commands
    _, chat_id = tg_creds()
    if data == "chart":
        photo, cap_or_err = handle_chart()
        if photo:
            tg_send_photo(chat_id, photo, cap_or_err)
        else:
            tg_send(chat_id, cap_or_err)
    elif data == "status":
        tg_send(chat_id, status_text())
    elif data == "pause_1h":
        save_state({"paused_until": int(time.time()) + 3600,
                    "alert_on": True})
        tg_send(chat_id,
                "⏸️ <b>Alert di-pause 1 jam.</b>\n"
                "Sinyal entry berhenti, heartbeat tetap jalan.\n"
                "Kirim /alert_on untuk lanjutkan lebih cepat.")
    elif data == "alert_off":
        save_state({"alert_on": False, "paused_until": 0})
        tg_send(chat_id,
                "🔴 <b>Alert XAUUSD dimatikan.</b>\n"
                "Kirim /alert_on untuk menyalakan lagi.")

def handle(text):
    cmd = text.strip().split()[0].split("@")[0].lower()
    if cmd == "/start":
        return HELP
    if cmd == "/set_modal":
        # /set_modal 600 usc  |  /set_modal 200  (keep currency)  |  /set_modal 50 usd
        parts = text.strip().split()
        if len(parts) < 2:
            st0 = load_state()
            m0 = st0.get("modal") or {"amount": 600, "currency": "usc"}
            u0 = "USC" if (m0.get("currency") or "usc") == "usc" else "USD"
            return (f"💰 Modal saat ini: <b>{m0.get('amount')} {u0}</b>\n"
                    f"Pakai: /set_modal &lt;jumlah&gt; [usd|usc]\n"
                    f"Contoh: /set_modal 600 usc")
        try:
            amount = float(parts[1])
        except ValueError:
            return "❌ Jumlah harus angka. Contoh: /set_modal 600 usc"
        if amount <= 0:
            return "❌ Jumlah harus lebih dari 0."
        st0 = load_state()
        modal = st0.get("modal") or {"amount": 600, "currency": "usc"}
        if len(parts) > 2:
            cur = parts[2].lower()
            if cur not in ("usd", "usc"):
                return "❌ Mata uang cuma: usd atau usc."
            modal["currency"] = cur
        modal["amount"] = int(amount) if amount == int(amount) else round(amount, 2)
        save_state({"modal": modal})
        unit = "USC" if modal["currency"] == "usc" else "USD"
        return (f"✅ <b>Modal diset: {modal['amount']} {unit}</b>\n"
                f"Risiko % di alert & notif sekarang pakai angka ini.\n"
                f"Update lagi via /set_modal tiap deposit/tarik dana.")
    if cmd == "/alert_on":
        save_state({"alert_on": True, "paused_until": 0})
        return ("🟢 <b>Alert XAUUSD dinyalakan.</b>\n"
                "Sinyal BUY/SELL + heartbeat tiap 5 mnt aktif.")
    if cmd == "/alert_off":
        save_state({"alert_on": False})
        return ("🔴 <b>Alert XAUUSD dimatikan.</b>\n"
                "Kirim /alert_on untuk menyalakan lagi.")
    if cmd in ("/alert_status", "/cek"):
        return status_text()
    if cmd == "/riwayat":
        return history_text()
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
            return ("ℹ️ Tidak ada posisi aktif.\n"
                    "Tidak ada yang perlu di-skip/close/cancel.")
        outcome_map = {
            "/skip_trade": ("skipped", "skipped", "0",
                            "Trade di-skip — tidak entry."),
            "/cancel_trade": ("cancelled", "cancelled", "0",
                              "Trade di-cancel — sinyal dianggap invalid."),
        }
        if cmd == "/close_trade":
            parts = text.strip().split()
            o = (parts[1] if len(parts) > 1 else "manual").lower()
            # FIX #3 (2026-10-05): use standard outcome format that
            # /riwayat and scoreboard recognize (not "closed-tp1")
            omap = {"sl": ("closed", "SL", "-1"),
                    "tp1": ("closed", "TP1", "1"),
                    "tp2": ("closed", "TP2", "1.5"),
                    "tp3": ("closed", "TP3", "2"),
                    "be": ("closed", "TP1+BE", "0"),
                    "manual": ("closed", "manual", "0")}
            if o not in omap:
                return ("❌ Outcome harus: sl | tp1 | tp2 | tp3 | be | manual\n"
                        "Contoh: /close_trade tp1")
            _st, _oc, _rm = omap[o]
            outcome_map[cmd] = (_st, _oc, _rm,
                                f"Trade ditutup manual ({o}).")
        status, outcome, rmult, desc = outcome_map[cmd]
        # update journal under lock
        def _lifecycle_update(rows):
            for r in rows:
                if r.get("status") == "open":
                    r["status"] = status
                    r["outcome"] = outcome
                    r["closed_time_utc"] = datetime.datetime.now(
                        datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    r["r_multiple"] = rmult
            return True
        try:
            save_journal_rows(_lifecycle_update)
        except Exception as ex:
            log("xauusd-tg-cmd", f"lifecycle-journal-fail:{str(ex)[:40]}")
        save_state({"active_trade": None})
        sig_txt = f"{at.get('signal')} @ ${at.get('entry')}" if at else \
            f"{len(open_rows)} jurnal open"
        log("xauusd-tg-cmd", f"{cmd}:{sig_txt}")
        return (f"✅ <b>{desc}</b>\n"
                f"Posisi: {sig_txt}\n"
                f"Sistem lanjut memantau sinyal baru.")
    # (removed duplicate /alert_status,/cek,/riwayat handlers — 2026-10-05)
    if cmd == "/reset_trade":
        # Emergency reset: clear a stuck active_trade (e.g. state desync
        # where the journal says open but no position is actually tracked,
        # or a trade that should have resolved but didn't).
        st0 = load_state()
        at = st0.get("active_trade")
        if not at:
            return ("ℹ️ Tidak ada posisi aktif yang perlu di-reset.\n"
                    "Sistem sudah memantau sinyal baru seperti biasa.")
        save_state({"active_trade": None})
        log("xauusd-tg-cmd", f"reset-trade:{at.get('signal')}@{at.get('entry')}")
        return (f"🔄 <b>active_trade di-reset.</b>\n"
                f"Posisi {at.get('signal')} @ ~${at.get('entry')} dihapus dari pantauan.\n"
                f"Sistem kembali memantau sinyal baru.")
    if cmd.startswith("/"):
        return "❓ Perintah tidak dikenal.\n" + HELP
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
    for u in d.get("result", []):
        uid = u.get("update_id", 0)
        max_id = max(max_id, uid + 1)
        # inline-keyboard taps arrive as callback_query
        cq = u.get("callback_query")
        if cq:
            cq_chat = str((cq.get("message") or {}).get("chat", {}).get("id"))
            if cq_chat == CHAT_ID:
                # FIX #7 (2026-10-05): DRY-guard the callback answer —
                # dry runs must not send real Telegram API calls
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
            continue
        cmd = text.split()[0].split("@")[0].lower()
        if cmd == "/chart":
            photo, cap_or_err = handle_chart()
            if photo:
                tg_send_photo(CHAT_ID, photo, cap_or_err)
            else:
                tg_send(CHAT_ID, cap_or_err)
            log("xauusd-tg-cmd", "handled:/chart")
            continue
        reply = handle(text)
        if reply:
            tg_send(CHAT_ID, reply)
            log("xauusd-tg-cmd", f"handled:{text.split()[0]}")
    set_offset(max_id)
    log("xauusd-tg-cmd", "poll-ok")
except Exception as ex:
    log("xauusd-tg-cmd", f"fail:{str(ex)[:80]}")
out("silent", "tg-cmd-poll")
PYEOF
echo "HATCH_HOOK_LOG:{\"message\":\"xauusd-tg-cmd\",\"reason\":\"script-end\"}" >&2
