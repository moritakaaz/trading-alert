#!/usr/bin/env python3
"""Send a Telegram message via the dedicated alert bot (@ahsudahlah_bot).
Usage: send_tg.py <textfile> [--silent]
Reads the message from <textfile> (HTML parse_mode). Used by cron workers
(e.g. Sunday review) because background worker -> WhatsApp delivery is
unreliable; direct Bot API push is the authoritative channel.
"""
import sys, os, subprocess

def main():
    if len(sys.argv) < 2:
        print("usage: send_tg.py <textfile> [--silent]", file=sys.stderr)
        sys.exit(2)
    silent = "--silent" in sys.argv[2:]
    with open(sys.argv[1]) as f:
        text = f.read().strip()
    if not text:
        print("empty message", file=sys.stderr)
        sys.exit(1)
    tok = cid = None
    with open(os.path.expanduser("~/.tg-alert-bot/.env")) as f:
        for line in f:
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                tok = line.strip().split("=", 1)[1]
            elif line.startswith("TELEGRAM_CHAT_ID="):
                cid = line.strip().split("=", 1)[1]
    if not tok or not cid:
        print("no tg creds", file=sys.stderr)
        sys.exit(1)
    cmd = ["curl", "-s", "-m", "30",
           "--data-urlencode", f"chat_id={cid}",
           "--data-urlencode", f"text={text}",
           "--data-urlencode", "parse_mode=HTML"]
    if silent:
        cmd += ["--data-urlencode", "disable_notification=true"]
    cmd.append(f"https://api.telegram.org/bot{tok}/sendMessage")
    r = subprocess.run(cmd, capture_output=True, timeout=35)
    import json
    try:
        ok = json.loads(r.stdout or b"{}").get("ok")
    except Exception:
        ok = False
    print("tg-send ok:", ok)
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
