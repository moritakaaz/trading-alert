import sys, datetime
sys.path.insert(0, '.')
from backtest_strategies import load_bars, atr_list, run, pf_of

bars = load_bars("/tmp/bt/gc_1h_1y.json")
atr = atr_list(bars, 14)

def don48(i):
    hh = max(b["h"] for b in bars[i-48:i])
    ll = min(b["l"] for b in bars[i-48:i])
    if bars[i]["c"] > hh: return 1
    if bars[i]["c"] < ll: return -1
    return 0

trades, eq, maxdd, cumR, maxddR = run(bars, don48, 1.5, 3.0, atr)
print(f"FULL: trades={len(trades)} net=${eq:.2f} PF={pf_of(trades):.2f}")

# quarterly split by exit time
t0, t1 = bars[0]["t"], bars[-1]["t"]
for q in range(4):
    qa, qb = t0 + (t1-t0)*q/4, t0 + (t1-t0)*(q+1)/4
    qs = [t for t in trades if qa <= t[0] < qb]
    qd = datetime.datetime.fromtimestamp(qa, datetime.timezone.utc).strftime("%Y-%m-%d")
    print(f"Q{q+1} from {qd}: trades={len(qs)} net=${sum(t[1] for t in qs):.2f} PF={pf_of(qs):.2f}")

# R distribution: top-5 winners share of gross profit
gains = sorted([t[1] for t in trades if t[1] > 0], reverse=True)
gp = sum(gains)
print(f"gross profit=${gp:.2f}, top5 winners share={sum(gains[:5])/gp*100:.1f}%")
losses = sorted([t[1] for t in trades if t[1] < 0])
print(f"gross loss=${sum(losses):.2f}, worst loss=${losses[0]:.2f}, avg win=${gp/len(gains):.2f}, avg loss=${sum(losses)/len(losses):.2f}")
