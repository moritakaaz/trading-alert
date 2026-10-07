#!/usr/bin/env python3
"""Update outcomes for open XAUUSD entry alerts (learning loop).

Reads ~/hooks/state/entry_journal.csv, and for each 'open' alert fetches
subsequent M5 bars from Twelve Data (fallback: skip, stays open) to find the
first touch of SL / TP1 / TP2 / TP3. Alerts untouched after 48h are marked
'expired'. Prints a summary. Safe to run daily via cron.
"""
import csv, json, os, subprocess, sys, time, datetime, fcntl

JPATH = os.path.expanduser("~/hooks/state/entry_journal.csv")
TD = os.path.expanduser("~/workspace/skills/twelve-data/bin/xauusd_ohlc.py")
EXPIRE_H = 48

def td_m5(n):
    r = subprocess.run([TD, "--interval", "5min", "--outputsize", str(n)],
                       capture_output=True, text=True, timeout=60)
    d = json.loads(r.stdout or "{}")
    if "values" not in d:
        raise RuntimeError(d.get("error", "no values"))
    return d["values"]

def score_row(r, bars, now):
    # Score a single open journal row against M5 bars.
    # Returns True if the row was closed, False if still open.
    # FIX (2026-10-05): extracted so it can run inside the journal lock.
    try:
        at = datetime.datetime.strptime(r["alert_time_utc"], "%Y-%m-%dT%H:%M:%SZ") \
            .replace(tzinfo=datetime.timezone.utc).timestamp()
    except ValueError:
        return False
    sig = r["signal"]; entry = float(r["entry_ref"])
    sl_d, t1, t2, t3 = (float(r[k]) for k in ("sl_d", "tp1_d", "tp2_d", "tp3_d"))
    m = 1 if sig == "BUY" else -1
    sl_px = entry - m * sl_d
    tp1_px, tp2_px, tp3_px = entry + m * t1, entry + m * t2, entry + m * t3
    sl_first, tp1_t, max_tp, be_hit, closed_t = False, None, 0, False, None
    max_tp_t = None
    expired_t = None
    last_close = None
    for b in bars:
        if b["t"] < at:
            continue
        bt = datetime.datetime.fromtimestamp(b["t"], datetime.timezone.utc) \
            .strftime("%Y-%m-%dT%H:%M:%SZ")
        if b["t"] - at > EXPIRE_H * 3600:
            expired_t = bt
            break
        last_close = b["c"]
        if sig == "BUY":
            sl_hit = b["l"] <= sl_px
            t1_hit, t2_hit, t3_hit = b["h"] >= tp1_px, b["h"] >= tp2_px, b["h"] >= tp3_px
            be_hit_now = b["l"] <= entry
        else:
            sl_hit = b["h"] >= sl_px
            t1_hit, t2_hit, t3_hit = b["l"] <= tp1_px, b["l"] <= tp2_px, b["l"] <= tp3_px
            be_hit_now = b["h"] >= entry
        if tp1_t is None:
            if sl_hit:
                sl_first, closed_t = True, bt
                break
            if t1_hit:
                tp1_t, max_tp, max_tp_t = bt, 1, bt
                if t3_hit:
                    max_tp, max_tp_t = 3, bt
                elif t2_hit:
                    max_tp = 2
        else:
            if t3_hit:
                max_tp, max_tp_t = 3, bt
            elif t2_hit:
                max_tp, max_tp_t = max(max_tp, 2), bt
            if be_hit_now:
                be_hit, closed_t = True, bt
                break
    if sl_first:
        outcome, rmult = "SL", -1.0
    elif max_tp == 0:
        if expired_t:
            if last_close is not None:
                pnl = (last_close - entry) * m
                rmult = round(pnl / sl_d, 2)
            else:
                rmult = 0.0
            outcome, closed_t = "expired", expired_t
        else:
            return False  # still open
    elif be_hit:
        outcome, rmult = f"TP{max_tp}+BE", 0.0
    else:
        rmult = float({1: 1.0, 2: 1.5, 3: 2.0}[max_tp])
        outcome, closed_t = f"TP{max_tp}", max_tp_t or expired_t
    r["status"], r["outcome"], r["closed_time_utc"] = "closed", outcome, closed_t or expired_t
    r["max_tp"], r["r_multiple"] = str(max_tp), str(rmult)
    return True

def main():
    if not os.path.exists(JPATH):
        print("no journal yet"); return
    # Fetch price data FIRST (outside lock — don't hold lock during network).
    try:
        bars = td_m5(1500)
    except Exception as e:
        print(f"price fetch failed: {e}"); return
    now = time.time()
    # FIX (2026-10-05): read + score + write ALL inside the lock.
    # Prevents lost updates if the alert script appends a signal mid-run.
    result = {}
    def _update(rows):
        for r in rows:
            r.setdefault("max_tp", "")
            r.setdefault("r_multiple", "")
            r.setdefault("strategy_v", "1.0")
        opens = [r for r in rows if r["status"] == "open"]
        result["total"] = len(rows)
        result["opens"] = len(opens)
        if not opens:
            return False  # nothing to do
        updated = 0
        for r in opens:
            try:
                if score_row(r, bars, now):
                    updated += 1
            except Exception as ex:
                # one corrupt row must not kill the whole run
                print(f"skip bad row {r.get('alert_time_utc')}: {ex}",
                      file=sys.stderr)
        result["updated"] = updated
        return True
    # need a lock-aware version that returns the result
    import fcntl, tempfile
    lock_path = JPATH + ".lock"
    with open(lock_path, "a+") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            rows = []
            fieldnames = None
            if os.path.exists(JPATH):
                with open(JPATH, newline="") as jf:
                    reader = csv.DictReader(jf)
                    fieldnames = reader.fieldnames
                    rows = list(reader)
            if _update(rows) is False:
                print(f"{result.get('total', 0)} alerts, none open")
                return
            if fieldnames and "strategy_v" not in fieldnames:
                fieldnames = fieldnames + ["strategy_v"]
            if not fieldnames and rows:
                fieldnames = list(rows[0].keys())
            if fieldnames:
                # atomic write: lock-free readers see old OR new, never partial
                d = os.path.dirname(JPATH) or "."
                fd, tmp = tempfile.mkstemp(dir=d, prefix=".journal_tmp_")
                try:
                    with os.fdopen(fd, "w", newline="") as jf:
                        w = csv.DictWriter(jf, fieldnames=fieldnames)
                        w.writeheader()
                        w.writerows(rows)
                    os.replace(tmp, JPATH)
                except Exception:
                    try:
                        os.unlink(tmp)
                    except Exception:
                        pass
                    raise
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)
    # stats (outside lock, using the rows we just wrote)
    closed = [r for r in rows if r["status"] == "closed"]
    if not closed:
        print(f"alerts={len(rows)} open={len(rows)-len(closed)} updated={result.get('updated', 0)}")
        return
    skipped_n = sum(1 for r in rows if r["status"] in ("skipped", "cancelled"))
    rs = []
    for r in closed:
        try:
            rs.append(float(r.get("r_multiple") or 0))
        except ValueError:
            rs.append(0.0)
    wins = sum(1 for x in rs if x > 0)
    gross_win = sum(x for x in rs if x > 0)
    gross_loss = -sum(x for x in rs if x < 0)
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
    print(f"alerts={len(rows)} open={len(rows)-len(closed)} updated={result.get('updated', 0)} "
          f"closed={len(closed)} winrate={wins/len(closed)*100:.0f}% "
          f"totalR={sum(rs):+.1f} avgR={sum(rs)/len(rs):+.2f} PF~{pf:.2f} "
          f"skipped={skipped_n}")

if __name__ == "__main__":
    main()
