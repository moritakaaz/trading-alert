#!/bin/bash
# XAUUSD multi-timeframe entry alerts (v2.1 brutal): double top/bottom +
# Donchian(48) H1 second trigger, no trend filter. Parameterized by TF env var
# (m1|m5|m15). SL/TP from H1 ATR(14).
# Price: Twelve Data XAU/USD (fallback Kraken PAXGUSD). News: Finnhub forex headlines.
# Signal per confirmation bar, forex hours only, deduped by signal bar.
TF="${TF:-m5}"
STATE_FILE="$HOME/hooks/state/xauusd_entry_${TF}.json"
TD_CLI="$HOME/workspace/skills/twelve-data/bin/xauusd_ohlc.py"
FN_CLI="$HOME/workspace/skills/finnhub/bin/forex_news.py"
FRED_CLI="$HOME/workspace/skills/fred/bin/release_calendar.py"
mkdir -p "$(dirname "$STATE_FILE")"

python3 - "$STATE_FILE" "$TD_CLI" "$FN_CLI" "$FRED_CLI" <<'PYEOF'
import json, sys, time, subprocess, urllib.request, datetime, re, os

STATE_FILE, TD_CLI, FN_CLI, FRED_CLI = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]

# ---- multi-timeframe config (TF env var: m1|m5|m15, default m5) ----
TF = os.environ.get("TF", "m5").lower()
if TF not in ("m1", "m5", "m15"):
    TF = "m5"
TF_SECS = {"m1": 60, "m5": 300, "m15": 900}[TF]
TF_INTERVAL = {"m1": "1min", "m5": "5min", "m15": "15min"}[TF]
TF_BARS = {"m1": 600, "m5": 300, "m15": 200}[TF]
KRAKEN_INT = {"m1": 1, "m5": 5, "m15": 15}[TF]
HOOK_ID = f"xauusd-entry-{TF}"
TF_UP = TF.upper()

def out(decision, reason, payload=None):
    print("HATCH_HOOK_RESULT:" + json.dumps(
        {"decision": decision, "reason": reason, "payload": payload or {}}))
    sys.exit(0)

def log(msg, reason):
    print("HATCH_HOOK_LOG:" + json.dumps({"message": msg, "reason": reason}),
          file=sys.stderr)

def save_state_keys(updates):
    # Merge `updates` into the state file WITHOUT clobbering keys owned by
    # the command handler (e.g. alert_on). The old code wrote back the whole
    # `st` dict loaded at script start — a /alert_off arriving during the
    # ~20s of API calls would be silently reverted to alert_on=True.
    # Lock is on a SEPARATE .lock file (not the data file itself), because
    # os.replace() swaps the inode — a lock on the old inode wouldn't
    # protect the new file. Atomic write ensures lock-free readers see
    # old OR new, never partial.
    if os.environ.get("HATCH_HOOK_DRY_RUN") == "1":
        return
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
            cur.update(updates)
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
    # Read-modify-write the journal CSV under an exclusive fcntl lock.
    # FIX (2026-10-05): prevents lost updates when the alert script,
    # command handler, and scoreboard write concurrently.
    # Atomic write (tempfile + os.replace) ensures lock-free readers
    # (/history, /chart, self-heal) see old OR new, never partial.
    # update_fn(rows) mutates the list of dicts in place; return False to abort.
    if os.environ.get("HATCH_HOOK_DRY_RUN") == "1":
        return False
    import fcntl, csv, tempfile
    # Use a dedicated lock file so we can hold the lock across read+write
    # even when the journal itself doesn't exist yet.
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
            # ensure strategy_v / timeframe columns exist
            if fieldnames and "strategy_v" not in fieldnames:
                fieldnames = fieldnames + ["strategy_v"]
                for r in rows:
                    r.setdefault("strategy_v", "1.0")
            if fieldnames and "timeframe" not in fieldnames:
                fieldnames = fieldnames + ["timeframe"]
                for r in rows:
                    r.setdefault("timeframe", "m5")
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

def tg_send(text, photo=None, caption=None, silent=False, keyboard=None):
    # push alert to Faqih's Telegram via the dedicated alert bot
    # (@ahsudahlah_bot); silent on any failure, never on dry runs;
    # token never logged.
    # silent=True -> disable_notification: no sound/vibration (for the
    # routine heartbeat, so entry/TP/SL pushes stand out).
    # keyboard: inline keyboard dict for interactive buttons.
    try:
        if os.environ.get("HATCH_HOOK_DRY_RUN") == "1":
            return
        tok, cid = None, None
        with open(os.path.expanduser("~/.tg-alert-bot/.env")) as f:
            for line in f:
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    tok = line.strip().split("=", 1)[1]
                elif line.startswith("TELEGRAM_CHAT_ID="):
                    cid = line.strip().split("=", 1)[1]
        if not tok or not cid:
            return
        base = "https://api.telegram.org/bot" + tok
        def esc(s):
            return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if photo and os.path.isfile(photo):
            subprocess.run(["curl", "-s", "-m", "25",
                            "-F", "chat_id=" + cid,
                            "-F", "photo=@" + photo,
                            "-F", "caption=" + esc(caption or "📊 Chart entry"),
                            "-F", "parse_mode=HTML",
                            base + "/sendPhoto"],
                           capture_output=True, timeout=30)
        cmd = ["curl", "-s", "-m", "25",
               "--data-urlencode", "chat_id=" + cid,
               "--data-urlencode", "text=" + esc(text),
               "--data-urlencode", "parse_mode=HTML"]
        if silent:
            cmd += ["--data-urlencode", "disable_notification=true"]
        if keyboard:
            cmd += ["--data-urlencode",
                    "reply_markup=" + json.dumps(keyboard, separators=(",", ":"))]
        cmd.append(base + "/sendMessage")
        # retry once on failure (transient network/proxy/rate-limit)
        sent = False
        for attempt in range(2):
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=30)
                if b'"ok":true' in (r.stdout or b""):
                    sent = True
                    break
            except Exception:
                pass
            if attempt == 0:
                time.sleep(3)
        if sent:
            log(HOOK_ID, "tg-sent")
        else:
            log(HOOK_ID, "tg-fail:sendMessage-failed-2x")
    except Exception as ex:
        log(HOOK_ID, f"tg-fail:{str(ex)[:60]}")

def tg_edit_or_send(text, state_key, silent=True):
    # v2.4: heartbeat replace method — edit the previous heartbeat message
    # in place instead of spamming new ones. Stores message_id in state.
    # Returns True if sent/edited OK.
    try:
        if os.environ.get("HATCH_HOOK_DRY_RUN") == "1":
            return True
        tok, cid = None, None
        with open(os.path.expanduser("~/.tg-alert-bot/.env")) as f:
            for line in f:
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    tok = line.strip().split("=", 1)[1]
                elif line.startswith("TELEGRAM_CHAT_ID="):
                    cid = line.strip().split("=", 1)[1]
        if not tok or not cid:
            return False
        base = "https://api.telegram.org/bot" + tok
        def esc(s):
            return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        msg_id = st.get(state_key)
        # try editing the previous message
        if msg_id:
            cmd = ["curl", "-s", "-m", "25",
                   "--data-urlencode", "chat_id=" + cid,
                   "--data-urlencode", "message_id=" + str(msg_id),
                   "--data-urlencode", "text=" + esc(text),
                   "--data-urlencode", "parse_mode=HTML",
                   base + "/editMessageText"]
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=30)
                if b'"ok":true' in (r.stdout or b""):
                    log(HOOK_ID, "tg-heartbeat-edited")
                    return True
            except Exception:
                pass
            # edit failed (too old/deleted) — fall through to send new
        cmd = ["curl", "-s", "-m", "25",
               "--data-urlencode", "chat_id=" + cid,
               "--data-urlencode", "text=" + esc(text),
               "--data-urlencode", "parse_mode=HTML"]
        if silent:
            cmd += ["--data-urlencode", "disable_notification=true"]
        cmd.append(base + "/sendMessage")
        for attempt in range(2):
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=30)
                out_b = r.stdout or b""
                if b'"ok":true' in out_b:
                    # extract message_id for next edit
                    try:
                        mid = json.loads(out_b)["result"]["message_id"]
                        save_state_keys({state_key: mid})
                    except Exception:
                        pass
                    log(HOOK_ID, "tg-heartbeat-sent-new")
                    return True
            except Exception:
                pass
            if attempt == 0:
                time.sleep(3)
        log(HOOK_ID, "tg-fail:heartbeat-failed-2x")
        return False
    except Exception as ex:
        log(HOOK_ID, f"tg-fail:heartbeat:{str(ex)[:40]}")
        return False

# inline keyboard for entry alerts: chart / status / pause / off
ALERT_KB = {"inline_keyboard": [
    [{"text": "📈 Chart", "callback_data": "chart"},
     {"text": "✅ Status", "callback_data": "status"}],
    [{"text": "⏸️ Pause 1h", "callback_data": "pause_1h"},
     {"text": "🔴 Turn off", "callback_data": "alert_off"}],
]}

now = int(time.time())
utc = datetime.datetime.fromtimestamp(now, datetime.timezone.utc)
wd, hm = utc.weekday(), utc.hour + utc.minute / 60.0
# forex hours: Sun 22:00 -> Fri 21:00 UTC, skip daily break 21:00-22:00
# NOTE: xauusd_watchdog.py has a duplicate in_forex_hours() — keep in sync.
if wd == 5 or (wd == 6 and hm < 22) or (wd == 4 and hm >= 21) or (21 <= hm < 22):
    log(HOOK_ID, "market-closed"); out("silent", "market-closed")

# master on/off switch (toggled by !alert on/off on WA and /alert_on/off on TG)
try:
    _s0 = json.load(open(STATE_FILE))
except Exception:
    _s0 = {}
if not _s0.get("alert_on", True):
    log(HOOK_ID, "alert-off"); out("silent", "alert-off")

def td_ohlc(interval, n):
    r = subprocess.run([TD_CLI, "--interval", interval, "--outputsize", str(n)],
                       capture_output=True, text=True, timeout=40)
    d = json.loads(r.stdout or "{}")
    if "values" not in d:
        raise RuntimeError(d.get("error", "no values"))
    return [(v["t"], v["o"], v["h"], v["l"], v["c"]) for v in d["values"]]

def kraken(pair, interval, n=720):
    url = f"https://api.kraken.com/0/public/OHLC?pair={pair}&interval={interval}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    d = json.load(urllib.request.urlopen(req, timeout=25))
    if d.get("error"): raise RuntimeError(str(d["error"]))
    key = [k for k in d["result"] if k != "last"][0]
    return [(b[0], float(b[1]), float(b[2]), float(b[3]), float(b[4]))
            for b in d["result"][key]]

src = "Twelve Data XAU/USD"
try:
    tfbars = td_ohlc(TF_INTERVAL, TF_BARS)  # pattern history for this TF
    h1 = td_ohlc("1h", 80)
except Exception as e:
    log(HOOK_ID, f"twelvedata-fail:{str(e)[:80]}")
    try:
        tfbars = kraken("PAXGUSD", KRAKEN_INT); h1 = kraken("PAXGUSD", 60)
        src = "Kraken PAXGUSD (fallback)"
    except Exception as e2:
        log(HOOK_ID, "all-price-fail"); out("silent", "price-fetch-failed")

# last CLOSED bars
tfb = now - (now % TF_SECS)
closed_tf = [b for b in tfbars if b[0] < tfb]
if len(closed_tf) < 3:
    log(HOOK_ID, "not-enough-tf"); out("silent", "not-enough-data")
sig_bar, prev_bar = closed_tf[-1], closed_tf[-2]
bar_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(sig_bar[0]))
if now - sig_bar[0] > TF_SECS * 3:  # stale bar guard
    log(HOOK_ID, "stale-bar"); out("silent", "stale-bar")

# completed H1 bars strictly before the signal bar's hour
hour_start = sig_bar[0] - (sig_bar[0] % 3600)
h1c = [b for b in h1 if b[0] < hour_start]
if len(h1c) < 62:
    log(HOOK_ID, "not-enough-h1"); out("silent", "not-enough-data")

def atr14(bars):
    # ATR(14) over the last 14 completed H1 bars; bars=[(t,o,h,l,c),...] oldest-first
    trs = []
    for k in range(len(bars) - 14, len(bars)):
        h, l, pc = bars[k][2], bars[k][3], bars[k - 1][4]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / len(trs)

def _ema(vals, period):
    _k = 2.0 / (period + 1)
    _e = sum(vals[:period]) / period  # seed: SMA of first `period` closes
    for _v in vals[period:]:
        _e = _v * _k + _e * (1 - _k)
    return _e

a1 = atr14(h1c)
if a1 <= 0:
    log(HOOK_ID, "bad-atr"); out("silent", "bad-atr")

# (v2.1: M15 trend block removed — filter was dropped; H1 EMA kept for display)

# --- v2.1 brutal double top/bottom detector ---
# Pattern: two M5 fractal peaks/valleys (N=2), |p1-p2| <= 0.25*ATR(H1),
# 5-50 bars apart, valley >= 0.5*ATR deep, intervening extreme >=3 bars
# from each side. Confirmation = latest closed M5 bar closing beyond the
# neckline with the right color (touch-only rejected: a wick that closes
# back means the level HELD — firing on it catches traps, not breakouts).
# No lookahead: every bar referenced is closed at signal time.
def rsi_series(closes, period=14):
    # Wilder's RSI; returns list aligned with closes
    n = len(closes)
    out = [50.0] * n
    if n <= period:
        return out
    gains = [0.0] * n
    losses = [0.0] * n
    for i in range(1, n):
        d = closes[i] - closes[i-1]
        gains[i] = d if d > 0 else 0.0
        losses[i] = -d if d < 0 else 0.0
    ag = sum(gains[1:period+1]) / period
    al = sum(losses[1:period+1]) / period
    out[period] = 100.0 if al <= 0 else 100.0 - 100.0 / (1.0 + ag / al)
    for i in range(period+1, n):
        ag = (ag * (period-1) + gains[i]) / period
        al = (al * (period-1) + losses[i]) / period
        out[i] = 100.0 if al <= 0 else 100.0 - 100.0 / (1.0 + ag / al)
    return out

def score_pattern(sig, p1, p2, xn, neck):
    # v2.4: quality score 0-100 (adapted from Neblok's Double Tap).
    # No volume for spot XAUUSD, so rescaled to 100 from 85 max.
    # Peak match 25 + RSI divergence 20 + height 15 + symmetry 10 + prior trend 15.
    H = [b[2] for b in closed_tf]
    L = [b[3] for b in closed_tf]
    C = [b[4] for b in closed_tf]
    if sig == "SELL":
        ext = max(H[p1], H[p2])
        match = max(0.0, 1.0 - abs(H[p2]-H[p1]) / max(0.25*a1, 1e-9))
    else:
        ext = min(L[p1], L[p2])
        match = max(0.0, 1.0 - abs(L[p2]-L[p1]) / max(0.25*a1, 1e-9))
    s1 = 25.0 * match
    r = rsi_series(C)
    rsi_div = (r[p2] < r[p1]) if sig == "SELL" else (r[p2] > r[p1])
    s2 = 20.0 if rsi_div else 0.0
    h = abs(ext - neck)
    s4 = 15.0 * min(1.0, h / max(3.0*a1, 1e-9))
    l1, l2 = xn - p1, p2 - xn
    sym = min(l1, l2) / max(max(l1, l2), 1)
    s5 = 10.0 * sym
    # prior trend: strong move into the pattern (look back 60 bars from p1)
    lo_i = max(0, p1 - 60)
    if sig == "SELL":
        pre = min(L[lo_i:p1+1]) if lo_i < p1 else ext
        prior = max(0.0, ext - pre)
    else:
        pre = max(H[lo_i:p1+1]) if lo_i < p1 else ext
        prior = max(0.0, pre - ext)
    s6 = 15.0 * min(1.0, prior / max(h, 1e-9))
    score = int(round((s1+s2+s4+s5+s6) / 85.0 * 100.0))
    grade = "A" if score >= 75 else ("B" if score >= 55 else "C")
    return score, grade, rsi_div

def detect_dtb():
    n = len(closed_tf)
    if n < 80 or a1 <= 0:
        return None, None
    H = [b[2] for b in closed_tf]
    L = [b[3] for b in closed_tf]
    is_peak = [False] * n
    is_valley = [False] * n
    for i in range(2, n - 2):
        if H[i] > H[i-1] and H[i] > H[i-2] and H[i] > H[i+1] and H[i] > H[i+2]:
            is_peak[i] = True
        if L[i] < L[i-1] and L[i] < L[i-2] and L[i] < L[i+1] and L[i] < L[i+2]:
            is_valley[i] = True
    k = n - 1  # sig_bar: must be the confirmation candle
    so, sc = closed_tf[k][1], closed_tf[k][4]
    # double tops -> SELL
    for p2 in range(max(2, k - 24), k):
        if not is_peak[p2]:
            continue
        # v2.3: p1 = nearest peak that forms a VALID pattern (not just nearest).
        # The old greedy-nearest missed real formations when a small intermediate
        # peak sat between the two true tops.
        p1, vlo, vi = None, None, None
        for q in range(p2 - 5, max(1, p2 - 50), -1):
            if not is_peak[q]:
                continue
            if abs(H[p2] - H[q]) > 0.25 * a1:
                continue
            _seg = L[q + 1:p2]
            if not _seg:
                continue
            _vlo = min(_seg)
            if min(H[q], H[p2]) - _vlo < 0.5 * a1:
                continue
            _vi = q + 1 + _seg.index(_vlo)
            if _vi - q < 3 or p2 - _vi < 3:
                continue
            p1, vlo, vi = q, _vlo, _vi
            break
        if p1 is None:
            continue
        # v2.4 clean check: no higher high between the peaks (else it's not a clean M)
        if max(H[p1+1:p2]) > max(H[p1], H[p2]) + 1e-9:
            continue
        if sc < vlo and sc < so:  # close below neckline + red
            _score, _grade, _rsi_div = score_pattern("SELL", p1, p2, vi, vlo)
            return "SELL", {"kind": "DOUBLE TOP", "p1": H[p1],
                            "p2": H[p2], "neck": vlo,
                            "p2_t": closed_tf[p2][0],
                            "p1_t": closed_tf[p1][0],
                            "neck_t": closed_tf[vi][0],
                            "score": _score, "grade": _grade,
                            "rsi_div": _rsi_div}
    # double bottoms -> BUY
    for p2 in range(max(2, k - 24), k):
        if not is_valley[p2]:
            continue
        # v2.3: p1 = nearest valley that forms a VALID pattern
        p1, vhi, pi = None, None, None
        for q in range(p2 - 5, max(1, p2 - 50), -1):
            if not is_valley[q]:
                continue
            if abs(L[p2] - L[q]) > 0.25 * a1:
                continue
            _seg = H[q + 1:p2]
            if not _seg:
                continue
            _vhi = max(_seg)
            if _vhi - max(L[q], L[p2]) < 0.5 * a1:
                continue
            _pi = q + 1 + _seg.index(_vhi)
            if _pi - q < 3 or p2 - _pi < 3:
                continue
            p1, vhi, pi = q, _vhi, _pi
            break
        if p1 is None:
            continue
        # v2.4 clean check: no lower low between the valleys (else it's not a clean W)
        if min(L[p1+1:p2]) < min(L[p1], L[p2]) - 1e-9:
            continue
        if sc > vhi and sc > so:  # close above neckline + green
            _score, _grade, _rsi_div = score_pattern("BUY", p1, p2, pi, vhi)
            return "BUY", {"kind": "DOUBLE BOTTOM", "p1": L[p1],
                           "p2": L[p2], "neck": vhi,
                           "p2_t": closed_tf[p2][0],
                           "p1_t": closed_tf[p1][0],
                           "neck_t": closed_tf[pi][0],
                           "score": _score, "grade": _grade,
                           "rsi_div": _rsi_div}
    return None, None

# v2.2: setup detector — pattern geometry complete but NO confirmation yet.
# Fires once per pattern as an early "standby" warning before the entry signal.
# Same geometry as detect_dtb; returns the most recent unconfirmed pattern.
# v2.3: uses first-valid p1 (not greedy-nearest).
def detect_setup():
    n = len(closed_tf)
    if n < 80 or a1 <= 0:
        return None, None
    H = [b[2] for b in closed_tf]
    L = [b[3] for b in closed_tf]
    is_peak = [False] * n
    is_valley = [False] * n
    for i in range(2, n - 2):
        if H[i] > H[i-1] and H[i] > H[i-2] and H[i] > H[i+1] and H[i] > H[i+2]:
            is_peak[i] = True
        if L[i] < L[i-1] and L[i] < L[i-2] and L[i] < L[i+1] and L[i] < L[i+2]:
            is_valley[i] = True
    k = n - 1
    so, sc = closed_tf[k][1], closed_tf[k][4]
    best = None  # (p2, sig, pattern) — keep the most recent
    # double tops forming -> potential SELL
    for p2 in range(max(2, k - 24), k):
        if not is_peak[p2]:
            continue
        # v2.3: first-valid p1
        p1, vlo, vi = None, None, None
        for q in range(p2 - 5, max(1, p2 - 50), -1):
            if not is_peak[q]:
                continue
            if abs(H[p2] - H[q]) > 0.25 * a1:
                continue
            _seg = L[q + 1:p2]
            if not _seg:
                continue
            _vlo = min(_seg)
            if min(H[q], H[p2]) - _vlo < 0.5 * a1:
                continue
            _vi = q + 1 + _seg.index(_vlo)
            if _vi - q < 3 or p2 - _vi < 3:
                continue
            p1, vlo, vi = q, _vlo, _vi
            break
        if p1 is None:
            continue
        # v2.4 clean check
        if max(H[p1+1:p2]) > max(H[p1], H[p2]) + 1e-9:
            continue
        if sc < vlo and sc < so:
            continue  # already confirmed -> real signal, not a setup
        # only warn if price is near the neckline (within 0.5xATR) — far away = not actionable
        if sc - vlo > 0.5 * a1:
            continue
        _score, _grade, _rsi_div = score_pattern("SELL", p1, p2, vi, vlo)
        best = (p2, "SELL", {"kind": "DOUBLE TOP", "p1": H[p1],
                             "p2": H[p2], "neck": vlo,
                             "p2_t": closed_tf[p2][0],
                             "p1_t": closed_tf[p1][0],
                             "neck_t": closed_tf[vi][0],
                             "score": _score, "grade": _grade,
                             "rsi_div": _rsi_div})
    # double bottoms forming -> potential BUY
    for p2 in range(max(2, k - 24), k):
        if not is_valley[p2]:
            continue
        # v2.3: first-valid p1
        p1, vhi, pi = None, None, None
        for q in range(p2 - 5, max(1, p2 - 50), -1):
            if not is_valley[q]:
                continue
            if abs(L[p2] - L[q]) > 0.25 * a1:
                continue
            _seg = H[q + 1:p2]
            if not _seg:
                continue
            _vhi = max(_seg)
            if _vhi - max(L[q], L[p2]) < 0.5 * a1:
                continue
            _pi = q + 1 + _seg.index(_vhi)
            if _pi - q < 3 or p2 - _pi < 3:
                continue
            p1, vhi, pi = q, _vhi, _pi
            break
        if p1 is None:
            continue
        # v2.4 clean check
        if min(L[p1+1:p2]) < min(L[p1], L[p2]) - 1e-9:
            continue
        if sc > vhi and sc > so:
            continue  # already confirmed -> real signal, not a setup
        if vhi - sc > 0.5 * a1:
            continue
        if best is None or p2 > best[0]:
            _score, _grade, _rsi_div = score_pattern("BUY", p1, p2, pi, vhi)
            best = (p2, "BUY", {"kind": "DOUBLE BOTTOM", "p1": L[p1],
                                "p2": L[p2], "neck": vhi,
                                "p2_t": closed_tf[p2][0],
                                "p1_t": closed_tf[p1][0],
                                "neck_t": closed_tf[pi][0],
                                "score": _score, "grade": _grade,
                                "rsi_div": _rsi_div})
    if best:
        return best[1], best[2]
    return None, None

sig, pattern = detect_dtb()

# v2.1 brutal: Donchian(48) H1 second trigger (NO EMA filter).
# v2.1 brutal: double top/bottom takes priority; Donchian only if no pattern.
# Channel = prior 48 completed H1 bars; trigger = M5 close beyond the band.
if not sig and len(h1c) >= 48:
    _d_up = max(b[2] for b in h1c[-48:])
    _d_dn = min(b[3] for b in h1c[-48:])
    if sig_bar[4] > _d_up:
        sig, pattern = "BUY", {"kind": "DONCHIAN BREAKOUT", "neck": _d_up,
                               "upper": _d_up, "lower": _d_dn,
                               "p2_t": bar_iso}
    elif sig_bar[4] < _d_dn:
        sig, pattern = "SELL", {"kind": "DONCHIAN BREAKOUT", "neck": _d_dn,
                                "upper": _d_up, "lower": _d_dn,
                                "p2_t": bar_iso}

# EMA20/50 H1 trend (v2.1: display only, filter removed).
ema_trend = None
try:
    _closes = [b[4] for b in h1c]
    _d = _ema(_closes, 20) - _ema(_closes, 50)
    ema_trend = "BULLISH" if _d > 0 else ("BEARISH" if _d < 0 else None)
except Exception as ex:
    log(HOOK_ID, f"ema-filter-fail:{str(ex)[:40]}")

try:
    st = json.load(open(STATE_FILE))
except Exception:
    st = {}
WIB = datetime.timezone(datetime.timedelta(hours=7))

def heartbeat_maybe(reason):
    # liveness ping while alerts are ON — every 5 min, but using REPLACE method:
    # edits the previous Telegram heartbeat message in place (no spam).
    # WhatsApp side chat gets nothing (silent) — use /alert_status to check.
    # (2026-10-08: user found every-5-min new messages too spammy.)
    if now - st.get("last_heartbeat", 0) < 300:
        log(HOOK_ID, reason); out("silent", reason)
    try:
        day = datetime.datetime.fromtimestamp(now, datetime.timezone.utc).strftime("%Y-%m-%d")
        n = 0
        with open(os.path.expanduser(f"~/hooks/logs/{HOOK_ID}.jsonl")) as f:
            for line in f:
                try:
                    ts = json.loads(line).get("started_at_ms", 0) / 1000
                    if datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%d") == day:
                        n += 1
                except Exception:
                    pass
    except Exception:
        n = 0
    wib_now = datetime.datetime.fromtimestamp(now, WIB).strftime("%H:%M")
    save_state_keys({"last_heartbeat": now})
    # show active-trade info so he knows why no new signals are coming
    # FIX (2026-10-05): resolve_active_trade is called here AND at line ~473.
    # If it just closed a trade (SL/TP1 notification already sent), skip the
    # heartbeat — the user doesn't need two messages for one event.
    active, closed_kind = resolve_active_trade()
    resolve_runner()  # v1.3: post-TP1 runner watch (TP2/TP3/BE alerts)
    if closed_kind in ("SL", "TP1", "expired"):
        log(HOOK_ID, f"heartbeat-skipped-after-{closed_kind.lower()}")
        out("silent", f"trade-closed-{closed_kind.lower()}-notified")
    at = st.get("active_trade")
    extra = ""
    if st.get("paused_until", 0) > now:
        mins = int((st["paused_until"] - now) / 60)
        extra = f"\n⏸️ Pause active (~{mins} min left) — /alert_on to resume"
    elif at:
        # v2.4: count open journal entries for multi-position display
        try:
            import csv as _csv
            jpath = os.path.expanduser("~/hooks/state/entry_journal.csv")
            with open(jpath) as jf:
                _n_open = sum(1 for r in _csv.DictReader(jf)
                             if r and r.get("status") == "open"
                             and r.get("timeframe") == TF)
        except Exception:
            _n_open = 1
        tp1_px = round(at["entry"] + at["tp1_d"] * (1 if at["signal"] == "BUY" else -1), 2)
        if _n_open > 1:
            extra = f"\n📌 {_n_open}x positions open (latest: {at['signal']} @ ~${at['entry']})"
        else:
            extra = f"\n📌 Position {at['signal']} @ ~${at['entry']} still running (TP1 ${tp1_px})"
    elif st.get("runner"):
        _rn = st["runner"]
        _mult = 1 if _rn["signal"] == "BUY" else -1
        _tp2 = int(round(_rn["entry"] + _mult * _rn["tp2_d"]))
        extra = f"\n📌 Runner {_rn['signal']} @ ~${_rn['entry']} running (TP2 ${_tp2})"
    elif closed_kind in ("SL", "TP1"):
        extra = (f"\n{'🛑 SL' if closed_kind == 'SL' else '🎯 TP1'} hit — "
                 f"position closed, ready for new signals")
    _off_cmd = "/alert_off" if TF == "m5" else f"/alert_off_{TF}"
    msg = (f"🟢 Entry alert ACTIVE ({TF_UP}) — {n}x checks today, no BUY/SELL signal yet\n"
           f"(last check {wib_now} WIB). Type {_off_cmd} to stop.{extra}")
    log(HOOK_ID, "heartbeat")
    # v2.4 replace method: edit previous TG heartbeat in place; WA gets nothing
    tg_edit_or_send(msg, "heartbeat_msg_id", silent=True)
    out("silent", "heartbeat")

def resolve_active_trade():
    # One position at a time: while the previous signal's trade is still
    # running (no SL hit, no TP1 touch, <48h), suppress new signals.
    # Returns (active: bool, closed_kind: str|None). On SL/TP1 a Telegram
    # notification is pushed exactly once (the trade is cleared, so the
    # next poll won't re-notify).
    at = st.get("active_trade")
    if not at:
        # self-heal (2026-10-05): the journal is the source of truth for
        # signals. If state lost active_trade (desync), reconstruct it from
        # the most recent open journal entry so the SL/TP monitor isn't blind.
        try:
            import csv as _csv
            jpath = os.path.expanduser("~/hooks/state/entry_journal.csv")
            with open(jpath) as jf:
                # guard against None rows from partial writes
                rows = [r for r in _csv.DictReader(jf)
                        if r and r.get("status") == "open"]
            if rows:
                last = rows[-1]
                bar_ts = int(datetime.datetime.fromisoformat(
                    last["alert_time_utc"].replace("Z", "+00:00")).timestamp())
                at = {"signal": last["signal"],
                      "entry": float(last["entry_ref"]),
                      "sl_d": float(last["sl_d"]),
                      "tp1_d": float(last["tp1_d"]),
                      "tp2_d": float(last["tp2_d"]),
                      "tp3_d": float(last["tp3_d"]),
                      "bar_ts": bar_ts, "ts": bar_ts}
                st["active_trade"] = at
                save_state_keys({"active_trade": at})
                log(HOOK_ID, "active-trade-healed-from-journal")
        except Exception as ex:
            log(HOOK_ID, f"heal-fail:{str(ex)[:40]}")
    if not at:
        return False, None
    if now - at.get("ts", 0) > 172800:  # 48h expiry, same as scoreboard
        st["active_trade"] = None
        save_state_keys({"active_trade": None})
        log(HOOK_ID, "active-trade-expired")
        # also close the journal so self-heal doesn't resurrect it.
        # FIX #2: calculate actual R from last close, not hardcoded 0.
        def _expire_update(rows):
            _bar_iso = datetime.datetime.fromtimestamp(
                at.get("bar_ts", 0), datetime.timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ")
            for _r in rows:
                if _r.get("status") == "open" and \
                   _r.get("alert_time_utc") == _bar_iso:
                    _r["status"] = "expired"
                    _r["outcome"] = "expired"
                    _r["closed_time_utc"] = datetime.datetime.fromtimestamp(
                        now, datetime.timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%SZ")
                    # actual R from last available close
                    try:
                        _last = tfbars[-1][4] if tfbars else at["entry"]
                        _m = 1 if at["signal"] == "BUY" else -1
                        _pnl = (_last - at["entry"]) * _m
                        _r["r_multiple"] = str(round(_pnl / at["sl_d"], 2))
                    except Exception:
                        _r["r_multiple"] = "0"
                    break
            return True
        try:
            save_journal_rows(_expire_update)
        except Exception as _ex:
            log(HOOK_ID, f"journal-expire-fail:{str(_ex)[:40]}")
        return False, "expired"
    bars = [b for b in tfbars if b[0] > at["bar_ts"]]
    if not bars:
        return True, None
    entry, sl_d, tp1_d = at["entry"], at["sl_d"], at["tp1_d"]
    close_kind = None
    for b in bars:
        if at["signal"] == "BUY":
            if b[3] <= entry - sl_d:
                close_kind = "SL"; break
            if b[2] >= entry + tp1_d:
                close_kind = "TP1"; break
        else:
            if b[2] >= entry + sl_d:
                close_kind = "SL"; break
            if b[3] <= entry - tp1_d:
                close_kind = "TP1"; break
    if close_kind:
        st["active_trade"] = None
        save_state_keys({"active_trade": None})
        log(HOOK_ID, f"active-trade-closed:{close_kind.lower()}")
        # FIX #1 (2026-10-05): close the journal entry NOW under lock, not
        # just in the daily scoreboard. Otherwise self-heal resurrects the
        # trade from the still-open journal row and re-sends the
        # SL/TP1 notification every poll.
        def _close_update(rows):
            _bar_iso = datetime.datetime.fromtimestamp(
                at.get("bar_ts", 0), datetime.timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ")
            for _r in rows:
                if _r.get("status") == "open" and \
                   _r.get("alert_time_utc") == _bar_iso:
                    _r["status"] = "closed"
                    _r["outcome"] = close_kind
                    if close_kind == "TP1":
                        _r["max_tp"] = "TP1"
                    _r["closed_time_utc"] = datetime.datetime.fromtimestamp(
                        now, datetime.timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%SZ")
                    _r["r_multiple"] = "-1" if close_kind == "SL" else "1"
                    break
            return True
        try:
            save_journal_rows(_close_update)
        except Exception as _ex:
            log(HOOK_ID, f"journal-close-fail:{str(_ex)[:40]}")
        mult = 1 if at["signal"] == "BUY" else -1
        _m = st.get("modal") or {"amount": 600, "currency": "usc"}
        _ma = float(_m.get("amount") or 600)
        _mu = "USC" if (_m.get("currency") or "usc") == "usc" else "USD"
        # daily circuit breaker (anti-revenge): count consecutive SLs per UTC day.
        # Warning only — never auto-pauses alerts (needs his explicit OK).
        _day = datetime.datetime.fromtimestamp(now, datetime.timezone.utc).strftime("%Y-%m-%d")
        _cb = st.get("circuit") or {}
        if _cb.get("day") != _day:
            _cb = {"day": _day, "consec_sl": 0}
        if close_kind == "SL":
            _cb["consec_sl"] = _cb.get("consec_sl", 0) + 1
        else:
            _cb["consec_sl"] = 0
        save_state_keys({"circuit": _cb})
        if close_kind == "SL":
            px = int(round(entry - mult * sl_d))
            pct = (sl_d / _ma * 100) if _ma > 0 else 0
            cmsg = (f"🛑 SL HIT — {at['signal']} @ ${entry}\n"
                    f"💸 -{sl_d} {_mu} (-1R, -{pct:.1f}% of balance) @ ${px}")
            if _cb["consec_sl"] >= 2:
                cmsg += (f"\n\n⚠️ CIRCUIT BREAKER: {_cb['consec_sl']}x consecutive SL today.\n"
                         f"Market is choppy / you may be on tilt. "
                         f"Consider taking a break — /alert_off if needed.")
        else:
            px = int(round(entry + mult * tp1_d))
            pct = (tp1_d / _ma * 100) if _ma > 0 else 0
            cmsg = (f"🎯 TP1 HIT — {at['signal']} @ ${entry}\n"
                    f"💰 +{tp1_d} {_mu} (+1R, +{pct:.1f}% of balance) @ ${px}\n"
                    f"📌 Move SL to breakeven, runner still going")
        tg_send(cmsg)
        if close_kind == "TP1":
            # v1.3 runner tracking (2026-10-07, user-approved): after TP1,
            # keep watching TP2/TP3 touches and breakeven retest. Each event
            # notifies exactly once. Informational only — never suppresses
            # new signals, never changes the journal outcome (+1R stands).
            st["runner"] = {"signal": at["signal"], "entry": entry,
                            "tp2_d": at["tp2_d"], "tp3_d": at["tp3_d"],
                            "tp1_ts": now, "bar_ts": at.get("bar_ts", 0),
                            "sig_ts": at.get("ts", 0), "notified": ["TP1"]}
            save_state_keys({"runner": st["runner"]})
            log(HOOK_ID, "runner-tracking-started")
        return False, close_kind
    return True, None

def resolve_runner():
    # v1.3 runner tracking: post-TP1 watch for TP2/TP3 touches and breakeven
    # retest on M5 bars. Each event notifies exactly once via Telegram, then
    # TP3/BE (or 48h expiry) clears the runner. Never blocks new signals.
    rn = st.get("runner")
    if not rn:
        return False
    if now - rn.get("sig_ts", 0) > 172800:  # 48h expiry from original signal
        st["runner"] = None
        save_state_keys({"runner": None})
        log(HOOK_ID, "runner-expired")
        return False
    bars = [b for b in tfbars if b[0] > rn["tp1_ts"]]
    if not bars:
        return True
    sig, entry = rn["signal"], rn["entry"]
    notified = rn.get("notified", [])
    mult = 1 if sig == "BUY" else -1
    tp2_px = entry + mult * rn["tp2_d"]
    tp3_px = entry + mult * rn["tp3_d"]
    hit = None
    for b in bars:
        if sig == "BUY":
            be_hit = b[3] <= entry
            t2_hit = b[2] >= tp2_px
            t3_hit = b[2] >= tp3_px
        else:
            be_hit = b[2] >= entry
            t2_hit = b[3] <= tp2_px
            t3_hit = b[3] <= tp3_px
        # conservative priority (same spirit as SL-first): breakeven first,
        # then TP3 (implies TP2), then TP2.
        if be_hit and "BE" not in notified:
            hit = "BE"; break
        if t3_hit and "TP3" not in notified:
            hit = "TP3"; break
        if t2_hit and "TP2" not in notified:
            hit = "TP2"; break
    if not hit:
        return True
    _m = st.get("modal") or {"amount": 600, "currency": "usc"}
    _ma = float(_m.get("amount") or 600)
    _mu = "USC" if (_m.get("currency") or "usc") == "usc" else "USD"
    if hit == "TP2":
        px = int(round(tp2_px))
        pct = (rn["tp2_d"] / _ma * 100) if _ma > 0 else 0
        tg_send(f"🎯 TP2 HIT — {sig} @ ${entry}\n"
                f"💰 +{rn['tp2_d']} {_mu} (+1.5R, +{pct:.1f}% of balance) @ ${px}\n"
                f"📌 Runner still going to TP3")
        notified = notified + ["TP2"]
        log(HOOK_ID, "runner-tp2")
    elif hit == "TP3":
        px = int(round(tp3_px))
        pct = (rn["tp3_d"] / _ma * 100) if _ma > 0 else 0
        tg_send(f"🎯 TP3 HIT — {sig} @ ${entry}\n"
                f"💰 +{rn['tp3_d']} {_mu} (+2R, +{pct:.1f}% of balance) @ ${px}\n"
                f"✅ Runner done — consider closing the position")
        notified = list(set(notified + ["TP2", "TP3"]))
        log(HOOK_ID, "runner-tp3")
    else:  # BE
        tg_send(f"🛑 Runner hit breakeven — {sig} @ ${entry}\n"
                f"💸 0R on the runner (TP1 +1R already locked in)")
        notified = notified + ["BE"]
        log(HOOK_ID, "runner-breakeven")
    if hit in ("TP2", "TP3"):
        # journal max_tp upgrade (informational; scoreboard recomputes anyway)
        def _runner_update(rows):
            _bar_iso = datetime.datetime.fromtimestamp(
                rn.get("bar_ts", 0), datetime.timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ")
            _order = {"": 0, "TP1": 1, "TP2": 2, "TP3": 3}
            for _r in rows:
                if _r.get("alert_time_utc") == _bar_iso:
                    if _order.get(hit, 0) > _order.get(_r.get("max_tp") or "", 0):
                        _r["max_tp"] = hit
                    break
            return True
        try:
            save_journal_rows(_runner_update)
        except Exception as _ex:
            log(HOOK_ID, f"journal-runner-fail:{str(_ex)[:40]}")
    done = hit in ("TP3", "BE")
    st["runner"] = None if done else dict(rn, notified=notified)
    save_state_keys({"runner": st["runner"]})
    return not done

if sig is None:
    # v2.2: setup watch — pattern forming but not confirmed yet.
    # Early "standby" alert so he can prepare before the entry signal.
    # v2.4: no suppression for active trades (multi-position mode).
    _setup_sig, _setup_pat = detect_setup()
    _paused = st.get("paused_until", 0) > now
    if (_setup_sig and not _paused
            and st.get("setup_p2_t") != _setup_pat.get("p2_t")):
        try:
            _neck = int(round(_setup_pat["neck"]))
            _cur = int(round(sig_bar[4]))
            _dist = abs(_cur - _neck)
            _dir_emoji = "🟢" if _setup_sig == "BUY" else "🔴"
            _wib = datetime.datetime.fromtimestamp(
                sig_bar[0], datetime.timezone.utc).astimezone(WIB).strftime("%d %b %H:%M")
            _setup_msg = (
                f"⚠️ SETUP WATCH ({TF_UP}): potential {_setup_sig} forming\n"
                f"📐 Pattern: {_setup_pat['kind']} (neckline ${_neck})"
                f" · ⭐ Grade {_setup_pat.get('grade','?')} ({_setup_pat.get('score','?')}/100)\n"
                f"💰 Current: ${_cur} (${_dist} from neckline)\n"
                f"👀 Standby — NOT an entry signal.\n"
                f"{'Entry triggers if a candle closes above' if _setup_sig == 'BUY' else 'Entry triggers if a candle closes below'} ${_neck}.\n"
                f"\n🕐 {_wib} WIB [setup v2.4]"
            )
            # chart of the forming pattern
            _chart_dir = os.path.expanduser("~/workspace/trading-ea/charts")
            os.makedirs(_chart_dir, exist_ok=True)
            _chart_path = os.path.join(_chart_dir, f"setup_{bar_iso}.png")
            _chart_in = {
                "bars": [{"t": b[0], "o": b[1], "h": b[2], "l": b[3], "c": b[4]}
                         for b in closed_tf],
                "pattern": {k: _setup_pat[k] for k in
                            ("kind", "p1", "p2", "neck", "p1_t", "neck_t", "p2_t")
                            if k in _setup_pat},
                "signal": _setup_sig, "entry": _cur,
                "sl": 0, "tp1": 0, "tp2": 0, "tp3": 0,
                "bar_time_wib": _wib, "out": _chart_path,
                "setup_mode": True,
            }
            _tmp_in = _chart_path + ".json"
            json.dump(_chart_in, open(_tmp_in, "w"))
            _r = subprocess.run(
                [sys.executable, os.path.expanduser("~/hooks/scripts/make_chart.py"),
                 _tmp_in], capture_output=True, text=True, timeout=60)
            os.remove(_tmp_in)
            _chart_url = None
            if os.path.exists(_chart_path):
                _chart_url = ("sandbox://workspace/trading-ea/charts/"
                              + os.path.basename(_chart_path))
            tg_send(_setup_msg, silent=False,
                    photo=_chart_path if os.path.exists(_chart_path) else None)
            save_state_keys({"setup_p2_t": _setup_pat.get("p2_t")})
            log(HOOK_ID, f"wake-setup-{_setup_sig.lower()}")
            out("wake", f"xauusd-setup-{_setup_sig.lower()}-{TF}",
                {"message": _setup_msg,
                 "chart": _chart_url} if _chart_url else {"message": _setup_msg})
        except Exception as _ex:
            log(HOOK_ID, f"setup-fail:{str(_ex)[:60]}")
            heartbeat_maybe("no-signal")
    else:
        heartbeat_maybe("no-signal")

if st.get("last_bar") == bar_iso:
    log(HOOK_ID, "dup"); out("silent", "already-alerted")

# v2.1: one signal per pattern (same as the backtest's used_p2 dedupe).
# Without this, every bar closing beyond the neckline re-triggers.
if pattern and st.get("pattern_p2_t") == pattern.get("p2_t"):
    log(HOOK_ID, "dup-pattern"); out("silent", "already-alerted-pattern")

# pause check (inline keyboard "⏸️ Pause 1h"): suppress signals but not
# the heartbeat, so he still sees liveness while paused
if st.get("paused_until", 0) > now:
    heartbeat_maybe("paused")
    log(HOOK_ID, "signal-paused")

# v2.1 brutal: trend filter REMOVED — every signal fires, both directions.
# (ema_trend is still computed above; shown in the alert intel
# block for context only, never blocking.)

# one position at a time: suppress new signals while the previous trade is
# still active (no SL hit, no TP1 touch, <48h)
active, _closed = resolve_active_trade()
resolve_runner()  # v1.3: post-TP1 runner watch (TP2/TP3/BE alerts)
# v2.4: multi-position — NO suppression. New signals fire even with active trades.
# The bot tracks the LATEST signal for SL/TP notifications; the journal records all.
# (User requested 2026-10-08: "buat agar muncul signal lagi")

sl_d = int(round(1.5 * a1))
tp1_d = int(round(1.5 * a1))   # 1R
tp2_d = int(round(2.25 * a1))  # 1.5R
tp3_d = int(round(3.0 * a1))   # 2R runner (research-validated full TP)
price = int(round(sig_bar[4]))  # entry reference = signal bar close, whole numbers only (TradingView-friendly)
# --- modal & risk (set via /set_balance; default 600 USC = HFM Cent account) ---
# $1 gold move at 0.01 lot = 1 USC (cent) or $1 (USD) -> sl_d IS the risk
# in account units at min lot; only the label differs by currency.
_modal = st.get("modal") or {"amount": 600, "currency": "usc"}
m_amount = float(_modal.get("amount") or 600)
m_unit = "USC" if (_modal.get("currency") or "usc") == "usc" else "USD"
# v2.4: user-configurable risk % limit and lot size (via /set_risk, /set_lot)
# Stored in M5 state (global); M1/M15 read from there.
def _global_setting(key, default):
    v = st.get(key)
    if v is not None:
        return v
    try:
        with open(os.path.expanduser("~/hooks/state/xauusd_entry_m5.json")) as _f:
            _gs = json.load(_f)
            return _gs.get(key, default)
    except Exception:
        return default
_risk_limit = float(_global_setting("risk_pct_limit", 2.0))
_lot_size = float(_global_setting("lot_size", 0.01))
# risk scales with lot: at 0.01 lot, $1 = 1 unit; at 0.02 lot, $1 = 2 units, etc.
_lot_mult = _lot_size / 0.01
risk_usc = sl_d * _lot_mult
risk_pct = (risk_usc / m_amount * 100) if m_amount > 0 else 0
# lot size for ~risk_limit% risk, rounded DOWN to 0.01 step, floored at min lot
import math as _math
_lot_raw = (m_amount * (_risk_limit / 100) / sl_d) * 0.01 if sl_d > 0 else 0.01
lot_suggest = max(0.01, _math.floor(_lot_raw * 100) / 100)
lot_risk_pct = (sl_d * (lot_suggest / 0.01) / m_amount * 100) if m_amount > 0 else 0

# --- economic calendar (FRED, cached daily) ---
cal_lines = []
try:
    CAL_FILE = os.path.expanduser("~/hooks/state/fred_calendar.json")
    today_utc = datetime.datetime.fromtimestamp(now, datetime.timezone.utc).date()
    today_iso = today_utc.isoformat()
    try:
        cal = json.load(open(CAL_FILE))
    except Exception:
        cal = {}
    if cal.get("date") != today_iso:
        r = subprocess.run([FRED_CLI, "--days", "14"], capture_output=True,
                           text=True, timeout=60)
        d = json.loads(r.stdout or "{}")
        if "events" not in d:
            raise RuntimeError(d.get("error", "no events"))
        cal = {"date": today_iso, "events": d["events"]}
        json.dump(cal, open(CAL_FILE, "w"))
    def et_offset(d):
        def nth_sunday(y, m, n):
            dt = datetime.date(y, m, 1)
            return dt + datetime.timedelta(days=(6 - dt.weekday()) % 7 + 7 * (n - 1))
        return -4 if nth_sunday(d.year, 3, 2) <= d < nth_sunday(d.year, 11, 1) else -5
    for e in cal.get("events", []):
        ed = datetime.date.fromisoformat(e["date"])
        rel = datetime.datetime(ed.year, ed.month, ed.day, 8, 30,
              tzinfo=datetime.timezone(datetime.timedelta(hours=et_offset(ed))))
        rel_utc = int(rel.timestamp())
        wib_s = rel.astimezone(WIB).strftime("%H:%M")
        dmin = (rel_utc - now) / 60
        if abs(dmin) <= 30:
            when = f"{int(abs(dmin))} min away" if dmin > 0 else f"just released {int(abs(dmin))} min ago"
            cal_lines.append(f"⚠️ {e['name']} {when} ({wib_s} WIB) — avoid entries for now")
        elif e["date"] == today_iso:
            cal_lines.append(f"📅 Today: {e['name']} {wib_s} WIB")
    future = [e for e in cal.get("events", []) if e["date"] > today_iso]
    if future and not cal_lines:
        cal_lines.append(f"📅 Next: {future[0]['name']} {future[0]['date']}")
except Exception as ex:
    log(HOOK_ID, f"cal-fail:{str(ex)[:60]}")

# --- news (Finnhub, best effort) ---
headlines, warn = [], False
try:
    r = subprocess.run([FN_CLI, "--limit", "8"], capture_output=True,
                       text=True, timeout=40)
    d = json.loads(r.stdout or "{}")
    items = [n for n in d.get("news", []) if n.get("t") and now - n["t"] < 12 * 3600]
    kw = re.compile(r"gold|xau|fed|fomc|powell|dollar|nfp|non-?farm|cpi|inflation|rate", re.I)
    hot = re.compile(r"nfp|non-?farm payroll|cpi|fomc|rate decision|powell", re.I)
    ranked = sorted(items, key=lambda n: (not kw.search(n.get("headline", "") or ""), -(n["t"] or 0)))
    for n in ranked[:2]:
        hl = (n.get("headline") or "").strip()
        if hl:
            headlines.append(hl)
            if hot.search(hl):
                warn = True
except Exception as e:
    log(HOOK_ID, f"news-fail:{str(e)[:60]}")

# --- trading intelligence (informational only, NOT backtested) ---
# These add context to the alert; they never block or change the signal.
intel_lines = []
try:
    wib_dt = datetime.datetime.fromtimestamp(now, WIB)
    wib_hm = wib_dt.hour + wib_dt.minute / 60.0
    # sessions (approx WIB): Asia 06-14, London 14-20:30, NY 20:30-04
    if 14 <= wib_hm < 20.5:
        session = "London"
    elif wib_hm >= 20.5 or wib_hm < 4:
        session = "New York"
    elif 6 <= wib_hm < 14:
        session = "Asia"
    else:
        session = "Off-hours"
    intel_lines.append(f"⏰ Session: {session}")
    # high-volatility windows: London/NY open ±45m
    if (13.25 <= wib_hm < 14.75) or (19.75 <= wib_hm < 21.25):
        intel_lines.append("⚠️ High volatility (session open) — watch for widening spreads & false breakouts")
    # abnormal signal bar: M5 range > 1.5x H1 ATR is extreme
    if (sig_bar[2] - sig_bar[3]) > 1.5 * a1:
        intel_lines.append("⚠️ Abnormal signal candle (range > 1.5x H1 ATR) — consider wait & see")
except Exception as ex:
    log(HOOK_ID, f"intel-session-fail:{str(ex)[:40]}")

# v2.1: H1 EMA20/50 shown for context only (filter removed).
if ema_trend:
    intel_lines.append(f"📊 H1 EMA20/50: {ema_trend}")

# retest zone: the pattern neckline (natural retest area for the breakout)
try:
    neck_px = int(round(pattern["neck"])) if pattern else None
    if neck_px:
        intel_lines.append(f"💡 Retest zone (neckline): ${neck_px}")
except Exception:
    pass

# price levels (must be defined BEFORE the psych-levels block below)
dir_emoji = "🟢" if sig == "BUY" else "🔴"
mult = 1 if sig == "BUY" else -1
sl_px = price + mult * -sl_d
tp1_px = price + mult * tp1_d
tp2_px = price + mult * tp2_d
tp3_px = price + mult * tp3_d

# psychological & daily levels: warn if SL/TP near round numbers or YHI/YLO
try:
    sig_date = datetime.datetime.fromtimestamp(sig_bar[0], datetime.timezone.utc).date()
    yest_iso = (sig_date - datetime.timedelta(days=1)).isoformat()
    yest_bars = [b for b in h1
                 if datetime.datetime.fromtimestamp(b[0], datetime.timezone.utc).date().isoformat() == yest_iso]
    yhi = max(b[2] for b in yest_bars) if yest_bars else None
    ylo = min(b[3] for b in yest_bars) if yest_bars else None
    def _near(px, tol=2.0):
        hits = []
        seen = set()
        for base in (10, 5):
            # _math.floor(x+0.5) instead of round() — avoids Python 3
            # banker's rounding (round(200.5)==200) missing $200 levels
            r = _math.floor(px / base + 0.5) * base
            if abs(px - r) <= tol and r not in seen:
                seen.add(r)
                hits.append(f"${r:.0f}")
        if yhi and abs(px - yhi) <= tol:
            hits.append(f"YHI ${yhi:.0f}")
        if ylo and abs(px - ylo) <= tol:
            hits.append(f"YLO ${ylo:.0f}")
        return hits
    lvl_warn = []
    for name, px in (("SL", sl_px), ("TP1", tp1_px), ("TP2", tp2_px), ("TP3", tp3_px)):
        hits = _near(px)
        if hits:
            lvl_warn.append(f"{name} near {', '.join(hits)}")
    if lvl_warn:
        intel_lines.append("⚠️ Level: " + " | ".join(lvl_warn))
except Exception as ex:
    log(HOOK_ID, f"intel-lvl-fail:{str(ex)[:40]}")

lines = [f"🚨 ENTRY XAUUSD ({TF_UP}): {dir_emoji} {sig}",
         f"📐 Pattern: {pattern['kind']}" +
         (" + neckline break" if pattern['kind'] in ("DOUBLE TOP", "DOUBLE BOTTOM")
          else " (H1 channel)") +
         (f" · ⭐ Grade {pattern.get('grade','?')} ({pattern.get('score','?')}/100)"
          if pattern.get('grade') else ""),
         "",
         f"🎯 Entry: ${price}",
         f"🛑 SL: ${sl_px} (${sl_d} from entry)",
         f"🎯 TP1: ${tp1_px} (${tp1_d} from entry, 1R) → move SL to breakeven",
         f"🎯 TP2: ${tp2_px} (${tp2_d} from entry, 1.5R)",
         f"🎯 TP3: ${tp3_px} (${tp3_d} from entry, 2R runner)",
         ""]
# v2.4: warn if there's already an active position (multi-position mode)
if active:
    _at = st.get("active_trade") or {}
    _at_sig = _at.get("signal", "?")
    _at_entry = _at.get("entry", "?")
    lines.append(f"⚠️ Already have {_at_sig} @ ${_at_entry} running — "
                 f"this is a NEW signal. Total risk adds up!")
    lines.append("")
# trading intelligence (context only — signal logic unchanged)
lines.extend(intel_lines)
lines.append("")
lines.extend([f"⚖️ Risk @{_lot_size} lot: ~{risk_usc:.0f} {m_unit} ({risk_pct:.1f}% of balance)",
         f"💡 Lot for ~{_risk_limit}% risk: {lot_suggest:.2f} (risk {lot_risk_pct:.1f}%)"])
# hard warning (not a block) when risk exceeds user's limit
if risk_pct > _risk_limit:
    lines.append(f"⚠️ RISK {risk_pct:.1f}% OF BALANCE (>{_risk_limit}%) — consider skipping this signal")
lines.extend([
         f"Levels from ref price ({src}) — may differ slightly vs your broker, adjust",
         ""])
# fallback transparency: Kraken PAXGUSD is a proxy, not XAU/USD directly
if "fallback" in src.lower():
    lines.append("⚠️ [FALLBACK] Price from Kraken PAXGUSD, not XAU/USD directly")
    log(HOOK_ID, "alert-on-fallback-feed")
lines.extend(cal_lines)
if warn:
    lines.append("\u26A0\uFE0F Headline mentions a high-impact event (NFP/CPI/FOMC) — watch out for volatility")
for hl in headlines:
    lines.append(f"\U0001F4F0 {hl}")
lines.append("")
lines.append("Not financial advice, manage your own risk. Experimental v2.4 multi-position signal. [strat v2.4]")
msg = "\n".join(lines)

# --- entry chart (candles + pattern + SL/TP) ---
chart_url = None
chart_path = None
try:
    import glob as _glob
    chart_dir = os.path.expanduser("~/workspace/trading-ea/charts")
    os.makedirs(chart_dir, exist_ok=True)
    chart_path = os.path.join(chart_dir, f"entry_{bar_iso}.png")
    chart_in = {
        "bars": [{"t": b[0], "o": b[1], "h": b[2], "l": b[3], "c": b[4]} for b in closed_tf],
        "pattern": {k: pattern[k] for k in
                    ("kind", "p1", "p2", "neck", "upper", "lower",
                     "p1_t", "neck_t", "p2_t")
                    if k in pattern},
        "signal": sig, "entry": price, "tf": TF_UP,
        "sl": sl_d, "tp1": tp1_d, "tp2": tp2_d, "tp3": tp3_d,
        "bar_time_wib": datetime.datetime.fromtimestamp(sig_bar[0], datetime.timezone.utc)
                         .astimezone(WIB).strftime("%d %b %H:%M"),
        "out": chart_path,
    }
    tmp_in = chart_path + ".json"
    json.dump(chart_in, open(tmp_in, "w"))
    r = subprocess.run([sys.executable, os.path.expanduser("~/hooks/scripts/make_chart.py"),
                        tmp_in], capture_output=True, text=True, timeout=60)
    os.remove(tmp_in)
    if os.path.exists(chart_path):
        chart_url = "sandbox://workspace/trading-ea/charts/" + os.path.basename(chart_path)
        # keep only the 20 newest charts
        files = sorted(_glob.glob(os.path.join(chart_dir, "entry_*.png")),
                       key=os.path.getmtime)
        for old in files[:-20]:
            os.remove(old)
    else:
        log(HOOK_ID, f"chart-fail:{r.stderr[:80]}")
except Exception as ex:
    log(HOOK_ID, f"chart-fail:{str(ex)[:80]}")

st["last_bar"] = bar_iso
# v2.4 multi-position: track the LATEST signal for SL/TP notifications.
# New signals overwrite; the journal records all. No suppression.
st["active_trade"] = {"signal": sig, "entry": price, "sl_d": sl_d,
                      "tp1_d": tp1_d, "tp2_d": tp2_d, "tp3_d": tp3_d,
                      "bar_ts": sig_bar[0], "ts": now}
# don't consume the signal on dry runs (a dry-run wake must not silence the next live poll)
save_state_keys({"last_bar": bar_iso, "active_trade": st["active_trade"],
                 "pattern_p2_t": pattern["p2_t"]})
if os.environ.get("HATCH_HOOK_DRY_RUN") != "1":
    # --- alert journal for outcome tracking / learning loop ---
    # Uses save_journal_rows (locked) to prevent lost updates.
    def _append_signal(rows):
        # strategy version for performance comparison across logic changes
        # v2.1 brutal: -dtb = double top/bottom touch, -donch = Donchian breakout
        sv = "2.4-" + ("dtb" if pattern["kind"] in ("DOUBLE TOP", "DOUBLE BOTTOM")
                       else "donch")
        row = {"alert_time_utc": bar_iso, "signal": sig, "entry_ref": price,
               "sl_d": sl_d, "tp1_d": tp1_d, "tp2_d": tp2_d, "tp3_d": tp3_d,
               "status": "open", "outcome": "", "closed_time_utc": "",
               "max_tp": "", "r_multiple": "", "strategy_v": sv,
               "timeframe": TF}
        # backfill strategy_v / timeframe for old rows missing them
        for r in rows:
            r.setdefault("strategy_v", "1.0")
            r.setdefault("timeframe", "m5")
        rows.append(row)
        return True
    try:
        save_journal_rows(_append_signal)
    except Exception as ex:
        log(HOOK_ID, f"journal-fail:{str(ex)[:60]}")
log(HOOK_ID, f"wake-{sig.lower()}")
# push to Telegram (direct, reliable) in addition to the side-chat worker wake
tg_send(msg, photo=chart_path,
        caption=f"📊 XAUUSD {TF_UP} Chart — {sig} @ ~${price}",
        keyboard=ALERT_KB)
out("wake", f"{HOOK_ID}-{sig.lower()}",
    {"signal": sig, "price": price, "bar_time_utc": bar_iso,
     "atr_h1": round(a1, 2), "sl_distance": sl_d,
     "tp1_distance": tp1_d, "tp2_distance": tp2_d, "tp3_distance": tp3_d,
     "sl_price": sl_px, "tp1_price": tp1_px, "tp2_price": tp2_px, "tp3_price": tp3_px,
     "risk_usc_at_min_lot": risk_usc,
     "source": src, "headlines": headlines, "news_warning": warn,
     "chart": chart_url,
     "message": msg})
PYEOF
echo "HATCH_HOOK_LOG:{\"message\":\"xauusd-entry-${TF}\",\"reason\":\"script-end\"}" >&2
