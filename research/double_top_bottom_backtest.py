#!/usr/bin/env python3
"""double_top_bottom_backtest.py — v2.0 calibration + "brutal" frequency tuning.

User spec (2026-10-08): M5 double top/bottom + 1 confirmation candle (neckline
break), trend filter M15+H1 EMA20/50 (both agree -> follow that direction only;
disagree -> both allowed). SL 1.5xATR(H1), TP1 1R / TP2 1.5R / TP3 2R,
one-position-at-a-time, SL-first intrabar, 48h expiry. User claims 68% manual
winrate and wants it live ("brutal" = more entries/day, experimental).

Pattern definition (no lookahead), parameterized:
- Swing fractal N=2 on M5: peak[i] if h[i] > h[i+-1], h[i+-2]; valley likewise.
- DOUBLE TOP (SELL): p1 < p2 chronologically, both confirmed peaks (p2+2 <= i);
  |p1-p2| <= TOL*ATR(H1 at p2); 5 <= p2-p1 <= 50 bars;
  valley = lowest low strictly between; min(p1,p2) - valley >= DEPTH*ATR(H1);
  valley index must sit >= SEP_MIN bars from both p1 and p2 (rejects tight chop).
  Neckline = valley low.
- DOUBLE BOTTOM (BUY): mirror.
- CONFIRMATION: first M5 bar k in (p2, p2+24] with close beyond neckline AND
  correct color (top: c < neckline and c < o; bottom: c > neckline and c > o).
  Entry = close[k]. One pattern = one signal (used_p2 dedupe, same as live).
- TREND FILTER at k: EMA20/50 H1 + EMA20/50 M15 (same def as F.ema). Both
  bullish -> BUY only; both bearish -> SELL only; disagree -> both allowed.

Trade engine: runner + live_pos gate copied verbatim from run_t1 in
ema_trigger_backtest.py (validated). READ-ONLY vs live.
Output: double_top_bottom_RESULTS.md

FINAL SETTING (2026-10-08 "brutal" tuning, winner of the variant sweep below):
  FINAL_PARAMS = dict(sep_min=3, depth_mult=0.5, tol_mult=0.25)
Rationale: highest trades/day (0.93) with PF>=1.1 and n>=100. The sep>=3 rule
still rejects the 1-2 bar chop the user flagged, but keeps the 3-4 bar
formations that carry the edge (sep>=5 tested PF 0.88 — unprofitable).
"""
FINAL_PARAMS = dict(sep_min=3, depth_mult=0.5, tol_mult=0.25)
import sys, calendar, datetime, bisect
sys.path.insert(0, "/home/hatch/workspace/trading-ea/research")
import fix6sl_backtest as B
import ema_filter_backtest as F

bars, t5, h1, h1t, atr_h1 = B.bars, B.t5, B.h1, B.h1t, B.atr_h1
WIB = datetime.timezone(datetime.timedelta(hours=7))
n5 = len(bars)

# --- M15 bars + EMA20/50 (same def as H1) ---
m15 = []
bkt = None
for t, o, h, l, c in bars:
    mb = t - (t % 900)
    if bkt is None or bkt[0] != mb:
        if bkt:
            m15.append(bkt)
        bkt = [mb, o, h, l, c]
    else:
        bkt[2] = max(bkt[2], h); bkt[3] = min(bkt[3], l); bkt[4] = c
if bkt:
    m15.append(bkt)
m15t = [b[0] for b in m15]
m15c = [b[4] for b in m15]
diff_m15 = [a - b for a, b in zip(F.ema(m15c, 20), F.ema(m15c, 50))]

# --- H1 EMA20/50 ---
h1c = [b[4] for b in h1]
diff_h1 = [a - b for a, b in zip(F.ema(h1c, 20), F.ema(h1c, 50))]

# --- M5 swing fractals N=2 ---
H = [b[2] for b in bars]
L = [b[3] for b in bars]
is_peak = [False] * n5
is_valley = [False] * n5
for i in range(2, n5 - 2):
    if H[i] > H[i-1] and H[i] > H[i-2] and H[i] > H[i+1] and H[i] > H[i+2]:
        is_peak[i] = True
    if L[i] < L[i-1] and L[i] < L[i-2] and L[i] < L[i+1] and L[i] < L[i+2]:
        is_valley[i] = True

peaks = [i for i in range(n5) if is_peak[i]]
valleys = [i for i in range(n5) if is_valley[i]]


def h1_idx_at(ts):
    hb = ts - (ts % 3600)
    return bisect.bisect_left(h1t, hb) - 1


def scan_patterns(sep_min=5, depth_mult=0.5, tol_mult=0.25):
    """Pattern scan -> entry_of {confirm_bar_idx: (dir, neck)}.
    Mirrors the live detect_dtb() in ~/hooks/scripts/xauusd_entry_m5.sh,
    including the SEP_MIN separation rule and used_p2 per-pattern dedupe."""
    entry_of = {}
    used_p2 = set()
    n_raw_top = n_raw_bot = 0
    examples = []

    for p2 in peaks:
        if p2 + 2 >= n5 or p2 in used_p2:
            continue
        j = h1_idx_at(t5[p2])
        if j < 61:
            continue
        a = atr_h1[j]
        if a <= 0:
            continue
        p1 = None
        for q in range(p2 - 5, max(p2 - 50, 1), -1):
            if is_peak[q]:
                p1 = q
                break
        if p1 is None:
            continue
        if abs(H[p2] - H[p1]) > tol_mult * a:
            continue
        seg = L[p1 + 1:p2]
        if not seg:
            continue
        vlo = min(seg)
        if min(H[p1], H[p2]) - vlo < depth_mult * a:
            continue
        vi = p1 + 1 + seg.index(vlo)
        if vi - p1 < sep_min or p2 - vi < sep_min:
            continue
        n_raw_top += 1
        used_p2.add(p2)
        neck = vlo
        sig_idx = None
        for k in range(p2 + 1, min(p2 + 25, n5)):
            o, c = bars[k][1], bars[k][4]
            if c < neck and c < o:
                sig_idx = k
                break
        if sig_idx is None or sig_idx < 60:
            continue
        if sig_idx not in entry_of:
            entry_of[sig_idx] = ("SELL", neck)
            if len(examples) < 8:
                examples.append(("DOUBLE TOP", p2, sig_idx, H[p1], H[p2], neck))

    for p2 in valleys:
        if p2 + 2 >= n5 or p2 in used_p2:
            continue
        j = h1_idx_at(t5[p2])
        if j < 61:
            continue
        a = atr_h1[j]
        if a <= 0:
            continue
        p1 = None
        for q in range(p2 - 5, max(p2 - 50, 1), -1):
            if is_valley[q]:
                p1 = q
                break
        if p1 is None:
            continue
        if abs(L[p2] - L[p1]) > tol_mult * a:
            continue
        seg = H[p1 + 1:p2]
        if not seg:
            continue
        vhi = max(seg)
        if vhi - max(L[p1], L[p2]) < depth_mult * a:
            continue
        pi = p1 + 1 + seg.index(vhi)
        if pi - p1 < sep_min or p2 - pi < sep_min:
            continue
        n_raw_bot += 1
        used_p2.add(p2)
        neck = vhi
        sig_idx = None
        for k in range(p2 + 1, min(p2 + 25, n5)):
            o, c = bars[k][1], bars[k][4]
            if c > neck and c > o:
                sig_idx = k
                break
        if sig_idx is None or sig_idx < 60:
            continue
        if sig_idx not in entry_of:
            entry_of[sig_idx] = ("BUY", neck)
            if len(examples) < 8:
                examples.append(("DOUBLE BOTTOM", p2, sig_idx, L[p1], L[p2], neck))

    return entry_of, n_raw_top, n_raw_bot, examples


def trend_ok(sig, ts):
    """M15+H1 EMA20/50 filter. Both agree -> that direction only; else both."""
    j = h1_idx_at(ts)
    if j < 61:
        return False
    mb = ts - (ts % 900)
    jm = bisect.bisect_left(m15t, mb) - 1
    if jm < 61:
        return False
    h_bull = diff_h1[j] > 0
    h_bear = diff_h1[j] < 0
    m_bull = diff_m15[jm] > 0
    m_bear = diff_m15[jm] < 0
    if h_bull and m_bull:
        return sig == "BUY"
    if h_bear and m_bear:
        return sig == "SELL"
    return True


def run_dtb(entry_of, t_start, t_end, use_trend=True):
    """Double-top/bottom engine. Return (trades, n_sig_raw, n_trend_blocked)."""
    trades = []
    live_pos = None
    runners = []
    suppress_until = 0
    n_sig_raw = 0
    n_blocked = 0
    i0 = bisect.bisect_left(t5, t_start)
    i1 = bisect.bisect_left(t5, t_end)
    for i in range(max(i0, 60), i1):
        ts = t5[i]
        o, h, l, c = bars[i][1], bars[i][2], bars[i][3], bars[i][4]
        hb = ts - (ts % 3600)
        j = bisect.bisect_left(h1t, hb) - 1
        if j < 61:
            continue
        a = atr_h1[j]
        if a <= 0:
            continue

        # resolve runners — verbatim from run_t1 (validated engine)
        for r in runners[:]:
            d = r["dir"]; entry = r["entry"]; risk = r["risk"]
            sl = entry if r["tp1_hit"] else r["sl"]
            tp3, tp1 = r["tp3"], r["tp1"]
            if d == "BUY":
                hit_sl = l <= sl; hit_tp3 = h >= tp3
                if not r["tp1_hit"] and h >= tp1:
                    r["tp1_hit"] = True; r["tp1_ts"] = ts
            else:
                hit_sl = h >= sl; hit_tp3 = l <= tp3
                if not r["tp1_hit"] and l <= tp3:
                    r["tp1_hit"] = True; r["tp1_ts"] = ts
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
                r["close_ts"] = ts
                trades.append(r)
                runners.remove(r)

        # live_pos gate — verbatim from run_t1
        if live_pos is not None:
            d = live_pos["dir"]; sl = live_pos["sl"]; tp1 = live_pos["tp1"]
            if d == "BUY":
                hit_sl = l <= sl; hit_tp1 = h >= tp1
            else:
                hit_sl = h >= sl; hit_tp1 = l <= tp1
            expired = ts - live_pos["ts"] >= 48 * 3600
            if hit_sl:
                live_pos = None
                suppress_until = ts
            elif hit_tp1 or expired:
                live_pos = None
                suppress_until = ts

        # new signal: double top/bottom confirmation
        if i in entry_of:
            n_sig_raw += 1
        if live_pos is None and ts >= suppress_until and i in entry_of:
            sig, neck = entry_of[i]
            if use_trend and not trend_ok(sig, ts):
                n_blocked += 1
                continue
            risk = 1.5 * a
            entry = c
            if sig == "BUY":
                sl, tp1, tp3 = entry - risk, entry + risk, entry + 2 * risk
            else:
                sl, tp1, tp3 = entry + risk, entry - risk, entry - 2 * risk
            trade = {"dir": sig, "ts": ts, "entry": entry, "sl": sl,
                     "tp1": tp1, "tp3": tp3, "risk": risk,
                     "tp1_hit": False, "tp1_ts": None,
                     "r_full": None, "close_ts": None}
            live_pos = {"dir": sig, "ts": ts, "sl": sl, "tp1": tp1}
            runners.append(trade)
    return trades, n_sig_raw, n_blocked


def stats(trades):
    rs = [t["r_full"] for t in trades if t["r_full"] is not None]
    gw = sum(r for r in rs if r > 0)
    gl = -sum(r for r in rs if r <= 0)
    pf = gw / gl if gl > 0 else float("inf")
    n = len(rs)
    w = sum(1 for r in rs if r > 0) / n * 100 if n else 0
    tp1r = sum(1 for t in trades if t.get("tp1_hit")) / n * 100 if n else 0
    avg = sum(rs) / n if n else 0
    tot = sum(rs)
    eq = peak = mdd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    sl_tr = [t for t in trades if t["r_full"] == -1.0]
    if sl_tr and all(t.get("close_ts") for t in trades):
        whip = sum(1 for t in sl_tr if (t["close_ts"] - t["ts"]) / 3600 <= 12)
        whip_pct = whip / len(sl_tr) * 100
    else:
        whip_pct = float("nan")
    return dict(n=n, win=w, tp1=tp1r, pf=pf, avg=avg, tot=tot, mdd=mdd,
                whip_pct=whip_pct)


def U(s):
    return calendar.timegm(datetime.datetime.strptime(s, "%Y-%m-%d %H:%M").timetuple())


if __name__ == "__main__":
    JAN = U("2026-01-01 00:00"); SEP = U("2026-09-01 00:00"); END = t5[-1] + 1
    DAYS = (END - JAN) / 86400.0

    variants = [
        ("BASE-tight sep5/dep.50/tol.25", dict(sep_min=5, depth_mult=0.5, tol_mult=0.25)),
        ("VAR-a sep>=3",                 dict(sep_min=3, depth_mult=0.5, tol_mult=0.25)),
        ("VAR-b depth 0.40xATR",         dict(sep_min=5, depth_mult=0.4, tol_mult=0.25)),
        ("VAR-c tol 0.30xATR",           dict(sep_min=5, depth_mult=0.5, tol_mult=0.30)),
    ]
    results = []
    for vname, kw in variants:
        entry_of, nrt, nrb, ex = scan_patterns(**kw)
        tr, nraw, nblk = run_dtb(entry_of, JAN, END, use_trend=True)
        s = stats(tr)
        tpd = s["n"] / DAYS
        results.append((vname, kw, s, tpd, nraw, nblk, nrt, nrb))
        print(f"{vname:28s} Jan-Oct: n={s['n']:3d} t/d={tpd:.2f} win={s['win']:4.1f}% "
              f"TP1hit={s['tp1']:4.1f}% PF={s['pf']:.2f} avgR={s['avg']:+.2f} "
              f"totR={s['tot']:+.1f} maxDD={s['mdd']:.1f} "
              f"| whipsaw={s['whip_pct']:.0f}% raw_sig={nraw} blocked={nblk} "
              f"patterns=({nrt},{nrb})", flush=True)

    # winner: highest trades/day with PF>=1.1 and n>=100, else PF>=1.0
    cand = [r for r in results if r[2]["pf"] >= 1.1 and r[2]["n"] >= 100]
    pool = cand or [r for r in results if r[2]["pf"] >= 1.0]
    winner = max(pool, key=lambda r: r[3]) if pool else None
    if winner:
        print(f"WINNER: {winner[0]} (t/d={winner[3]:.2f}, PF={winner[2]['pf']:.2f}, "
              f"n={winner[2]['n']})", flush=True)
    else:
        print("WINNER: none met PF>=1.0", flush=True)

    # Sep-Oct detail for the winner (or baseline if none)
    w = winner or results[0]
    entry_of, _, _, _ = scan_patterns(**w[1])
    tr, _, _ = run_dtb(entry_of, SEP, END, use_trend=True)
    s = stats(tr)
    print(f"WINNER Sep-Oct: n={s['n']:3d} win={s['win']:4.1f}% TP1hit={s['tp1']:4.1f}% "
          f"PF={s['pf']:.2f} totR={s['tot']:+.1f}", flush=True)
    tr, _, _ = run_dtb(entry_of, JAN, END, use_trend=True)
    for d in ("BUY", "SELL"):
        sub = [t for t in tr if t["dir"] == d]
        s = stats(sub)
        print(f"  {d}: n={s['n']:3d} win={s['win']:4.1f}% TP1hit={s['tp1']:4.1f}% "
              f"PF={s['pf']:.2f} totR={s['tot']:+.1f}", flush=True)
