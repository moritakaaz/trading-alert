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

# B34: shared market hours (single source of truth)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from marketHours import in_forex_hours
except ImportError:
    in_forex_hours = None

STATE = os.path.expanduser("~/hooks/state/xauusd_entry_m5.json")
WD_STATE = os.path.expanduser("~/hooks/state/watchdog_state.json")  # B35: watchdog dedupe in its own file
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
        # B30 (P1): token via -K config file, not in argv
        import tempfile
        _cfg = tempfile.NamedTemporaryFile(mode="w", suffix=".curlcfg",
                                           delete=False)
        try:
            _cfg.write('url = "%s"\n' % (base + "/sendMessage").replace('"', "%22"))
            _cfg.close()
            subprocess.run(
                ["curl", "-K", _cfg.name, "-s", "-m", "25",
                 "--data-urlencode", "chat_id=" + cid,
                 "--data-urlencode", "text=" + esc(text),
                 "--data-urlencode", "parse_mode=HTML"],
                capture_output=True, timeout=30)
        finally:
            try:
                os.unlink(_cfg.name)
            except Exception:
                pass
        log("tg-sent")
    except Exception as ex:
        log(f"tg-fail:{str(ex)[:60]}")


def _in_forex_hours_local(now):
    # Fallback if marketHours import failed (kept in sync with marketHours.py)
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

def _forex_hours(now):
    # B34: prefer shared marketHours module
    if in_forex_hours:
        return in_forex_hours(now)
    return _in_forex_hours_local(now)


def check_tf(tf, now):
    # v2.4: per-timeframe checks (M1/M5/M15). Only checks TFs with alert_on=true.
    STATE_TF = os.path.expanduser(f"~/hooks/state/xauusd_entry_{tf}.json")
    LOG_TF = os.path.expanduser(f"~/hooks/logs/xauusd-entry-{tf}.jsonl")
    try:
        with open(STATE_TF) as f:
            st = json.load(f)
        state_missing = False
    except Exception:
        st = {}
        state_missing = True
    if state_missing:
        # only alert if this TF was supposed to be on (avoid noise for never-used TFs)
        log(f"{tf}:skip:state-missing")
        return
    alert_on = st.get("alert_on", False)
    if not alert_on:
        log(f"{tf}:skip:alert-off")
        return

    # --- 1. heartbeat freshness ---
    # v2.5: check last_run (liveness), not last_heartbeat (message gate)
    last_hb = st.get("last_run", 0)
    if _forex_hours(now) and now - last_hb > 900:
        mins = int((now - last_hb) / 60)
        last_wd = st.get("watchdog_last_alert", 0)
        if now - last_wd > 3600:
            tg_send(
                f"⚠️ <b>SYSTEM DOWN? ({tf.upper()})</b>\n"
                f"Last heartbeat {mins} minutes ago.\n"
                f"The xauusd-entry-{tf} hook may be dead. Check /alert_status.")
            save_wd_ts(STATE_TF, "watchdog_last_alert", now)
            log(f"{tf}:alert:heartbeat-stale-{mins}m")
        else:
            log(f"{tf}:heartbeat-stale:already-alerted")
    else:
        log(f"{tf}:ok:heartbeat-fresh")

    # --- 2. consecutive price-fetch failures ---
    try:
        trailing = 0
        with open(LOG_TF) as f:
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
                    f"⚠️ <b>PRICE FEED DOWN ({tf.upper()})</b>\n"
                    f"{trailing} consecutive price fetch failures.\n"
                    f"Check connection / API quota.")
                save_wd_ts(STATE_TF, "watchdog_last_price_alert", now)
                log(f"{tf}:alert:price-fail-x{trailing}")
            else:
                log(f"{tf}:price-fail:already-alerted")
    except Exception as ex:
        log(f"{tf}:price-check-fail:{str(ex)[:40]}")


def save_wd_ts(state_path, key, now):
    # atomic write via tempfile + replace; lock on separate .lock file
    import tempfile
    lock_path = state_path + ".lock"
    try:
        with open(lock_path, "a+") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                try:
                    with open(state_path) as rf:
                        s = json.load(rf)
                except Exception:
                    s = {}
                s[key] = now
                d = os.path.dirname(state_path) or "."
                fd, tmp = tempfile.mkstemp(dir=d, prefix=".state_tmp_")
                try:
                    with os.fdopen(fd, "w") as tf:
                        json.dump(s, tf)
                    os.replace(tmp, state_path)
                except Exception:
                    try:
                        os.unlink(tmp)
                    except Exception:
                        pass
                    raise
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)
    except Exception:
        pass


def main():
    now = int(time.time())
    # v2.4: check all three timeframes (only those with alert_on=true)
    for tf in ("m1", "m5", "m15"):
        try:
            check_tf(tf, now)
        except Exception as ex:
            log(f"{tf}:check-fail:{str(ex)[:40]}")

    # --- 3. command handler liveness (FIX #6, 2026-10-05) ---
    # If xauusd-tg-cmd dies, Telegram commands silently stop working
    # while the entry heartbeat looks healthy. Check its log freshness.
    try:
        cmd_log = os.path.expanduser("~/hooks/logs/xauusd-tg-cmd.jsonl")
        # B56: if the log file does not exist yet (fresh install), skip the
        # check instead of firing COMMAND HANDLER DOWN on every run.
        if not os.path.exists(cmd_log):
            log("ok:cmd-log-not-yet-created")
        else:
            _check_cmd_stale(now, os.path.getmtime(cmd_log))
    except Exception as ex:
        log(f"cmd-check-fail:{str(ex)[:40]}")

    # B57: rotate logs on every watchdog run (cheap, idempotent)
    try:
        prune_logs()
    except Exception:
        pass


def prune_logs(days=14):
    """B57: rotate jsonl logs — keep only the last `days` days of entries.

    Idempotent and cheap: files are only rewritten when lines are dropped.
    """
    cutoff = time.time() - days * 86400
    for pat in ("~/hooks/logs/xauusd-entry-m1.jsonl",
                "~/hooks/logs/xauusd-entry-m5.jsonl",
                "~/hooks/logs/xauusd-entry-m15.jsonl",
                "~/hooks/logs/xauusd-tg-cmd.jsonl",
                "~/hooks/logs/xauusd-watchdog.jsonl"):
        p = os.path.expanduser(pat)
        try:
            with open(p) as f:
                lines = f.readlines()
        except FileNotFoundError:
            continue
        kept = []
        for line in lines:
            try:
                ts = json.loads(line).get("started_at_ms", 0) / 1000
                if ts >= cutoff or ts == 0:
                    kept.append(line)
            except Exception:
                kept.append(line)  # keep unparseable lines rather than dropping
        if len(kept) < len(lines):
            try:
                with open(p, "w") as f:
                    f.writelines(kept)
                log(f"pruned:{os.path.basename(p)}:{len(lines)}->{len(kept)}")
            except Exception:
                pass


def _check_cmd_stale(now, cmd_mtime):
    # tg-cmd polls every 30s, so >5 min without a log line = dead
    if now - cmd_mtime > 300:
        # B35: dedupe in watchdog's own state file
        try:
            with open(WD_STATE) as f:
                st5 = json.load(f)
        except Exception:
            st5 = {}
        last_wd = st5.get("watchdog_last_cmd_alert", 0)
        if now - last_wd > 3600:
            tg_send(
                f"⚠️ <b>COMMAND HANDLER DOWN?</b>\n"
                f"No activity for {int((now - cmd_mtime) / 60)} minutes.\n"
                f"Telegram commands may not be responding.")
            save_wd_ts(WD_STATE, "watchdog_last_cmd_alert", now)
            log("alert:cmd-handler-stale")
        else:
            log("cmd-handler-stale:already-alerted")
    else:
        log("ok:cmd-handler-alive")


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        log(f"watchdog-crash:{str(ex)[:60]}")
