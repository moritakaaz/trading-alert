#!/usr/bin/env python3
"""
Compare XAUUSD trend-strategy logics on GC=F (gold futures, XAUUSD proxy).
Engine: max 1 position, long+short, entries at next-bar open after a signal
on a closed bar, ATR-based SL/TP checked intrabar (SL first if both hit),
$0.40 spread per round trip, fixed 0.01 lot (=> $1 P/L per $1 move).
Opposite signal closes the position (no immediate reversal) - like GoldTrendEA.
"""
import json, datetime, math, sys

DATA = "/tmp/bt/gc_1h_1y.json"
SPREAD = 0.40  # dollars per round trip at 0.01 lot
WARMUP = 260

# ---------------------------------------------------------------- data
def load_bars(path):
    d = json.load(open(path))
    r = d["chart"]["result"][0]
    ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    bars = []
    for i, t in enumerate(ts):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, l, c):
            continue
        bars.append({"t": t, "o": o, "h": h, "l": l, "c": c})
    return bars

# ---------------------------------------------------------- indicators
def ema_list(vals, p):
    k = 2.0 / (p + 1)
    e = vals[0]; out = [e]
    for v in vals[1:]:
        e = v * k + e * (1 - k); out.append(e)
    return out

def atr_list(bars, p=14):
    n = len(bars); trs = []
    for i in range(1, n):
        h, l, pc = bars[i]["h"], bars[i]["l"], bars[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    a = [None] * n
    s = sum(trs[:p]) / p; a[p] = s
    for i in range(p + 1, n):
        s = (s * (p - 1) + trs[i - 1]) / p; a[i] = s
    return a

def rsi_list(bars, p=14):
    n = len(bars); gains = []; losses = []
    for i in range(1, n):
        ch = bars[i]["c"] - bars[i - 1]["c"]
        gains.append(max(ch, 0)); losses.append(max(-ch, 0))
    r = [None] * n
    ag = sum(gains[:p]) / p; al = sum(losses[:p]) / p
    r[p] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(p + 1, n):
        ag = (ag * (p - 1) + gains[i - 1]) / p
        al = (al * (p - 1) + losses[i - 1]) / p
        r[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return r

def adx_list(bars, p=14):
    n = len(bars); pdm = []; mdm = []; tr = []
    for i in range(1, n):
        up = bars[i]["h"] - bars[i - 1]["h"]; dn = bars[i - 1]["l"] - bars[i]["l"]
        pdm.append(up if (up > dn and up > 0) else 0)
        mdm.append(dn if (dn > up and dn > 0) else 0)
        h, l, pc = bars[i]["h"], bars[i]["l"], bars[i - 1]["c"]
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    spdm = [None] * n; smdm = [None] * n; str_ = [None] * n
    dx = [None] * n; adx = [None] * n
    spdm[p] = sum(pdm[:p]); smdm[p] = sum(mdm[:p]); str_[p] = sum(tr[:p])
    for i in range(p + 1, n):
        spdm[i] = spdm[i - 1] - spdm[i - 1] / p + pdm[i - 1]
        smdm[i] = smdm[i - 1] - smdm[i - 1] / p + mdm[i - 1]
        str_[i] = str_[i - 1] - str_[i - 1] / p + tr[i - 1]
        pdi = 100 * spdm[i] / str_[i] if str_[i] else 0
        mdi = 100 * smdm[i] / str_[i] if str_[i] else 0
        dx[i] = 100 * abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) else 0
    adx[2 * p] = sum(dx[p + 1:2 * p + 1]) / p
    for i in range(2 * p + 1, n):
        adx[i] = (adx[i - 1] * (p - 1) + dx[i]) / p
    return adx

def supertrend(bars, p=10, mult=3.0):
    n = len(bars); atr = atr_list(bars, p)
    st = [None] * n; up = [None] * n; dn = [None] * n
    for i in range(1, n):
        if atr[i] is None:
            continue
        mid = (bars[i]["h"] + bars[i]["l"]) / 2
        bub = mid + mult * atr[i]; blb = mid - mult * atr[i]
        if up[i - 1] is None:
            up[i] = blb; dn[i] = bub
        else:
            up[i] = blb if (blb > up[i - 1] or bars[i - 1]["c"] < up[i - 1]) else up[i - 1]
            dn[i] = bub if (bub < dn[i - 1] or bars[i - 1]["c"] > dn[i - 1]) else dn[i - 1]
        if st[i - 1] is None:
            st[i] = 1 if bars[i]["c"] > dn[i] else (-1 if bars[i]["c"] < up[i] else 1)
        elif st[i - 1] == 1:
            st[i] = -1 if bars[i]["c"] < up[i] else 1
        else:
            st[i] = 1 if bars[i]["c"] > dn[i] else -1
    return st

# --------------------------------------------------------------- engine
def run(bars, sig_fn, sl_mult, tp_mult, atr):
    trades = []          # (exit_epoch, net_$, R)
    pos = None
    eq = 0.0; peak = 0.0; maxdd = 0.0
    cumR = 0.0; peakR = 0.0; maxddR = 0.0

    def close_pos(px, exit_t):
        nonlocal eq, peak, maxdd, cumR, peakR, maxddR
        gross = (px - pos["entry"]) * pos["dir"]
        net = gross - SPREAD
        R = net / pos["risk"]
        trades.append((exit_t, net, R))
        eq += net; cumR += R
        peak = max(peak, eq); maxdd = max(maxdd, peak - eq)
        peakR = max(peakR, cumR); maxddR = max(maxddR, peakR - cumR)

    for i in range(WARMUP, len(bars) - 1):
        b = bars[i]
        if pos is not None:                       # intrabar SL/TP, SL first
            hit = None
            if pos["dir"] == 1:
                if b["l"] <= pos["sl"]: hit = pos["sl"]
                elif b["h"] >= pos["tp"]: hit = pos["tp"]
            else:
                if b["h"] >= pos["sl"]: hit = pos["sl"]
                elif b["l"] <= pos["tp"]: hit = pos["tp"]
            if hit is not None:
                close_pos(hit, b["t"]); pos = None
        s = sig_fn(i)
        skipped_reverse = False
        if s != 0 and pos is not None and (
                (s == 1 and pos["dir"] == -1) or (s == -1 and pos["dir"] == 1)):
            close_pos(b["c"], b["t"]); pos = None
            skipped_reverse = True                # like the EA: wait, don't reverse
        if s != 0 and pos is None and not skipped_reverse and atr[i]:
            nb = bars[i + 1]
            entry = nb["o"]
            sld = sl_mult * atr[i]
            sl = entry - sld if s == 1 else entry + sld
            tp = entry + tp_mult * atr[i] if s == 1 else entry - tp_mult * atr[i]
            if (s == 1 and entry <= sl) or (s == -1 and entry >= sl):
                # gapped through SL at open -> instant scratch loss (spread)
                net = -SPREAD; R = net / sld
                trades.append((nb["t"], net, R))
                eq += net; cumR += R
                peak = max(peak, eq); maxdd = max(maxdd, peak - eq)
                peakR = max(peakR, cumR); maxddR = max(maxddR, peakR - cumR)
            else:
                pos = {"dir": s, "entry": entry, "sl": sl, "tp": tp, "risk": sld}
    if pos is not None:                           # close remainder at end
        px = bars[-1]["c"]
        gross = (px - pos["entry"]) * pos["dir"]
        net = gross - SPREAD; R = net / pos["risk"]
        trades.append((bars[-1]["t"], net, R))
        eq += net; cumR += R
        peak = max(peak, eq); maxdd = max(maxdd, peak - eq)
        peakR = max(peakR, cumR); maxddR = max(maxddR, peakR - cumR)
    return trades, eq, maxdd, cumR, maxddR

def pf_of(trades):
    gp = sum(t[1] for t in trades if t[1] > 0)
    gl = -sum(t[1] for t in trades if t[1] < 0)
    return gp / gl if gl > 0 else float("inf")

def summarize(name, trades, eq, maxdd, cumR, maxddR, t_mid):
    n = len(trades)
    wins = sum(1 for t in trades if t[1] > 0)
    h1 = [t for t in trades if t[0] < t_mid]
    h2 = [t for t in trades if t[0] >= t_mid]
    return {
        "name": name, "trades": n,
        "net_$": round(eq, 2), "PF": round(pf_of(trades), 2),
        "win%": round(100 * wins / n, 1) if n else 0,
        "avgR": round(cumR / n, 2) if n else 0,
        "maxDD_$": round(maxdd, 2), "maxDD_R": round(maxddR, 1),
        "PF_h1": round(pf_of(h1), 2), "n_h1": len(h1),
        "PF_h2": round(pf_of(h2), 2), "n_h2": len(h2),
    }

# ------------------------------------------------------------------ main
def main(path):
    bars = load_bars(path)
    t0 = datetime.datetime.fromtimestamp(bars[0]["t"], datetime.timezone.utc).strftime("%Y-%m-%d")
    t1 = datetime.datetime.fromtimestamp(bars[-1]["t"], datetime.timezone.utc).strftime("%Y-%m-%d")
    print(f"DATA: {path} | {len(bars)} bars | {t0} -> {t1}")
    closes = [b["c"] for b in bars]
    e20 = ema_list(closes, 20); e50 = ema_list(closes, 50); e200 = ema_list(closes, 200)
    atr = atr_list(bars, 14); adx = adx_list(bars, 14); rsi = rsi_list(bars, 14)
    st = supertrend(bars, 10, 3.0)
    hours = [datetime.datetime.fromtimestamp(b["t"], datetime.timezone.utc).hour for b in bars]

    def cross(i):
        if e20[i] > e50[i] and e20[i - 1] <= e50[i - 1]: return 1
        if e20[i] < e50[i] and e20[i - 1] >= e50[i - 1]: return -1
        return 0

    def donchian(i, n=24):
        hh = max(b["h"] for b in bars[i - n:i])
        ll = min(b["l"] for b in bars[i - n:i])
        if bars[i]["c"] > hh: return 1
        if bars[i]["c"] < ll: return -1
        return 0

    variants = [
        ("0 baseline EMA20/50 x",      lambda i: cross(i), 1.5, 3.0),
        ("1 Donchian(24) breakout",    lambda i: donchian(i), 1.5, 3.0),
        ("2 EMA cross + ADX>20",       lambda i: cross(i) if (adx[i] and adx[i] > 20) else 0, 1.5, 3.0),
        ("3 EMA cross, 07-21 UTC",     lambda i: cross(i) if 7 <= hours[i] < 21 else 0, 1.5, 3.0),
        ("4 RSI pullback in trend",    None, 1.5, 2.5),   # custom below
        ("5 Supertrend(10,3) flips",   None, 1.5, 3.0),   # custom below
        ("6 baseline SL2.0/TP4.0",     lambda i: cross(i), 2.0, 4.0),
    ]

    def rsi_sig(i):
        up = closes[i] > e200[i]; dn = closes[i] < e200[i]
        if up and rsi[i - 1] is not None and rsi[i - 1] < 35 and rsi[i] >= 35: return 1
        if dn and rsi[i - 1] is not None and rsi[i - 1] > 65 and rsi[i] <= 65: return -1
        return 0

    def st_sig(i):
        if st[i] is None or st[i - 1] is None: return 0
        if st[i] == 1 and st[i - 1] == -1: return 1
        if st[i] == -1 and st[i - 1] == 1: return -1
        return 0

    t_mid = (bars[0]["t"] + bars[-1]["t"]) / 2
    rows = []
    for name, fn, slm, tpm in variants:
        if fn is None:
            fn = rsi_sig if name.startswith("4") else st_sig
        trades, eq, maxdd, cumR, maxddR = run(bars, fn, slm, tpm, atr)
        rows.append(summarize(name, trades, eq, maxdd, cumR, maxddR, t_mid))
    hdr = ["name", "trades", "net_$", "PF", "win%", "avgR", "maxDD_$", "maxDD_R",
           "PF_h1", "n_h1", "PF_h2", "n_h2"]
    print(" | ".join(hdr))
    for r in rows:
        print(" | ".join(str(r[h]) for h in hdr))
    return rows

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else DATA)
