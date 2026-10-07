#!/usr/bin/env python3
"""ema_filter_backtest.py — uji EMA20/50 sebagai FILTER arah pada strategi XAUUSD M5 v1.1.
Basis: fix6sl_backtest.py (harness tervalidasi, replikasi logika live).
READ-ONLY terhadap sistem live. Output: ~/workspace/trading-ea/research/ema_filter_RESULTS.md

Varian:
  F1: state filter di H1 — BUY hanya jika EMA20_H1 > EMA50_H1; SELL hanya jika <.
  F2: F1 + cross harus "segar" (cross terakhir <= 24 bar H1 lalu).
  F3: state filter di M5 (timeframe trigger) — BUY hanya jika EMA20_M5 > EMA50_M5.
Diagnostik: sinyal yang di-suppress dijalankan sebagai "phantom trade" untuk
mengukur PF-nya — kalau yang dibuang malah bagus, filternya merusak.
"""
import sys, calendar, datetime, bisect
sys.path.insert(0, "/home/hatch/workspace/trading-ea/research")
import fix6sl_backtest as B

bars, t5, h1, h1t, atr_h1 = B.bars, B.t5, B.h1, B.h1t, B.atr_h1

def ema(values, period):
    k = 2 / (period + 1)
    out = [0.0] * len(values)
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    e = seed
    for i in range(period, len(values)):
        e = values[i] * k + e * (1 - k)
        out[i] = e
    # backfill warmup
    for i in range(period - 1):
        out[i] = out[period - 1]
    return out

h1c = [b[4] for b in h1]
ema20_h1 = ema(h1c, 20)
ema50_h1 = ema(h1c, 50)
diff_h1 = [a - b for a, b in zip(ema20_h1, ema50_h1)]

# last cross index per H1 bar: k where sign(diff[k]) != sign(diff[k-1])
last_cross = [None] * len(h1)
last = None
prev_sign = 0
for k in range(1, len(h1)):
    s = 1 if diff_h1[k] > 0 else (-1 if diff_h1[k] < 0 else 0)
    if prev_sign != 0 and s != 0 and s != prev_sign:
        last = k
    if s != 0:
        prev_sign = s
    last_cross[k] = last

m5c = [b[4] for b in bars]
ema20_m5 = ema(m5c, 20)
ema50_m5 = ema(m5c, 50)

def ema_ok(mode, sig, i, j):
    """True jika sinyal lolos filter EMA."""
    if mode == "F1":
        d = diff_h1[j]
        return (sig == "BUY" and d > 0) or (sig == "SELL" and d < 0)
    if mode == "F2":
        d = diff_h1[j]
        aligned = (sig == "BUY" and d > 0) or (sig == "SELL" and d < 0)
        if not aligned:
            return False
        lc = last_cross[j]
        return lc is not None and (j - lc) <= 24
    if mode == "F3":
        d = ema20_m5[i] - ema50_m5[i]
        return (sig == "BUY" and d > 0) or (sig == "SELL" and d < 0)
    return True

def run_ema(mode, t_start, t_end):
    """Seperti B.run(V11) tapi dengan filter EMA; return (trades, suppressed)."""
    trades, suppressed = [], []
    live_pos = None
    runners, phantom = [], []
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
        if a <= 0:
            continue

        # resolve runners (taken) + phantom (suppressed) — same machinery
        for lst, is_ph in ((runners, False), (phantom, True)):
            for r in lst[:]:
                d = r["dir"]; entry = r["entry"]; risk = r["risk"]
                sl = entry if r["tp1_hit"] else r["sl"]
                tp3, tp1 = r["tp3"], r["tp1"]
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
                    (trades if not is_ph else suppressed).append(r)
                    lst.remove(r)

        # live_pos gates new signals (only taken trades gate)
        if live_pos is not None:
            d = live_pos["dir"]; sl = live_pos["sl"]; tp1 = live_pos["tp1"]
            if d == "BUY":
                hit_sl = l <= sl; hit_tp1 = h >= tp1
            else:
                hit_sl = h >= sl; hit_tp1 = l <= tp1
            expired = ts - live_pos["ts"] >= 48 * 3600
            if hit_sl:
                last_sl_ts = ts; live_pos = None
                suppress_until = ts
            elif hit_tp1 or expired:
                live_pos = None
                suppress_until = ts

        # new signal (v1.1: h4 filter + transition-only + one-position)
        if live_pos is None and ts >= suppress_until:
            sig = B.sig_of(c, upper, lower)
            sig_prev = B.sig_of(bars[i - 1][4], upper, lower)
            if sig is None or sig == sig_prev:
                continue
            tr = B.h4_trend(j)
            if tr is None:
                continue
            if not ((sig == "BUY" and tr == "BULLISH") or
                    (sig == "SELL" and tr == "BEARISH")):
                continue
            risk = 1.5 * a
            entry = c
            if sig == "BUY":
                sl, tp1, tp3 = entry - risk, entry + risk, entry + 2 * risk
            else:
                sl, tp1, tp3 = entry + risk, entry - risk, entry - 2 * risk
            trade = {"dir": sig, "ts": ts, "entry": entry, "sl": sl,
                     "tp1": tp1, "tp3": tp3, "risk": risk,
                     "tp1_hit": False, "r_full": None}
            if ema_ok(mode, sig, i, j):
                live_pos = {"dir": sig, "ts": ts, "sl": sl, "tp1": tp1}
                runners.append(trade)
            else:
                phantom.append(trade)  # suppressed: tracked, doesn't gate
    return trades, suppressed

def pf_of(trades):
    rs = [t["r_full"] for t in trades if t["r_full"] is not None]
    gw = sum(r for r in rs if r > 0); gl = -sum(r for r in rs if r <= 0)
    return (gw / gl if gl > 0 else float("inf")), rs

def U(s):
    return calendar.timegm(datetime.datetime.strptime(s, "%Y-%m-%d %H:%M").timetuple())

if __name__ == "__main__":
    JAN = U("2026-01-01 00:00"); SEP = U("2026-09-01 00:00"); END = t5[-1] + 1
    results = {}
    for mode, label in [(None, "v1.1 BASELINE"), ("F1", "F1 EMA state H1"),
                        ("F2", "F2 EMA fresh-cross H1"), ("F3", "F3 EMA state M5")]:
        for pname, ps, pe in [("Jan-Oct", JAN, END), ("Sep-Oct", SEP, END)]:
            tr, sup = run_ema(mode, ps, pe)
            pf, rs = pf_of(tr)
            w = sum(1 for r in rs if r > 0) / len(rs) * 100 if rs else 0
            eq = peak = mdd = 0.0
            for r in rs:
                eq += r; peak = max(peak, eq); mdd = max(mdd, peak - eq)
            spf, srs = pf_of(sup)
            print(f"{label:18s} {pname:7s}: n={len(tr):3d} win={w:4.1f}% PF={pf:.2f} "
                  f"avgR={sum(rs)/len(rs):+.2f} totR={sum(rs):+.1f} maxDD={mdd:.1f} "
                  f"| suppressed n={len(sup):3d} PF_sup={spf:.2f}")
            results[(label, pname)] = (len(tr), w, pf, sum(rs), mdd, len(sup), spf)
    import json
    json.dump({f"{k[0]}|{k[1]}": v for k, v in results.items()},
              open("/tmp/ema_filter_results.json", "w"))
