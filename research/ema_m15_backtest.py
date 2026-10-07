#!/usr/bin/env python3
"""ema_m15_backtest.py — uji EMA20/50 STATE di M15 sebagai filter tambahan
pada strategi XAUUSD v1.2 (v1.1 + filter EMA20/50 state @H1, live sejak 2026-10-07).

Basis: ema_filter_backtest.py (pola run_ema, harness tervalidasi fix6sl_backtest).
READ-ONLY terhadap sistem live.

Varian (sinyal harus lolos filter H4 dulu, seperti live):
  v12 : baseline v1.2 = v1.1 + EMA20/50 state @H1
  G1  : v1.2 + EMA20/50 state @M15 (H4 + EMA-H1 + EMA-M15)
  G2p : v1.1 + EMA20/50 state @M15 MENGGANTIKAN filter EMA-H1 (tanpa EMA-H1)

M15 diresample dari bar M5 (pola sama seperti H1 di fix6sl_backtest).
Tanpa lookahead: untuk sinyal di bar M5 index i (open ts), dipakai bar M15
terakhir yang SUDAH close: k = bisect_left(m15t, ts - ts%900) - 1.

Diagnostik: tiap sinyal kandidat dicatat kombinasi (h1_ok, m15_ok) untuk
mengukur redundansi kedua filter; sinyal ter-suppress dijalankan sebagai
phantom trade per filter penyebabnya (PF_sup).
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
    for i in range(period - 1):  # backfill warmup
        out[i] = out[period - 1]
    return out

# --- M15 resample dari M5 (pola sama seperti H1 di fix6sl_backtest) ---
m15 = []
bkt = None
for t, o, h, l, c in bars:
    mb = t - (t % 900)
    if bkt is None or bkt[0] != mb:
        if bkt:
            m15.append(bkt)
        bkt = [mb, o, h, l, c]
    else:
        bkt[2] = max(bkt[2], h)
        bkt[3] = min(bkt[3], l)
        bkt[4] = c
if bkt:
    m15.append(bkt)
m15t = [b[0] for b in m15]
print(f"M15: {len(m15)}", flush=True)

m15c = [b[4] for b in m15]
diff_m15 = [a - b for a, b in zip(ema(m15c, 20), ema(m15c, 50))]

h1c = [b[4] for b in h1]
diff_h1 = [a - b for a, b in zip(ema(h1c, 20), ema(h1c, 50))]

def run_m15(mode, t_start, t_end):
    """Mirror run_ema; mode in {'v12','G1','G2p'}.
    Return (trades, sup_h1, sup_m15, combos) dengan combos = dict
    {(h1_ok, m15_ok): count} atas semua sinyal kandidat pasca-H4."""
    trades, sup_h1, sup_m15 = [], [], []
    combos = {(True, True): 0, (True, False): 0, (False, True): 0, (False, False): 0}
    live_pos = None
    runners, phantom = [], []
    suppress_until = 0
    last_sl_ts = 0
    i0 = bisect.bisect_left(t5, t_start)
    i1 = bisect.bisect_left(t5, t_end)
    for i in range(max(i0, 60), i1):
        ts = t5[i]
        o, h, l, c = bars[i][1], bars[i][2], bars[i][3], bars[i][4]
        hb = ts - (ts % 3600)
        j = bisect.bisect_left(h1t, hb) - 1
        if j < 61:
            continue
        mb = ts - (ts % 900)
        k = bisect.bisect_left(m15t, mb) - 1
        if k < 1:
            continue
        win = h1[j - 47:j + 1]
        upper = max(b[2] for b in win)
        lower = min(b[3] for b in win)
        a = atr_h1[j]
        if a <= 0:
            continue

        # resolve runners (taken) + phantom (suppressed)
        for lst, is_ph in ((runners, False), (phantom, True)):
            for r in lst[:]:
                d = r["dir"]
                entry = r["entry"]
                risk = r["risk"]
                sl = entry if r["tp1_hit"] else r["sl"]
                tp3, tp1 = r["tp3"], r["tp1"]
                if d == "BUY":
                    hit_sl = l <= sl
                    hit_tp3 = h >= tp3
                    if not r["tp1_hit"] and h >= tp1:
                        r["tp1_hit"] = True
                else:
                    hit_sl = h >= sl
                    hit_tp3 = l <= tp3
                    if not r["tp1_hit"] and l <= tp1:
                        r["tp1_hit"] = True
                expired = ts - r["ts"] >= 48 * 3600
                done = False
                if hit_sl:
                    r["r_full"] = 0.0 if r["tp1_hit"] else -1.0
                    done = True
                elif hit_tp3:
                    r["r_full"] = 2.0
                    done = True
                elif expired:
                    r["r_full"] = (c - entry) / risk if d == "BUY" else (entry - c) / risk
                    done = True
                if done:
                    if not is_ph:
                        trades.append(r)
                    else:
                        if "h1" in r["why"]:
                            sup_h1.append(r)
                        if "m15" in r["why"]:
                            sup_m15.append(r)
                    lst.remove(r)

        # live_pos gates new signals (only taken trades gate)
        if live_pos is not None:
            d = live_pos["dir"]
            sl = live_pos["sl"]
            tp1 = live_pos["tp1"]
            if d == "BUY":
                hit_sl = l <= sl
                hit_tp1 = h >= tp1
            else:
                hit_sl = h >= sl
                hit_tp1 = l <= tp1
            expired = ts - live_pos["ts"] >= 48 * 3600
            if hit_sl:
                last_sl_ts = ts
                live_pos = None
                suppress_until = ts
            elif hit_tp1 or expired:
                live_pos = None
                suppress_until = ts

        # new signal (v1.1 core: h4 filter + transition-only + one-position)
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
                     "tp1_hit": False, "r_full": None, "why": set()}

            d_h1 = diff_h1[j]
            h1_ok = (sig == "BUY" and d_h1 > 0) or (sig == "SELL" and d_h1 < 0)
            d_m15 = diff_m15[k]
            m15_ok = (sig == "BUY" and d_m15 > 0) or (sig == "SELL" and d_m15 < 0)
            combos[(h1_ok, m15_ok)] += 1

            if mode == "v12":
                take, why = h1_ok, (set() if h1_ok else {"h1"})
            elif mode == "G1":
                take = h1_ok and m15_ok
                why = set()
                if not h1_ok:
                    why.add("h1")
                if not m15_ok:
                    why.add("m15")
            elif mode == "G2p":
                take, why = m15_ok, (set() if m15_ok else {"m15"})
            else:
                raise ValueError(mode)

            if take:
                live_pos = {"dir": sig, "ts": ts, "sl": sl, "tp1": tp1}
                runners.append(trade)
            else:
                trade["why"] = why
                phantom.append(trade)  # suppressed: tracked, doesn't gate
    return trades, sup_h1, sup_m15, combos

def pf_of(trades):
    rs = [t["r_full"] for t in trades if t["r_full"] is not None]
    gw = sum(r for r in rs if r > 0)
    gl = -sum(r for r in rs if r <= 0)
    return (gw / gl if gl > 0 else float("inf")), rs

def U(s):
    return calendar.timegm(datetime.datetime.strptime(s, "%Y-%m-%d %H:%M").timetuple())

if __name__ == "__main__":
    JAN = U("2026-01-01 00:00")
    SEP = U("2026-09-01 00:00")
    END = t5[-1] + 1
    results = {}
    combos_all = {}
    for mode, label in [("v12", "v1.2 BASELINE (H4+EMA-H1)"),
                        ("G1", "G1 v1.2 + EMA-M15"),
                        ("G2p", "G2p v1.1 + EMA-M15 (ganti H1)")]:
        for pname, ps, pe in [("Jan-Oct", JAN, END), ("Sep-Oct", SEP, END)]:
            tr, sh1, sm15, combos = run_m15(mode, ps, pe)
            pf, rs = pf_of(tr)
            w = sum(1 for r in rs if r > 0) / len(rs) * 100 if rs else 0
            eq = peak = mdd = 0.0
            for r in rs:
                eq += r
                peak = max(peak, eq)
                mdd = max(mdd, peak - eq)
            ph1, _ = pf_of(sh1)
            pm15, _ = pf_of(sm15)
            print(f"{label:28s} {pname:7s}: n={len(tr):3d} win={w:4.1f}% PF={pf:.2f} "
                  f"avgR={sum(rs)/len(rs):+.2f} totR={sum(rs):+.1f} maxDD={mdd:.1f} "
                  f"| supH1 n={len(sh1):3d} PF={ph1:.2f} | supM15 n={len(sm15):3d} PF={pm15:.2f}")
            results[(label, pname)] = (len(tr), w, pf, sum(rs) / len(rs), sum(rs), mdd,
                                       len(sh1), ph1, len(sm15), pm15)
            if pname == "Jan-Oct":
                combos_all[label] = combos
    print("\nRedundansi filter (sinyal kandidat pasca-H4, Jan-Okt):")
    for label, cb in combos_all.items():
        tt = sum(cb.values())
        tT = cb[(True, True)] + cb[(True, False)]
        tF = cb[(False, True)] + cb[(False, False)]
        mT = cb[(True, True)] + cb[(False, True)]
        print(f"  {label:28s}: total={tt} | H1 lolos={tT} (M15 buang {cb[(True, False)]} = "
              f"{cb[(True, False)]/tT*100:.1f}% di antaranya) | M15 lolos={mT} (H1 buang "
              f"{cb[(False, True)]} = {cb[(False, True)]/mT*100:.1f}% di antaranya) | "
              f"keduanya buang={cb[(False, False)]}")
    import json
    json.dump({f"{k[0]}|{k[1]}": v for k, v in results.items()},
              open("/tmp/ema_m15_results.json", "w"))
    json.dump({k: {str(kk): vv for kk, vv in v.items()} for k, v in combos_all.items()},
              open("/tmp/ema_m15_combos.json", "w"))
