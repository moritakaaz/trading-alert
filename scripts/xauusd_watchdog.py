#!/usr/bin/env python3
"""Dead man's switch for the XAUUSD alert system.

Runs via cron every 10 min. Checks:
1. Heartbeat freshness — if alerts are ON and we're in forex hours but no
   heartbeat in >15 min, the hook is dead -> Telegram alert.
2. Consecutive price-fetch failures — N fails in a row -> Telegram alert.
3. Scoreboard cron liveness — if it hasn't run in >26h -> Telegram alert.

All alerts go DIRECT via Telegram Bot API (never via worker/WhatsApp).
Silent on dry runs. Never raises — a watchdog that crashes is useless.
"""
import json
import os
import sys
import time
import fcntl
import datetime
import subprocess

STATE = os.path.expanduser("~/hooks/state/xauusd_entry_m5.json")
LOG = os.path.expanduser("~/hooks/logs/xauusd-entry-m5.jsonl")
DRY = os.environ.get("HATCH_HOOK_DRY_RUN") == "1"


def log(msg):
    line = json.dumps({"ts": int(time.time() * 1000), "hook": "xauusd-watchdog",
                       "msg": msg})
    try:
        with open(os.path.expanduser("~/hooks/logs/xauusd-watchdog.jsonl"),
                  "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def tg_send(text):
    try:
        if DRY:
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
            return (s or "").replace("&", "&amp;").replace("<", "&lt;") \
                            .replace(">", "&gt;")
        subprocess.run(
            ["curl", "-s", "-m", "25",
             "--data-urlencode", "chat_id=" + cid,
             "--data-urlencode", "text=" + esc(text),
             "--data-urlencode", "parse_mode=HTML",
             base + "/sendMessage"],
            capture_output=True, timeout=30)
        log("tg-sent")
    except Exception as ex:
        log(f"tg-fail:{str(ex)[:60]}")


def in_forex_hours(now):
    # NOTE (2026-10-05): this duplicates the forex-hours gate in
    # xauusd_entry_m5.sh (which uses numeric wd/hm). If either changes,
    # update the other. Both use UTC (DST-immune).
    dt = datetime.datetime.fromtimestamp(now, datetime.timezone.utc)
    if dt.strftime("%H:%M") >= "21:00" and dt.strftime("%H:%M") < "22:00":
        return False  # daily break
    wd = dt.weekday()  # Mon=0
    if wd == 5:
        return False  # Saturday
    if wd == 6 and dt.hour >= 22:
        return True
    if wd == 6:
        return False  # Sunday before 22:00
    if wd == 4 and dt.hour >= 21:
        return False  # Friday after 21:00
    return True


def main():
    now = int(time.time())
    state_missing = False
    try:
        with open(STATE) as f:
            st = json.load(f)
    except Exception:
        st = {}
        state_missing = True
    # FIX (2026-10-05): if state is missing/corrupt, alert instead of
    # going silent — the alert script defaults alert_on=True, so a silent
    # watchdog would leave the system unmonitored.
    if state_missing:
        last_wd = st.get("watchdog_last_alert", 0)
        if now - last_wd > 3600:
            tg_send("⚠️ <b>Watchdog: state file hilang/korup</b>\n\n"
                    "File <code>xauusd_entry_m5.json</code> tidak bisa dibaca. "
                    "Alert script mungkin jalan tanpa watchdog. Cek segera.")
            log("alert:state-missing")
        else:
            log("state-missing:already-alerted")
    # default True to match the alert script's behavior when state is empty
    alert_on = st.get("alert_on", True)
    if not alert_on:
        log("skip:alert-off")
        return

    # --- 1. heartbeat freshness ---
    last_hb = st.get("last_heartbeat", 0)
    if in_forex_hours(now) and now - last_hb > 900:
        mins = int((now - last_hb) / 60)
        # dedupe: don't spam every 10 min
        last_wd = st.get("watchdog_last_alert", 0)
        if now - last_wd > 3600:
            tg_send(
                f"⚠️ <b>SYSTEM DOWN?</b>\n"
                f"Heartbeat terakhir {mins} menit lalu.\n"
                f"Hook xauusd-entry-m5 mungkin mati. Cek /alert_status.")
            # atomic write via tempfile + replace (lock-free readers
            # never see partial); lock on separate .lock file
            import tempfile
            lock_path = STATE + ".lock"
            with open(lock_path, "a+") as lf:
                fcntl.flock(lf, fcntl.LOCK_EX)
                try:
                    try:
                        with open(STATE) as rf:
                            s = json.load(rf)
                    except Exception:
                        s = {}
                    s["watchdog_last_alert"] = now
                    d = os.path.dirname(STATE) or "."
                    fd, tmp = tempfile.mkstemp(dir=d, prefix=".state_tmp_")
                    try:
                        with os.fdopen(fd, "w") as tf:
                            json.dump(s, tf)
                        os.replace(tmp, STATE)
                    except Exception:
                        try:
                            os.unlink(tmp)
                        except Exception:
                            pass
                        raise
                finally:
                    fcntl.flock(lf, fcntl.LOCK_UN)
            log(f"alert:heartbeat-stale-{mins}m")
        else:
            log("heartbeat-stale:already-alerted")
    else:
        log("ok:heartbeat-fresh")

    # --- 2. consecutive price-fetch failures ---
    # (FIX 2026-10-05: removed dead `fails` loop; fixed missing write-back
    # of watchdog_last_price_alert which caused alert spam every 10 min)
    try:
        trailing = 0
        with open(LOG) as f:
            lines = f.readlines()[-20:]
        for line in reversed(lines):
            try:
                r = json.loads(line).get("script_logs", [])
                reasons = [e.get("reason") for e in r]
                if "price-fetch-failed" in reasons:
                    trailing += 1
                else:
                    break
            except Exception:
                break
        if trailing >= 3:
            last_wd = st.get("watchdog_last_price_alert", 0)
            if now - last_wd > 3600:
                tg_send(
                    f"⚠️ <b>PRICE FEED DOWN</b>\n"
                    f"{trailing}x gagal ambil harga berturut-turut.\n"
                    f"Cek koneksi / API quota.")
                try:
                    with open(STATE, "r+") as f:
                        fcntl.flock(f, fcntl.LOCK_EX)
                        s = json.load(f)
                        s["watchdog_last_price_alert"] = now
                        f.seek(0)
                        json.dump(s, f)
                        f.truncate()
                        fcntl.flock(f, fcntl.LOCK_UN)
                except Exception:
                    pass
                log(f"alert:price-fail-x{trailing}")
            else:
                log("price-fail:already-alerted")
    except Exception as ex:
        log(f"price-check-fail:{str(ex)[:40]}")

    # --- 3. command handler liveness (FIX #6, 2026-10-05) ---
    # If xauusd-tg-cmd dies, Telegram commands silently stop working
    # while the entry heartbeat looks healthy. Check its log freshness.
    try:
        cmd_log = os.path.expanduser("~/hooks/logs/xauusd-tg-cmd.jsonl")
        cmd_mtime = os.path.getmtime(cmd_log) if os.path.exists(cmd_log) else 0
        # tg-cmd polls every 30s, so >5 min without a log line = dead
        if now - cmd_mtime > 300:
            last_wd = st.get("watchdog_last_cmd_alert", 0)
            if now - last_wd > 3600:
                tg_send(
                    f"⚠️ <b>COMMAND HANDLER DOWN?</b>\n"
                    f"Tidak ada aktivitas {int((now - cmd_mtime) / 60)} menit.\n"
                    f"Command Telegram mungkin tidak direspons.")
                try:
                    with open(STATE, "r+") as f:
                        fcntl.flock(f, fcntl.LOCK_EX)
                        s = json.load(f)
                        s["watchdog_last_cmd_alert"] = now
                        f.seek(0)
                        json.dump(s, f)
                        f.truncate()
                        fcntl.flock(f, fcntl.LOCK_UN)
                except Exception:
                    pass
                log("alert:cmd-handler-stale")
            else:
                log("cmd-handler-stale:already-alerted")
        else:
            log("ok:cmd-handler-alive")
    except Exception as ex:
        log(f"cmd-check-fail:{str(ex)[:40]}")


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        log(f"watchdog-crash:{str(ex)[:60]}")
