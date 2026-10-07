import sys
sys.path.insert(0, '.')
from backtest_strategies import load_bars, ema_list, atr_list, run, summarize

bars = load_bars("/tmp/bt/gc_1h_1y.json")
atr = atr_list(bars, 14)
t_mid = (bars[0]["t"] + bars[-1]["t"]) / 2

def make_donchian(n, adx_min=0, h1=None, h2=None):
    def sig(i):
        if adx_min and not (h1[i] and h1[i] > adx_min): return 0
        hh = max(b["h"] for b in bars[i-n:i])
        ll = min(b["l"] for b in bars[i-n:i])
        if bars[i]["c"] > hh: return 1
        if bars[i]["c"] < ll: return -1
        return 0
    return sig

print("lookback | SL | TP | trades | net_$ | PF | win% | avgR | maxDD_R | PF_h1 | PF_h2")
best = []
for n in [12, 20, 24, 32, 48]:
    for slm in [1.0, 1.5, 2.0]:
        for tpm in [2.0, 3.0, 4.0]:
            trades, eq, maxdd, cumR, maxddR = run(bars, make_donchian(n), slm, tpm, atr)
            r = summarize(f"D{n}", trades, eq, maxdd, cumR, maxddR, t_mid)
            best.append((r["PF"], n, slm, tpm, r))
            print(f"{n} | {slm} | {tpm} | {r['trades']} | {r['net_$']} | {r['PF']} | {r['win%']} | {r['avgR']} | {r['maxDD_R']} | {r['PF_h1']} | {r['PF_h2']}")
print("\nTOP 8 by PF (both halves >= 0.95):")
cands = [b for b in best if b[4]["PF_h1"] >= 0.95 and b[4]["PF_h2"] >= 0.95 and b[4]["trades"] >= 80]
cands.sort(reverse=True)
for pf, n, slm, tpm, r in cands[:8]:
    print(f"PF={pf} n={n} SL={slm} TP={tpm} trades={r['trades']} net={r['net_$']} win={r['win%']}% avgR={r['avgR']} DD_R={r['maxDD_R']} PF_h1={r['PF_h1']} PF_h2={r['PF_h2']}")
