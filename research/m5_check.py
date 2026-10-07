#!/usr/bin/env python3
"""Validate Donchian(48) H1 breakout evaluated on M5 bars (for M5 entry alerts).
Data: Kraken PAXGUSD M5 (~3 months via pagination), H1 resampled from M5.
Signal: on each new M5 bar, BUY if close > highest high of prior 48 completed H1
bars; SELL if close < lowest low. SL=1.5*ATR(14 M5), TP=3*ATR(14 M5).
Reports PF, trades, max DD in R — comparable to the M15 check (PF 1.10)."""
import json, time, urllib.request

PAIR = "PAXGUSD"
M5_TARGET = 26000  # ~90 days of M5 bars

def kraken_ohlc(interval, since=0):
    url = f"https://api.kraken.com/0/public/OHLC?pair={PAIR}&interval={interval}"
    if since:
        url += f"&since={since}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    d = json.load(urllib.request.urlopen(req, timeout=30))
    if d.get("error"):
        raise RuntimeError(d["error"])
    key = [k for k in d["result"] if k != "last"][0]
    return d["result"][key], d["result"]["last"]

def fetch_m5(n_target):
    all_bars, since, seen = [], 0, set()
    while len(all_bars) < n_target:
        bars, last = kraken_ohlc(5, since)
        new = [b for b in bars if b[0] not in seen]
        if not new:
            break
        for b in new:
            seen.add(b[0])
        all_bars.extend(new)
        since = last
        time.sleep(0.4)
    all_bars.sort(key=lambda b: b[0])
    return all_bars

print("downloading M5 ...", flush=True)
m5 = fetch_m5(M5_TARGET)
print(f"M5 bars: {len(m5)}, from {time.strftime('%Y-%m-%d', time.gmtime(m5[0][0]))} "
      f"to {time.strftime('%Y-%m-%d', time.gmtime(m5[-1][0]))}", flush=True)

# M5 -> dict arrays
t5 = [b[0] for b in m5]
o5 = [float(b[1]) for b in m5]
h5 = [float(b[2]) for b in m5]
l5 = [float(b[3]) for b in m5]
c5 = [float(b[4]) for b in m5]

# resample to H1
h1 = []
bucket = None
for t, o, h, l, c in zip(t5, o5, h5, l5, c5):
    hb = t - (t % 3600)
    if bucket is None or bucket[0] != hb:
        if bucket:
            h1.append(bucket)
        bucket = [hb, o, h, l, c]
    else:
        bucket[2] = max(bucket[2], h)
        bucket[3] = min(bucket[3], l)
        bucket[4] = c
if bucket:
    h1.append(bucket)
h1t = [b[0] for b in h1]

def atr(highs, lows, closes, i, n=14):
    trs = []
    for k in range(i - n + 1, i + 1):
        trs.append(max(highs[k] - lows[k],
                       abs(highs[k] - closes[k - 1]),
                       abs(lows[k] - closes[k - 1])))
    return sum(trs) / n

trades = []
pos = None
DON = 48
for i in range(60, len(c5)):
    # completed H1 bars strictly before this M5 bar's hour
    hb = t5[i] - (t5[i] % 3600)
    import bisect
    j = bisect.bisect_left(h1t, hb) - 1  # last completed H1
    if j < DON:
        continue
    window = h1[j - DON + 1:j + 1]
    upper = max(b[2] for b in window)
    lower = min(b[3] for b in window)
    if pos is None:
        if c5[i] > upper:
            a = atr(h5, l5, c5, i)
            pos = ("BUY", c5[i], c5[i] - 1.5 * a, c5[i] + 3.0 * a)
        elif c5[i] < lower:
            a = atr(h5, l5, c5, i)
            pos = ("SELL", c5[i], c5[i] + 1.5 * a, c5[i] - 3.0 * a)
    else:
        d, entry, sl, tp = pos
        hit_sl = (l5[i] <= sl) if d == "BUY" else (h5[i] >= sl)
        hit_tp = (h5[i] >= tp) if d == "BUY" else (l5[i] <= tp)
        if hit_sl or hit_tp:
            # conservative: if both hit same bar, count as SL
            exit_p = sl if hit_sl else tp
            r = (exit_p - entry) / (entry - sl) if d == "BUY" else (entry - exit_p) / (sl - entry)
            trades.append(r)
            pos = None

wins = [r for r in trades if r > 0]
pf = sum(wins) / -sum(r for r in trades if r <= 0) if any(r <= 0 for r in trades) else float("inf")
# max drawdown in R
eq, peak, mdd = 0.0, 0.0, 0.0
for r in trades:
    eq += r
    peak = max(peak, eq)
    mdd = max(mdd, peak - eq)
print(f"\ntrades={len(trades)} winrate={len(wins)/len(trades)*100:.1f}% "
      f"PF={pf:.2f} totalR={sum(trades):.1f} maxDD_R={mdd:.1f}", flush=True)
# halves
h = len(trades) // 2
for name, seg in [("H1", trades[:h]), ("H2", trades[h:])]:
    w = [r for r in seg if r > 0]
    p = sum(w) / -sum(r for r in seg if r <= 0) if any(r <= 0 for r in seg) else float("inf")
    print(f"  {name}: n={len(seg)} PF={p:.2f}", flush=True)
