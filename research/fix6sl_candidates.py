#!/usr/bin/env python3
"""fix6sl_candidates.py — uji kandidat perbaikan vs baseline v1.1.
Kandidat (max 3), masing-masing diuji di Sep-Oct 2026 DAN Jan-Oct 2026 (cek overfit).
Yang SUDAH ditolak riset sebelumnya (filter sesi, SL 2.0x, TP1 0.75R) tidak diuji ulang.
"""
import fix6sl_backtest as B
import datetime, calendar

def U(s): return calendar.timegm(datetime.datetime.strptime(s, "%Y-%m-%d %H:%M").timetuple())
JAN = U("2026-01-01 00:00"); SEP = U("2026-09-01 00:00"); END = B.t5[-1] + 1
V11 = {"h4_filter": True, "transition_only": True, "one_position": True}

def diag_depth():
    """Diagnostik: performa trade berdasarkan breakout depth (data Jan-Oct, v1.1)."""
    tr = B.run(V11, JAN, END)
    shallow = [t for t in tr if t["depth_atr"] < 0.3]
    deep = [t for t in tr if t["depth_atr"] >= 0.3]
    print("--- Diagnostik depth (v1.1, Jan-Oct) ---")
    B.stats(shallow, "depth < 0.3 ATR")
    B.stats(deep, "depth >= 0.3 ATR")
    # distribusi depth untuk yang loss vs win
    import statistics
    lw = [t["depth_atr"] for t in tr if t["r_full"] > 0]
    ll = [t["depth_atr"] for t in tr if t["r_full"] <= 0]
    print(f"  median depth WIN: {statistics.median(lw):.2f} ATR, LOSS: {statistics.median(ll):.2f} ATR")

def diag_vol():
    """Diagnostik: performa berdasarkan rasio ATR vs median 20 (v1.1, Jan-Oct)."""
    tr = B.run(V11, JAN, END)
    # hitung rasio per trade
    def ratio(t):
        import bisect as bs
        i = bs.bisect_left(B.t5, t["ts"])
        hb = t["ts"] - (t["ts"] % 3600)
        j = bs.bisect_left(B.h1t, hb) - 1
        hist = sorted(B.atr_h1[max(14, j - 20):j])
        return t["atr"] / hist[len(hist)//2] if hist else 1.0
    hi = [t for t in tr if ratio(t) > 2.0]
    lo = [t for t in tr if ratio(t) <= 2.0]
    print("--- Diagnostik vol-ratio (v1.1, Jan-Oct) ---")
    B.stats(hi, "atr_ratio > 2.0 (ledakan volatilitas)")
    B.stats(lo, "atr_ratio <= 2.0")

if __name__ == "__main__":
    diag_depth()
    print()
    diag_vol()
    print()
    cands = {
        "BASE v1.1": V11,
        "C1 depth>=0.3 ATR": {**V11, "min_depth_atr": 0.3},
        "C2 cooldown 12h pasca-SL": {**V11, "cooldown_h": 12},
        "C3 skip vol-explosion (atr>2x med20)": {**V11, "vol_guard": 2.0},
    }
    for name, cfg in cands.items():
        print(f"=== {name} ===")
        B.stats(B.run(cfg, SEP, END), "  Sep-Oct 2026")
        B.stats(B.run(cfg, JAN, END), "  Jan-Oct 2026")
        print()
