#!/usr/bin/env python3
"""Validate Donchian(48) H1 breakout evaluated on M5 bars (for M5 entry alerts).
Data: Binance PAXGUSDT M5 zips (Jul-Aug 2026 monthly + Sep28-Oct4 daily),
weekends filtered to forex hours. Same trade logic as m15_check.py."""
import csv, glob, zipfile, time, datetime, bisect

def load():
    bars = []
    for zf in sorted(glob.glob("/tmp/paxg_m5/*.zip")):
        try:
            with zipfile.ZipFile(zf) as z:
                name = z.namelist()[0]
                with z.open(name) as f:
                    for row in csv.reader(f.read().decode().splitlines()):
                        t = int(row[0]) // 1_000_000  # binance vision csv: microseconds
                        bars.append((t, float(row[1]), float(row[2]),
                                     float(row[3]), float(row[4])))
        except Exception as e:
            print("skip", zf, e)
    bars.sort()
    # dedupe + forex-hours filter (drop Sat, Sun<22:00 UTC, Fri>=21:00 UTC)
    seen, out = set(), []
    for t, o, h, l, c in bars:
        if t in seen:
            continue
        seen.add(t)
        dt = datetime.datetime.fromtimestamp(t, datetime.timezone.utc)
        wd, hr = dt.weekday(), dt.hour + dt.minute / 60
        if wd == 5:
            continue
        if wd == 6 and hr < 22:
            continue
        if wd == 4 and hr >= 21:
            continue
        out.append((t, o, h, l, c))
    return out

bars = load()
t5 = [b[0] for b in bars]; o5 = [b[1] for b in bars]; h5 = [b[2] for b in bars]
l5 = [b[3] for b in bars]; c5 = [b[4] for b in bars]
print(f"M5 bars: {len(bars)}, {datetime.datetime.fromtimestamp(t5[0], datetime.timezone.utc):%Y-%m-%d} "
      f"-> {datetime.datetime.fromtimestamp(t5[-1], datetime.timezone.utc):%Y-%m-%d}", flush=True)

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
print(f"H1 bars: {len(h1)}", flush=True)

def atr(i, n=14):
    trs = [max(h5[k] - l5[k], abs(h5[k] - c5[k-1]), abs(l5[k] - c5[k-1]))
           for k in range(i - n + 1, i + 1)]
    return sum(trs) / n

DON = 48
trades, pos = [], None
for i in range(60, len(c5)):
    hb = t5[i] - (t5[i] % 3600)
    j = bisect.bisect_left(h1t, hb) - 1
    if j < DON:
        continue
    w = h1[j - DON + 1:j + 1]
    upper = max(b[2] for b in w); lower = min(b[3] for b in w)
    if pos is None:
        a = atr(i)
        if a <= 0: continue
        if c5[i] > upper:
            pos = ("BUY", c5[i], c5[i] - 1.5*a, c5[i] + 3.0*a)
        elif c5[i] < lower:
            pos = ("SELL", c5[i], c5[i] + 1.5*a, c5[i] - 3.0*a)
    else:
        d, entry, sl, tp = pos
        hit_sl = (l5[i] <= sl) if d == "BUY" else (h5[i] >= sl)
        hit_tp = (h5[i] >= tp) if d == "BUY" else (l5[i] <= tp)
        if hit_sl or hit_tp:
            exit_p = sl if hit_sl else tp
            r = (exit_p - entry)/(entry - sl) if d == "BUY" else (entry - exit_p)/(sl - entry)
            trades.append(r); pos = None

def stats(seg):
    w = [r for r in seg if r > 0]
    pf = sum(w)/-sum(r for r in seg if r <= 0) if any(r <= 0 for r in seg) else float("inf")
    return len(seg), (len(w)/len(seg)*100 if seg else 0), pf, sum(seg)

n, wr, pf, tr = stats(trades)
eq = peak = mdd = 0.0
for r in trades:
    eq += r; peak = max(peak, eq); mdd = max(mdd, peak - eq)
print(f"\nM5-eval: trades={n} winrate={wr:.1f}% PF={pf:.2f} totalR={tr:.1f} maxDD_R={mdd:.1f}", flush=True)
h = len(trades)//2
for name, seg in [("H1", trades[:h]), ("H2", trades[h:])]:
    nn, ww, pp, tt = stats(seg)
    print(f"  {name}: n={nn} PF={pp:.2f}", flush=True)
# signal count: how many M5 bars fire a fresh signal (alert frequency)
print(f"avg trades/week: {n/9.5:.1f}", flush=True)
