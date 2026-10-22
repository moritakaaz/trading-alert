#!/usr/bin/env python3
"""buy_variants_backtest.py — offline research (2026-10-23, user-approved).

Question (from live journal review 2026-10-23): in the live journal the
double-top/bottom PATTERN side splits hard — SELL +3.57R / PF 1.17 (n=46)
vs BUY -6.25R / PF 0.56 (n=25), while the all-time -19.35R is mostly the
already-killed Donchian trigger (-16.67R). Does the bigger Jan-Oct sample
agree, and would restricting BUY help?

Variants (all start from the SAME v2.4-final pattern scan, FINAL_PARAMS
sep>=3 / depth 0.5 / tol 0.25, close-confirmed, clean check, one-position
engine copied in double_top_bottom_backtest.run_dtb):
  BASE          all signals, no filter (≈ live v2.7 behaviour, except the
                research engine is one-position-at-a-time while live is
                multi-position since v2.4 — relative comparison only)
  SELL-ONLY     BUY signals removed entirely
  BUY+EMA-H1    BUY kept only if H1 EMA20 > EMA50 at confirmation bar;
                SELL unrestricted (asymmetric, mirrors the proposal)
  EMA-BOTH      both directions must align with H1 EMA20/50 (extra context)
  BUY+GRADE-AB  BUY kept only if pattern Grade score >= 55 (A/B);
                SELL unrestricted. Grade = replica of the live v2.4
                score_pattern (peak match 25 + RSI div 20 + height 15 +
                symmetry 10 + prior trend 15, rescaled /85*100), using the
                H1 ATR at p2 as a1 (live uses current H1 ATR — documented
                approximation).
  GRADE-AB-BOTH both directions Grade A/B only (extra context)

Harness validation: the metadata scan below must reproduce
double_top_bottom_backtest.scan_patterns(**FINAL_PARAMS) entry_of EXACTLY
(same signal bars, same directions) before any variant number is trusted.

Data: PAXGUSDT M5 (Binance Vision zips via fix6sl_backtest loader),
forex-hours filtered by the loader. Proxy for XAUUSD — spreads/slippage
not modelled. READ-ONLY vs live.
Output: buy_variants_RESULTS.md
"""
import sys, calendar, datetime, bisect
sys.path.insert(0, "/home/hatch/workspace/trading-ea/research")
import double_top_bottom_backtest as D

bars, t5 = D.bars, D.t5
H = [b[2] for b in bars]; L = [b[3] for b in bars]; C = [b[4] for b in bars]
n5 = len(bars)
FP = D.FINAL_PARAMS if hasattr(D, "FINAL_PARAMS") else dict(sep_min=3, depth_mult=0.5, tol_mult=0.25)


def rsi_series(closes, period=14):
    # Wilder's RSI — verbatim replica of the live engine's rsi_series
    n = len(closes)
    out = [50.0] * n
    if n <= period:
        return out
    gains = [0.0] * n; losses = [0.0] * n
    for i in range(1, n):
        d = closes[i] - closes[i-1]
        gains[i] = d if d > 0 else 0.0
        losses[i] = -d if d < 0 else 0.0
    ag = sum(gains[1:period+1]) / period
    al = sum(losses[1:period+1]) / period
    out[period] = 100.0 if al <= 0 else 100.0 - 100.0 / (1.0 + ag / al)
    for i in range(period+1, n):
        ag = (ag * (period-1) + gains[i]) / period
        al = (al * (period-1) + losses[i]) / period
        out[i] = 100.0 if al <= 0 else 100.0 - 100.0 / (1.0 + ag / al)
    return out


RSI = rsi_series(C)


def score_pattern(sig, p1, p2, xn, neck, a1):
    # Replica of live score_pattern (v2.4), a1 = H1 ATR at p2
    if sig == "SELL":
        ext = max(H[p1], H[p2])
        match = max(0.0, 1.0 - abs(H[p2]-H[p1]) / max(0.25*a1, 1e-9))
    else:
        ext = min(L[p1], L[p2])
        match = max(0.0, 1.0 - abs(L[p2]-L[p1]) / max(0.25*a1, 1e-9))
    s1 = 25.0 * match
    rsi_div = (RSI[p2] < RSI[p1]) if sig == "SELL" else (RSI[p2] > RSI[p1])
    s2 = 20.0 if rsi_div else 0.0
    h = abs(ext - neck)
    s4 = 15.0 * min(1.0, h / max(3.0*a1, 1e-9))
    l1, l2 = xn - p1, p2 - xn
    sym = min(l1, l2) / max(max(l1, l2), 1)
    s5 = 10.0 * sym
    lo_i = max(0, p1 - 60)
    if sig == "SELL":
        pre = min(L[lo_i:p1+1]) if lo_i < p1 else ext
        prior = max(0.0, ext - pre)
    else:
        pre = max(H[lo_i:p1+1]) if lo_i < p1 else ext
        prior = max(0.0, pre - ext)
    s6 = 15.0 * min(1.0, prior / max(h, 1e-9))
    score = int(round((s1+s2+s4+s5+s6) / 85.0 * 100.0))
    grade = "A" if score >= 75 else ("B" if score >= 55 else "C")
    return score, grade


def scan_with_meta(sep_min=3, depth_mult=0.5, tol_mult=0.25):
    """Exact replica of D.scan_patterns geometry, but records pattern
    metadata (p1, p2, xn, atr) per confirmed signal for grading."""
    is_peak = D.is_peak; is_valley = D.is_valley
    peaks = D.peaks; valleys = D.valleys
    entry_of = {}; meta = {}; used_p2 = set()
    for p2 in peaks:
        if p2 + 2 >= n5 or p2 in used_p2:
            continue
        j = D.h1_idx_at(t5[p2])
        if j < 61:
            continue
        a = D.atr_h1[j]
        if a <= 0:
            continue
        p1, vlo, vi = None, None, None
        for q in range(p2 - 5, max(p2 - 50, 1), -1):
            if not is_peak[q]:
                continue
            if abs(H[p2] - H[q]) > tol_mult * a:
                continue
            _seg = L[q+1:p2]
            if not _seg:
                continue
            _vlo = min(_seg)
            if min(H[q], H[p2]) - _vlo < depth_mult * a:
                continue
            _vi = q + 1 + _seg.index(_vlo)
            if _vi - q < sep_min or p2 - _vi < sep_min:
                continue
            p1, vlo, vi = q, _vlo, _vi
            break
        if p1 is None:
            continue
        if max(H[p1+1:p2]) > max(H[p1], H[p2]):
            continue
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
            meta[sig_idx] = dict(dir="SELL", p1=p1, p2=p2, xn=vi, neck=neck, atr=a)
    for p2 in valleys:
        if p2 + 2 >= n5 or p2 in used_p2:
            continue
        j = D.h1_idx_at(t5[p2])
        if j < 61:
            continue
        a = D.atr_h1[j]
        if a <= 0:
            continue
        p1, vhi, pi = None, None, None
        for q in range(p2 - 5, max(p2 - 50, 1), -1):
            if not is_valley[q]:
                continue
            if abs(L[p2] - L[q]) > tol_mult * a:
                continue
            _seg = H[q+1:p2]
            if not _seg:
                continue
            _vhi = max(_seg)
            if _vhi - max(L[q], L[p2]) < depth_mult * a:
                continue
            _pi = q + 1 + _seg.index(_vhi)
            if _pi - q < sep_min or p2 - _pi < sep_min:
                continue
            p1, vhi, pi = q, _vhi, _pi
            break
        if p1 is None:
            continue
        if min(L[p1+1:p2]) < min(L[p1], L[p2]):
            continue
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
            meta[sig_idx] = dict(dir="BUY", p1=p1, p2=p2, xn=pi, neck=neck, atr=a)
    return entry_of, meta


def U(s):
    return calendar.timegm(datetime.datetime.strptime(s, "%Y-%m-%d %H:%M").timetuple())


def tp1_stats(trades):
    """Journal-model R: TP1 hit = +1R, pre-TP1 SL = -1R, expiry = partial."""
    rs = []
    for t in trades:
        if t["r_full"] is None:
            continue
        rs.append(1.0 if t.get("tp1_hit") else t["r_full"])
    if not rs:
        return dict(n=0, win=0.0, pf=0.0, tot=0.0)
    gw = sum(r for r in rs if r > 0); gl = -sum(r for r in rs if r < 0)
    return dict(n=len(rs), win=sum(1 for r in rs if r > 0)/len(rs)*100,
                pf=gw/gl if gl > 0 else float("inf"), tot=sum(rs))


def fmt(s, s1):
    return (f"n={s['n']:3d} win={s['win']:4.1f}% PF={s['pf']:.2f} totR={s['tot']:+.1f} "
            f"maxDD={s['mdd']:.1f} | TP1-model: win={s1['win']:4.1f}% "
            f"PF={s1['pf']:.2f} totR={s1['tot']:+.1f}")


if __name__ == "__main__":
    JAN = U("2026-01-01 00:00"); SEP = U("2026-09-01 00:00"); END = t5[-1] + 1

    base_of, _, _, _, _, _ = D.scan_patterns(**FP)
    meta_of, meta = scan_with_meta(**FP)
    assert meta_of == base_of, "HARNESS MISMATCH: metadata scan != scan_patterns"
    print(f"HARNESS OK: metadata scan reproduces scan_patterns exactly "
          f"({len(base_of)} confirmed signals)", flush=True)

    for idx, m in meta.items():
        sc, gr = score_pattern(m["dir"], m["p1"], m["p2"], m["xn"], m["neck"], m["atr"])
        m["score"], m["grade"] = sc, gr

    def ema_h1_bull(idx):
        j = D.h1_idx_at(t5[idx])
        return j >= 61 and D.diff_h1[j] > 0

    def ema_h1_bear(idx):
        j = D.h1_idx_at(t5[idx])
        return j >= 61 and D.diff_h1[j] < 0

    variants = [
        ("BASE", lambda i, d: True),
        ("SELL-ONLY", lambda i, d: d == "SELL"),
        ("BUY+EMA-H1", lambda i, d: d == "SELL" or ema_h1_bull(i)),
        ("EMA-BOTH", lambda i, d: ema_h1_bull(i) if d == "BUY" else ema_h1_bear(i)),
        ("BUY+GRADE-AB", lambda i, d: d == "SELL" or meta[i]["score"] >= 55),
        ("GRADE-AB-BOTH", lambda i, d: meta[i]["score"] >= 55),
    ]
    for name, keep in variants:
        eof = {i: v for i, v in base_of.items() if keep(i, v[0])}
        tr, nraw, _ = D.run_dtb(eof, JAN, END, use_trend=False)
        s, s1 = D.stats(tr), tp1_stats(tr)
        print(f"{name:15s} Jan-Oct: {fmt(s, s1)}", flush=True)
        for d in ("BUY", "SELL"):
            sub = [t for t in tr if t["dir"] == d]
            if sub:
                print(f"                  {d}: {fmt(D.stats(sub), tp1_stats(sub))}", flush=True)
        tr2, _, _ = D.run_dtb(eof, SEP, END, use_trend=False)
        print(f"                  Sep-Oct: {fmt(D.stats(tr2), tp1_stats(tr2))}", flush=True)

    # descriptive: BASE trades by grade bucket
    tr, _, _ = D.run_dtb(base_of, JAN, END, use_trend=False)
    sig_ts = {}
    # map trade -> grade via its ts: find signal idx by ts
    ts2idx = {t5[i]: i for i in base_of}
    for gname, pred in [("Grade A (>=75)", lambda sc: sc >= 75),
                        ("Grade B (55-74)", lambda sc: 55 <= sc < 75),
                        ("Grade C (<55)", lambda sc: sc < 55)]:
        sub = []
        for t in tr:
            i = ts2idx.get(t["ts"])
            if i is not None and pred(meta[i]["score"]):
                sub.append(t)
        if sub:
            print(f"BASE by grade — {gname}: {fmt(D.stats(sub), tp1_stats(sub))}", flush=True)
