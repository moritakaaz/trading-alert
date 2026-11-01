#!/usr/bin/env python3
"""Windows bridge for the XAUUSD alert bot executor.

Subscribes to the bot's private push channel, verifies each signal,
and appends it to executor_signals.csv in the MT5 Common Files folder,
where ExecutorEA.mq5 picks it up.

Python 3 standard library only. No pip installs.

Usage:
    python bridge.py                 run the bridge (uses bridge_config.json)
    python bridge.py --test          append one TEST signal and exit
    python bridge.py --files-dir "C:\\path\\to\\Files"   override MT5 folder

Config (bridge_config.json, next to this script):
    {
      "topic":     "<channel name>",
      "secret":    "<shared secret>",
      "ntfy_base": "https://ntfy.sh",
      "files_dir": ""        // optional override; empty = auto-detect
    }

Treat bridge_config.json like a password. Never share it or commit it.
"""

import argparse
import csv
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "bridge_config.json")
SIGNAL_FILE = "executor_signals.csv"
HEADER = ["id", "signal", "sl_d", "tp1_d", "tp2_d", "tp3_d"]


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    for key in ("topic", "secret"):
        if not cfg.get(key):
            sys.exit(f"bridge_config.json is missing '{key}'")
    cfg.setdefault("ntfy_base", "https://ntfy.sh")
    cfg.setdefault("files_dir", "")
    return cfg


def detect_files_dir(cfg):
    if cfg.get("files_dir"):
        return cfg["files_dir"]
    appdata = os.environ.get("APPDATA")
    if not appdata:
        sys.exit("APPDATA not found; set files_dir in bridge_config.json")
    # MT5 Common Files folder, shared by all terminals on this machine.
    return os.path.join(appdata, "MetaQuotes", "Terminal", "Common", "Files")


def append_signal(files_dir, payload):
    """Append one signal row to the queue file. Returns the signal id."""
    os.makedirs(files_dir, exist_ok=True)
    path = os.path.join(files_dir, SIGNAL_FILE)
    sig_id = str(payload["id"])
    # Local dedupe: never write the same id twice.
    if os.path.exists(path):
        with open(path, "r", newline="", encoding="utf-8") as f:
            for row in csv.reader(f):
                if row and row[0] == sig_id:
                    print(f"[bridge] duplicate, skipped: {sig_id}")
                    return None
    new_file = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(HEADER)
        w.writerow([sig_id, payload["signal"], payload["sl_d"],
                    payload["tp1_d"], payload["tp2_d"], payload["tp3_d"]])
    print(f"[bridge] queued: {sig_id} {payload['signal']} "
          f"sl_d={payload['sl_d']} tp1_d={payload['tp1_d']}")
    return sig_id


def handle_message(cfg, files_dir, raw):
    try:
        payload = json.loads(raw)
    except Exception:
        return
    if payload.get("secret") != cfg["secret"]:
        print("[bridge] WARNING: message with wrong secret, ignored")
        return
    for key in ("id", "signal", "sl_d", "tp1_d", "tp2_d", "tp3_d"):
        if key not in payload:
            print(f"[bridge] WARNING: message missing '{key}', ignored")
            return
    append_signal(files_dir, payload)


def run(cfg, files_dir):
    url = cfg["ntfy_base"].rstrip("/") + "/" + cfg["topic"] + "/json"
    print(f"[bridge] listening... queue file: {os.path.join(files_dir, SIGNAL_FILE)}")
    print("[bridge] keep this window open. Ctrl+C to stop.")
    while True:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "xauusd-bridge/1.0"})
            with urllib.request.urlopen(req, timeout=90) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", "replace").strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except Exception:
                        continue
                    if event.get("event") == "message" and event.get("message"):
                        handle_message(cfg, files_dir, event["message"])
        except KeyboardInterrupt:
            print("\n[bridge] stopped")
            return
        except Exception as ex:
            print(f"[bridge] connection dropped ({ex}); reconnecting in 5s")
            time.sleep(5)


def main():
    ap = argparse.ArgumentParser(description="XAUUSD executor bridge")
    ap.add_argument("--test", action="store_true",
                    help="append one test signal to the queue file and exit")
    ap.add_argument("--files-dir", default="",
                    help="override the MT5 Common Files folder")
    args = ap.parse_args()

    cfg = load_config()
    if args.files_dir:
        cfg["files_dir"] = args.files_dir
    files_dir = detect_files_dir(cfg)

    if args.test:
        payload = {
            "id": "TEST-" + time.strftime("%Y%m%d%H%M%S", time.gmtime()),
            "signal": "BUY", "sl_d": 10, "tp1_d": 10, "tp2_d": 15, "tp3_d": 20,
            "secret": cfg["secret"],
        }
        # The test signal bypasses the channel; the EA will execute it on
        # the demo account so you can verify the whole chain end to end.
        append_signal(files_dir, payload)
        print("[bridge] test signal written. The EA should open a small "
              "BUY on the demo account within a few seconds.")
        return

    run(cfg, files_dir)


if __name__ == "__main__":
    main()
