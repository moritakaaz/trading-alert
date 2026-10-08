#!/usr/bin/env python3
"""Monthly log maintenance for the XAUUSD alert system.
- Truncates hooks/logs/*.jsonl to the last 14 days (prevents unbounded growth).
- Snapshots entry_journal.csv to ~/workspace/your_files/ (monthly, downloadable).
Safe to run via cron; idempotent.
"""
import os, json, time, datetime, shutil, glob

def prune_jsonl(path, days=14):
    cutoff = time.time() - days * 86400
    try:
        with open(path) as f:
            lines = f.readlines()
    except FileNotFoundError:
        return 0, 0
    kept = []
    for line in lines:
        try:
            ts = json.loads(line).get("started_at_ms", 0) / 1000
            if ts >= cutoff or ts == 0:
                kept.append(line)
        except Exception:
            kept.append(line)  # keep unparseable lines rather than dropping
    if len(kept) != len(lines):
        with open(path, "w") as f:
            f.writelines(kept)
    return len(lines), len(kept)

def main():
    for pat in ["~/hooks/logs/xauusd-entry-m5.jsonl",
                "~/hooks/logs/xauusd-tg-cmd.jsonl",
                "~/hooks/logs/xauusd-watchdog.jsonl"]:
        p = os.path.expanduser(pat)
        before, after = prune_jsonl(p)
        print(f"{os.path.basename(p)}: {before} -> {after} lines")
    j = os.path.expanduser("~/hooks/state/entry_journal.csv")
    if os.path.exists(j):
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m")
        dest = os.path.expanduser(
            f"~/workspace/your_files/entry_journal_{stamp}.csv")
        shutil.copy2(j, dest)
        print(f"journal snapshot: {dest}")
    # backup hook state JSON (active_trade, modal, circuit, paused_until, ...)
    s = os.path.expanduser("~/hooks/state/xauusd_entry_m5.json")
    if os.path.exists(s):
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m")
        sdest = os.path.expanduser(
            f"~/workspace/your_files/state_backup_{stamp}.json")
        shutil.copy2(s, sdest)
        print(f"state backup: {sdest}")
    # prune old monthly snapshots, keep last 6
    for pat, keep in [("~/workspace/your_files/entry_journal_*.csv", 6),
                      ("~/workspace/your_files/state_backup_*.json", 6)]:
        snaps = sorted(glob.glob(os.path.expanduser(pat)))
        for old in snaps[:-keep]:
            os.remove(old)
            print(f"removed old snapshot: {old}")

if __name__ == "__main__":
    main()
