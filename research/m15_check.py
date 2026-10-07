import sys, datetime
sys.path.insert(0, '.')
from backtest_strategies import load_bars, atr_list, ema_list, run, summarize, pf_of

bars = load_bars("/tmp/bt/gc_15m_60d.json")
print(f"M15 data: {len(bars)} bars")
atr15 = atr_list(bars, 14)
t_mid = (bars[0]["t"] + bars[-1]["t"]) / 2

# A: native M15 Donchian(48)
def don48_m15(i):
    hh = max(b["h"] for b in bars[i-48:i])
    ll = min(b["l"] for b in bars[i-48:i])
    if bars[i]["c"] > hh: return 1
    if bars[i]["c"] < ll: return -1
    return 0

# B: H1-channel Donchian(48) evaluated per M15 bar (EA-style)
h1 = []
for b in bars:
    hs = (b["t"] // 3600) * 3600
    if h1 and h1[-1][0] == hs:
        h1[-1][1] = max(h1[-1][1], b["h"]); h1[-1][2] = min(h1[-1][2], b["l"])
        h1[-1][3] = b["c"]
    else:
        h1.append([hs, b["h"], b["l"], b["o"], b["c"]])
# h1 entries: [t_start, h, l, o, c]; drop last (forming)
h1 = h1[:-1]
print(f"H1 resampled: {len(h1)} bars")

def don48_h1_on_m15(i):
    t = bars[i]["t"]
    # last H1 bar fully closed before this M15 bar starts
    j = None
    # binary search
    lo, hi = 0, len(h1)-1
    while lo <= hi:
        mid = (lo+hi)//2
        if h1[mid][0] + 3600 <= t: j = mid; lo = mid+1
        else: hi = mid-1
    if j is None or j < 48: return 0
    hh = max(h1[k][1] for k in range(j-48, j))
    ll = min(h1[k][2] for k in range(j-48, j))
    if bars[i]["c"] > hh: return 1
    if bars[i]["c"] < ll: return -1
    return 0

for name, fn in [("A native M15 Donchian(48)", don48_m15), ("B H1-Donchian(48) on M15 bars", don48_h1_on_m15)]:
    trades, eq, maxdd, cumR, maxddR = run(bars, fn, 1.5, 3.0, atr15)
    r = summarize(name, trades, eq, maxdd, cumR, maxddR, t_mid)
    print(f"{r['name']}: trades={r['trades']} net=${r['net_$']} PF={r['PF']} win={r['win%']}% avgR={r['avgR']} DD_R={r['maxDD_R']} PF_h1={r['PF_h1']} PF_h2={r['PF_h2']}")

# baseline on M15 for reference
closes = [b["c"] for b in bars]
e20 = ema_list(closes, 20); e50 = ema_list(closes, 50)
def cross(i):
    if e20[i] > e50[i] and e20[i-1] <= e50[i-1]: return 1
    if e20[i] < e50[i] and e20[i-1] >= e50[i-1]: return -1
    return 0
trades, eq, maxdd, cumR, maxddR = run(bars, cross, 1.5, 3.0, atr15)
r = summarize("0 baseline M15", trades, eq, maxdd, cumR, maxddR, t_mid)
print(f"{r['name']}: trades={r['trades']} net=${r['net_$']} PF={r['PF']} win={r['win%']}% avgR={r['avgR']} DD_R={r['maxDD_R']}")
