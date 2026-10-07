#!/usr/bin/env python3
"""fix6sl_backtest.py — re-backtest of the XAUUSD M5 v1.1 strategy + fix candidates.
Replicates the live logic: Donchian(48) on completed H1, M5-close trigger, SL 1.5xATR(H1),
transition-only, H4 filter (chunk-4 quirk), one-position-at-a-time (SL/TP1/48h).
live_pos gates when new signals may fire; the runner computes R_full separately.
READ-ONLY on the live system.
"""
import csv, glob, zipfile, datetime, bisect, sys, calendar

WIB = datetime.timezone(datetime.timedelta(hours=7))

def load_bars():
    bars = []
    for zf in sorted(glob.glob("/tmp/paxg_m5/*.zip")):
        try:
            with zipfile.ZipFile(zf) as z:
                name = z.namelist()[0]
                with z.open(name) as f:
                    for row in csv.reader(f.read().decode().splitlines()):
                        t = int(row[0]) // 1_000_000
                        bars.append((t, float(row[1]), float(row[2]),
                                     float(row[3]), float(row[4])))
        except Exception as e:
            print("skip", zf, str(e)[:50], file=sys.stderr)
    try:
        with open("/tmp/paxg_m5/paxg_oct6_api.csv") as f:
            for row in csv.reader(f):
                t = int(row[0]) // 1_000_000
                bars.append((t, float(row[1]), float(row[2]),
                             float(row[3]), float(row[4])))
    except FileNotFoundError:
        pass
    bars.sort()
    seen, out = set(), []
    for t, o, h, l, c in bars:
        if t in seen:
            continue
        seen.add(t)
        dt = datetime.datetime.fromtimestamp(t, datetime.timezone.utc)
        wd, hr = dt.weekday(), dt.hour + dt.minute / 60
        if wd == 5: continue
        if wd == 6 and hr < 22: continue
        if wd == 4 and hr >= 21: continue
        out.append((t, o, h, l, c))
    return out

print("loading...", flush=True, file=sys.stderr)
bars = load_bars()
t5 = [b[0] for b in bars]
print(f"M5: {len(bars)} ({datetime.datetime.fromtimestamp(t5[0], datetime.timezone.utc):%Y-%m-%d} -> "
      f"{datetime.datetime.fromtimestamp(t5[-1], datetime.timezone.utc):%Y-%m-%d %H:%M}Z)", flush=True)

h1 = []
bkt = None
for t, o, h, l, c in bars:
    hb = t - (t % 3600)
    if bkt is None or bkt[0] != hb:
        if bkt: h1.append(bkt)
        bkt = [hb, o, h, l, c]
    else:
        bkt[2] = max(bkt[2], h); bkt[3] = min(bkt[3], l); bkt[4] = c
if bkt: h1.append(bkt)
h1t = [b[0] for b in h1]
print(f"H1: {len(h1)}", flush=True)

# precompute ATR(14) per H1 bar
atr_h1 = [0.0] * len(h1)
for k in range(14, len(h1)):
    s = 0.0
    for m in range(k - 13, k + 1):
        hh, ll, pc = h1[m][2], h1[m][3], h1[m - 1][4]
        tr = hh - ll
        d1 = abs(hh - pc)
        if d1 > tr: tr = d1
        d2 = abs(ll - pc)
        if d2 > tr: tr = d2
        s += tr
    atr_h1[k] = s / 14

def h4_trend(j):
    # replicate live quirk: last 80 completed H1 bars, chunk in 4s from index 0
    seg = h1[max(0, j - 79):j + 1]
    if len(seg) < 63:
        return None
    closes = [seg[_i:_i + 4][-1][4] for _i in range(0, len(seg) - 3, 4)]
    if len(closes) < 15:
        return None
    sma = sum(closes[-15:]) / 15
    return "BULLISH" if closes[-1] > sma else "BEARISH"

def sig_of(close, upper, lower):
    if close > upper: return "BUY"
    if close < lower: return "SELL"
    return None

def session_wib(ts):
    dt = datetime.datetime.fromtimestamp(ts, WIB)
    h = dt.hour + dt.minute / 60
    if 6 <= h < 14: return "Asia"
    if 14 <= h < 20.5: return "London"
    if h >= 20.5 or h < 4: return "New York"
    return "Off"

def run(cfg, t_start, t_end):
    """cfg keys: h4_filter, transition_only, one_position,
    min_depth_atr (None=off), cooldown_h (None=off),
    vol_guard (None=off: skip if atr14 > mult * median(prev 20 atr14))."""
    trades = []
    live_pos = None
    runners = []
    suppress_until = 0
    last_sl_ts = 0
    i0 = bisect.bisect_left(t5, t_start)
    i1 = bisect.bisect_left(t5, t_end)
    for i in range(max(i0, 60), i1):
        ts = t5[i]; o, h, l, c = bars[i][1], bars[i][2], bars[i][3], bars[i][4]
        hb = ts - (ts % 3600)
        j = bisect.bisect_left(h1t, hb) - 1
        if j < 61:
            continue
        win = h1[j - 47:j + 1]
        upper = max(b[2] for b in win); lower = min(b[3] for b in win)
        a = atr_h1[j]
        if a <= 0: continue

        # 1. runners: full-runner resolution (SL / BE-after-TP1 / TP3 / 48h)
        for r in runners[:]:
            d = r["dir"]; entry = r["entry"]; risk = r["risk"]
            sl = entry if r["tp1_hit"] else r["sl"]
            tp3 = r["tp3"]; tp1 = r["tp1"]
            if d == "BUY":
                hit_sl = l <= sl; hit_tp3 = h >= tp3
                if not r["tp1_hit"] and h >= tp1: r["tp1_hit"] = True
            else:
                hit_sl = h >= sl; hit_tp3 = l <= tp3
                if not r["tp1_hit"] and l <= tp1: r["tp1_hit"] = True
            expired = ts - r["ts"] >= 48 * 3600
            done = False
            if hit_sl:
                r["r_full"] = 0.0 if r["tp1_hit"] else -1.0; done = True
            elif hit_tp3:
                r["r_full"] = 2.0; done = True
            elif expired:
                r["r_full"] = (c - entry) / risk if d == "BUY" else (entry - c) / risk
                done = True
            if done:
                trades.append(r); runners.remove(r)

        # 2. live_pos: live resolution (SL / TP1 / 48h) — gates new signals
        if live_pos is not None:
            d = live_pos["dir"]; sl = live_pos["sl"]; tp1 = live_pos["tp1"]
            if d == "BUY":
                hit_sl = l <= sl; hit_tp1 = h >= tp1
            else:
                hit_sl = h >= sl; hit_tp1 = l <= tp1
            expired = ts - live_pos["ts"] >= 48 * 3600
            if hit_sl:
                last_sl_ts = ts; live_pos = None
                if cfg.get("one_position"): suppress_until = ts
            elif hit_tp1 or expired:
                live_pos = None
                if cfg.get("one_position"): suppress_until = ts

        # 3. new signal
        if live_pos is None and ts >= suppress_until:
            sig = sig_of(c, upper, lower)
            if cfg.get("transition_only"):
                sig_prev = sig_of(bars[i - 1][4], upper, lower)
                if sig is None or sig == sig_prev:
                    continue
            elif sig is None:
                continue
            if cfg.get("h4_filter"):
                tr = h4_trend(j)
                if tr is None: continue
                if not ((sig == "BUY" and tr == "BULLISH") or
                        (sig == "SELL" and tr == "BEARISH")):
                    continue
            depth = (c - upper) if sig == "BUY" else (lower - c)
            if cfg.get("min_depth_atr") and depth < cfg["min_depth_atr"] * a:
                continue
            if cfg.get("cooldown_h") and ts - last_sl_ts < cfg["cooldown_h"] * 3600:
                continue
            if cfg.get("vol_guard"):
                hist = sorted(atr_h1[max(14, j - 20):j])
                if hist and a > cfg["vol_guard"] * hist[len(hist) // 2]:
                    continue
            risk = 1.5 * a
            entry = c
            if sig == "BUY":
                sl, tp1, tp3 = entry - risk, entry + risk, entry + 2 * risk
            else:
                sl, tp1, tp3 = entry + risk, entry - risk, entry - 2 * risk
            trade = {"dir": sig, "ts": ts, "entry": entry, "sl": sl,
                     "tp1": tp1, "tp3": tp3, "risk": risk, "atr": a,
                     "depth_atr": depth / a, "session": session_wib(ts),
                     "tp1_hit": False, "r_full": None}
            live_pos = {"dir": sig, "ts": ts, "sl": sl, "tp1": tp1}
            runners.append(trade)
    return trades

def stats(trades, name):
    if not trades:
        print(f"{name}: NO TRADES"); return None
    rs = [t["r_full"] for t in trades]
    w = sum(1 for r in rs if r > 0)
    gw = sum(r for r in rs if r > 0); gl = -sum(r for r in rs if r <= 0)
    pf = gw / gl if gl > 0 else float("inf")
    eq = peak = mdd = 0.0
    for r in rs:
        eq += r; peak = max(peak, eq); mdd = max(mdd, peak - eq)
    tp1r = sum(1 for t in trades if t["tp1_hit"]) / len(trades) * 100
    print(f"{name}: n={len(trades)} win={w/len(trades)*100:.1f}% PF={pf:.2f} "
          f"avgR={sum(rs)/len(rs):+.2f} totR={sum(rs):+.1f} maxDD={mdd:.1f} TP1hit={tp1r:.0f}%")
    return {"n": len(trades), "pf": pf, "totR": sum(rs), "maxDD": mdd}

def U(s):
    return calendar.timegm(datetime.datetime.strptime(s, "%Y-%m-%d %H:%M").timetuple())

if __name__ == "__main__":
    JAN = U("2026-01-01 00:00"); SEP = U("2026-09-01 00:00")
    END = t5[-1] + 1
    V11 = {"h4_filter": True, "transition_only": True, "one_position": True}

    print("\n=== VALIDASI: replikasi extended research 'A: H4 filter' Jan-Oct (tanpa transition/one-position) ===")
    stats(run({"h4_filter": True}, JAN, END), "H4-only Jan-Oct [acuan: PF~1.28 n~195]")

    print("\n=== LIVE v1.1 ===")
    stats(run(V11, JAN, END), "v1.1 Jan-Oct")
    stats(run(V11, SEP, END), "v1.1 Sep-Oct << edge decay check")

    print("\n=== v1.1 per bulan ===")
    for m in range(1, 11):
        a = U(f"2026-{m:02d}-01 00:00")
        b = U(f"2026-{m+1:02d}-01 00:00") if m < 10 else END
        tt = run(V11, a, b)
        if tt:
            rs = [x["r_full"] for x in tt]
            gw = sum(r for r in rs if r > 0); gl = -sum(r for r in rs if r <= 0)
            pf = gw / gl if gl > 0 else float("inf")
            print(f"  2026-{m:02d}: n={len(tt)} PF={pf:.2f} totR={sum(rs):+.1f}")
        else:
            print(f"  2026-{m:02d}: n=0")
