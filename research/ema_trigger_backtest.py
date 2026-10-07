#!/usr/bin/env python3
"""ema_trigger_backtest.py — test TRIGGER = fresh EMA20/50 cross on H1 (T1) vs the Donchian trigger (v1.2).

User's idea (approved "gas", 2026-10-07): enter on an EMA20/50 H1 cross, not on a
Donchian breakout — because on the 07 Oct chart the cross preceded the Donchian signal by ~$80.
Honest priors: the standalone EMA-cross LOST on all 6 symbols (early-Oct research),
and F2 (fresh-cross filter) failed. This test is fair: if it wins, it wins; if it loses, it loses.

T1 design (all other elements IDENTICAL to v1.2 for a fair comparison):
- Cross: sign(diff H1) changes on a completed H1 bar (exact F2 definition).
  Cross up = BUY, cross down = SELL. A cross is known when the H1 bar closes.
- Entry: the FIRST M5 close after that H1 cross bar closes (no lookahead).
- The H4 (SMA15) filter stays on, as in v1.2 (main variant); a diagnostic
  variant without the H4 filter is also run.
- The EMA-state filter is NOT used (redundant with the cross trigger).
- Identical risk management: SL 1.5xATR(H1), TP1 1R / TP2 1.5R / TP3 2R (full TP3=2R
  as r_full; TP1 touch -> SL to breakeven), one-position-at-a-time,
  SL / TP1 / 48h-expiry resolution, intrabar SL priority — the runner machinery is exactly run_ema.
- Transition-only: one cross = one signal; a cross while a position is active is discarded.

READ-ONLY on the live system. Output: ema_trigger_RESULTS.md
"""
import sys, calendar, datetime, bisect
sys.path.insert(0, "/home/hatch/workspace/trading-ea/research")
import fix6sl_backtest as B
import ema_filter_backtest as F  # run_ema = baseline v1.2 (F1); __main__ guarded

bars, t5, h1, h1t, atr_h1 = B.bars, B.t5, B.h1, B.h1t, B.atr_h1

# --- EMA20/50 + cross detection (exact F2 definition in ema_filter_backtest.py) ---
h1c = [b[4] for b in h1]
diff_h1 = [a - b for a, b in zip(F.ema(h1c, 20), F.ema(h1c, 50))]
cross_dir = [None] * len(h1)  # "BUY" (cross up) / "SELL" (cross down) at H1 bar index
prev_sign = 0
for k in range(1, len(h1)):
    s = 1 if diff_h1[k] > 0 else (-1 if diff_h1[k] < 0 else 0)
    if prev_sign != 0 and s != 0 and s != prev_sign:
        cross_dir[k] = "BUY" if s > 0 else "SELL"
    if s != 0:
        prev_sign = s

# entry: index of the first M5 bar that closes AFTER the H1 cross bar closes
entry_of = {}  # i_m5 -> (dir, j_h1)
for j, d in enumerate(cross_dir):
    if d is None or j < 61:
        continue
    i = bisect.bisect_left(t5, h1t[j] + 3600)
    if i < len(t5):
        entry_of[i] = (d, j)


def run_t1(use_h4, t_start, t_end):
    """T1: trigger = EMA cross. Return (trades, n_cross_raw)."""
    trades = []
    live_pos = None
    runners = []
    suppress_until = 0
    last_sl_ts = 0
    n_cross_raw = 0
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

        # resolve runners — exact run_ema machinery + diagnostic ts recording
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
                if not r["tp1_hit"] and l <= tp1:
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

        # live_pos gate — exactly like run_ema
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

        # new signal: TRIGGER = EMA cross (not Donchian breakout)
        if i in entry_of:
            n_cross_raw += 1
        if live_pos is None and ts >= suppress_until and i in entry_of:
            sig, jc = entry_of[i]
            if use_h4:
                tr = B.h4_trend(jc)
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
                     "tp1_hit": False, "tp1_ts": None,
                     "r_full": None, "close_ts": None}
            live_pos = {"dir": sig, "ts": ts, "sl": sl, "tp1": tp1}
            runners.append(trade)
    return trades, n_cross_raw


def pf_of(trades):
    rs = [t["r_full"] for t in trades if t["r_full"] is not None]
    gw = sum(r for r in rs if r > 0); gl = -sum(r for r in rs if r <= 0)
    return (gw / gl if gl > 0 else float("inf")), rs


def stats(trades):
    pf, rs = pf_of(trades)
    n = len(rs)
    w = sum(1 for r in rs if r > 0) / n * 100 if n else 0
    avg = sum(rs) / n if n else 0
    tot = sum(rs)
    eq = peak = mdd = 0.0
    for r in rs:
        eq += r; peak = max(peak, eq); mdd = max(mdd, peak - eq)
    sl_tr = [t for t in trades if t["r_full"] == -1.0]
    has_ts = all(t.get("close_ts") for t in trades)
    if has_ts and sl_tr:
        whip = sum(1 for t in sl_tr if (t["close_ts"] - t["ts"]) / 3600 <= 12)
        whip_pct = whip / len(sl_tr) * 100
        sl_ts = [(t["close_ts"] - t["ts"]) / 3600 for t in sl_tr]
        avg_sl = sum(sl_ts) / len(sl_ts)
    else:
        whip_pct, avg_sl = float("nan"), float("nan")
    tp1_list = [(t["tp1_ts"] - t["ts"]) / 3600 for t in trades if t.get("tp1_ts")]
    avg_tp1 = sum(tp1_list) / len(tp1_list) if tp1_list else float("nan")
    return dict(n=n, win=w, pf=pf, avg=avg, tot=tot, mdd=mdd,
                whip_pct=whip_pct, avg_tp1_h=avg_tp1, avg_sl_h=avg_sl)


def U(s):
    return calendar.timegm(datetime.datetime.strptime(s, "%Y-%m-%d %H:%M").timetuple())


if __name__ == "__main__":
    JAN = U("2026-01-01 00:00"); SEP = U("2026-09-01 00:00"); END = t5[-1] + 1
    print(f"total H1 crosses (j>=61): {sum(1 for d in cross_dir if d)}", flush=True)
    for label, fn in [("v1.2 BASELINE (Donchian trigger)", lambda ps, pe: F.run_ema("F1", ps, pe)[0]),
                      ("T1 EMA-cross trigger +H4", lambda ps, pe: run_t1(True, ps, pe)[0]),
                      ("T1 EMA-cross trigger no-H4", lambda ps, pe: run_t1(False, ps, pe)[0])]:
        for pname, ps, pe in [("Jan-Oct", JAN, END), ("Sep-Oct", SEP, END)]:
            tr = fn(ps, pe)
            s = stats(tr)
            print(f"{label:34s} {pname:7s}: n={s['n']:3d} win={s['win']:4.1f}% PF={s['pf']:.2f} "
                  f"avgR={s['avg']:+.2f} totR={s['tot']:+.1f} maxDD={s['mdd']:.1f} "
                  f"| whipsaw(<=12H1)={s['whip_pct']:.0f}% avgTP1={s['avg_tp1_h']:.1f}h avgSL={s['avg_sl_h']:.1f}h",
                  flush=True)
    # raw cross frequency per period (diagnostic)
    for pname, ps, pe in [("Jan-Oct", JAN, END), ("Sep-Oct", SEP, END)]:
        _, nraw = run_t1(True, ps, pe)
        print(f"cross events {pname}: {nraw}", flush=True)
