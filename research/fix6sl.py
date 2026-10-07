#!/usr/bin/env python3
"""fix6sl.py — investigasi 6 SL beruntun XAUUSD (2026-10-05/06).
PART A: rekonstruksi konteks tiap trade yang loss.
READ-ONLY terhadap sistem live. Output: data untuk laporan.
"""
import csv, glob, zipfile, datetime, bisect, json

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
            print("skip", zf, str(e)[:60])
    # Oct 6 from API csv
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
        out.append((t, o, h, l, c))
    return out

bars = load_bars()
t5 = [b[0] for b in bars]
print(f"M5 bars: {len(bars)}, "
      f"{datetime.datetime.fromtimestamp(t5[0], datetime.timezone.utc):%Y-%m-%d} -> "
      f"{datetime.datetime.fromtimestamp(t5[-1], datetime.timezone.utc):%Y-%m-%d %H:%M}Z")

# resample M5 -> H1
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
print(f"H1 bars: {len(h1)}")

def atr14(h1c):
    trs = []
    for k in range(len(h1c) - 14, len(h1c)):
        h, l, pc = h1c[k][2], h1c[k][3], h1c[k-1][4]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / len(trs)

def h4_trend(h1c):
    # replicate live quirk: last 80 completed H1 bars, chunk in 4s from index 0
    seg = h1c[-80:]
    _h4 = []
    for _i in range(0, len(seg) - 3, 4):
        _grp = seg[_i:_i + 4]
        _h4.append((_grp[0][0], max(_b[2] for _b in _grp),
                    min(_b[3] for _b in _grp), _grp[-1][4]))
    if len(_h4) < 15:
        return None
    _sma = sum(_b[3] for _b in _h4[-15:]) / 15
    return "BULLISH" if _h4[-1][3] > _sma else "BEARISH"

def session_wib(ts):
    dt = datetime.datetime.fromtimestamp(ts, WIB)
    h = dt.hour + dt.minute / 60
    if 6 <= h < 14: return "Asia"
    if 14 <= h < 20.5: return "London"
    if h >= 20.5 or h < 4: return "New York"
    return "Off-hours"

def donchian(h1c, n=48):
    win = h1c[-n:]
    return max(b[2] for b in win), min(b[3] for b in win)

# 6 loss trades: (alert_time_utc, signal, entry_ref, sl_d)
trades = [
    ("2026-10-05T07:50:00Z", "BUY", 4162.15, 15.39),
    ("2026-10-05T08:10:00Z", "BUY", 4168.28, 16.95),
    ("2026-10-05T08:45:00Z", "BUY", 4165.04, 16.95),
    ("2026-10-05T17:10:00Z", "SELL", 4126, 23),
    ("2026-10-06T02:35:00Z", "SELL", 4125, 19),
    ("2026-10-06T12:00:00Z", "BUY", 4177, 21),
]

print("\n" + "=" * 100)
print("PART A — konteks tiap trade yang loss")
print("=" * 100)
for iso, sig, entry, sl_d in trades:
    ts = int(datetime.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
             .replace(tzinfo=datetime.timezone.utc).timestamp())
    i = bisect.bisect_left(t5, ts)
    if i >= len(t5) or t5[i] != ts:
        print(f"{iso}: BAR NOT FOUND"); continue
    o, h, l, c = bars[i][1], bars[i][2], bars[i][3], bars[i][4]
    hb = ts - (ts % 3600)
    j = bisect.bisect_left(h1t, hb) - 1
    h1c = h1[:j + 1]  # completed H1 strictly before signal bar's hour
    # live uses h1c strictly < hour_start; h1t[j] is the bar < hb? bisect_left(hb)-1 gives bar with t < hb
    upper, lower = donchian(h1c)
    mid = (upper + lower) / 2
    a = atr14(h1c)
    # ATR history (last 20 H1 closes) for regime comparison
    atr_hist = [atr14(h1c[:k+1]) for k in range(len(h1c)-20, len(h1c))]
    atr_med = sorted(atr_hist)[len(atr_hist)//2]
    trend = h4_trend(h1c)
    sess = session_wib(ts)
    sig_range = h - l
    # breakout depth: how far past boundary at close
    depth = (c - upper) if sig == "BUY" else (lower - c)
    # distance entry to mid
    d_mid = abs(entry - mid)
    # excursion after entry: MFE in R before SL hit
    sl = entry - sl_d if sig == "BUY" else entry + sl_d
    tp1 = entry + sl_d if sig == "BUY" else entry - sl_d
    mfe, bars_to_sl, tp1_touched, tp1_bar = 0.0, None, False, None
    for k in range(i + 1, min(i + 600, len(bars))):
        bk = bars[k]
        if sig == "BUY":
            mfe = max(mfe, (bk[2] - entry) / sl_d)
            if bk[2] >= tp1 and not tp1_touched:
                tp1_touched, tp1_bar = True, k - i
            if bk[3] <= sl:
                bars_to_sl = k - i; break
        else:
            mfe = max(mfe, (entry - bk[3]) / sl_d)
            if bk[3] <= tp1 and not tp1_touched:
                tp1_touched, tp1_bar = True, k - i
            if bk[2] >= sl:
                bars_to_sl = k - i; break
    wib = datetime.datetime.fromtimestamp(ts, WIB).strftime("%d %b %H:%M")
    print(f"\n{sig} @{entry}  sinyal {iso} ({wib} WIB) — sesi {sess}")
    print(f"  H4 trend: {trend} | ATR H1: {a:.2f} (median20: {atr_med:.2f}, rasio {a/atr_med:.2f})")
    print(f"  Donchian: upper {upper:.2f} lower {lower:.2f} mid {mid:.2f}")
    print(f"  depth breakout: {depth:.2f} ({depth/a:+.2f} ATR) | jarak entry ke mid: {d_mid:.2f} ({d_mid/a:.2f} ATR)")
    print(f"  range bar sinyal: {sig_range:.2f} ({sig_range/a:.2f} ATR) | close bar: {c:.2f}")
    print(f"  MFE sblm SL: {mfe:.2f}R | TP1 tersentuh: {tp1_touched}"
          + (f" (bar ke-{tp1_bar})" if tp1_touched else "")
          + f" | SL kena di bar ke-{bars_to_sl} (~{bars_to_sl*5 if bars_to_sl else '?'} mnt)")
