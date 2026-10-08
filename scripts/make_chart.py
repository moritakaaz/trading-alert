#!/usr/bin/env python3
"""Render an XAUUSD M5 entry chart: candles + pattern + SL/TP levels.

Usage: make_chart.py <input.json>
input.json: {"bars":[{"t":epoch,"o":..,"h":..,"l":..,"c":..}...] (M5 oldest-first),
  "pattern": {"kind": "DOUBLE TOP"|"DOUBLE BOTTOM", "p1": float, "p2": float,
              "neck": float} (optional, v2.0),
  "signal": "BUY"|"SELL"|"NOW",
  "entry": float, "sl": dist, "tp1": dist, "tp2": dist, "tp3": dist,
  "bar_time_wib": "05 Oct 11:25", "out": "/path/to.png"}
"NOW" mode draws a live price line instead of SL/TP/entry marker (sl/tp keys optional).
Writes the PNG to "out".
"""
import json, sys, datetime

def main():
    d = json.load(open(sys.argv[1]))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # B18: dynamic bar count — ensure p1 is visible (max 72 default,
    # or p1-to-signal distance + 10)
    _all_bars = d["bars"]
    _n_bars = 72
    try:
        _pat = d.get("pattern") or {}
        _p1_t = _pat.get("p1_t")
        _sig_t = d.get("sig_t")
        if _p1_t and _sig_t:
            # find indices
            _bts = [b["t"] for b in _all_bars]
            _i1 = min(range(len(_bts)), key=lambda i: abs(_bts[i] - _p1_t))
            _i2 = min(range(len(_bts)), key=lambda i: abs(_bts[i] - _sig_t))
            _dist = abs(_i2 - _i1) + 10
            _n_bars = max(72, _dist)
    except Exception:
        pass
    bars = _all_bars[-_n_bars:]
    sig = d["signal"]  # "BUY", "SELL", or "NOW" (live chart without trade levels)
    entry = d["entry"]
    is_now = (sig == "NOW")
    # hist: True = closed/historical signal -> dimmed dashed lines + outcome label
    # entry_line: True = horizontal entry line (for /chart, where the signal
    #   bar is old); False = triangle marker on last bar (for fresh alerts)
    # setup_mode: True = forming pattern, no SL/TP (standby alert, not an entry)
    is_hist = d.get("hist", False)
    entry_line = d.get("entry_line", False)
    is_setup = d.get("setup_mode", False)
    if not is_now and not is_setup:
        sl_lv = entry - d["sl"] if sig == "BUY" else entry + d["sl"]
        tp_lvs = [("TP1", d["tp1"]), ("TP2", d["tp2"]), ("TP3", d["tp3"])]
        tp_vals = [(n, entry + v if sig == "BUY" else entry - v) for n, v in tp_lvs]
    else:
        tp_vals = []

    WIB = datetime.timezone(datetime.timedelta(hours=7))
    xs = list(range(len(bars)))
    opens = [b["o"] for b in bars]
    highs = [b["h"] for b in bars]
    lows = [b["l"] for b in bars]
    closes = [b["c"] for b in bars]
    times = [datetime.datetime.fromtimestamp(b["t"], datetime.timezone.utc).astimezone(WIB)
             for b in bars]

    # TradingView dark theme: bg #131722, grid #2a2e39, text #d1d4dc
    TV_BG = "#131722"
    TV_GRID = "#2a2e39"
    TV_TEXT = "#d1d4dc"
    TV_BBOX = dict(fc="#1e222d", ec="none", alpha=0.85, pad=1)
    fig, ax = plt.subplots(figsize=(12, 6.2), facecolor=TV_BG)
    ax.set_facecolor(TV_BG)
    ax.tick_params(colors=TV_TEXT)
    for spine in ax.spines.values():
        spine.set_color(TV_GRID)
    w = 0.7
    for i in range(len(bars)):
        col = "#26a69a" if closes[i] >= opens[i] else "#ef5350"
        ax.plot([xs[i], xs[i]], [lows[i], highs[i]], color=col, lw=1)
        top, bot = max(opens[i], closes[i]), min(opens[i], closes[i])
        ax.add_patch(plt.Rectangle((xs[i] - w / 2, bot), w, max(top - bot, 1e-9),
                                   color=col, zorder=3))

    lo, hi = min(lows), max(highs)
    lvls = ([sl_lv] + [v for _, v in tp_vals]
            if not is_now and not is_setup else [])
    pat = d.get("pattern")
    if pat:
        lvls.append(pat["neck"])
        # v2.1: include both Donchian bands in the y-range
        if pat.get("kind") == "DONCHIAN BREAKOUT":
            lvls += [pat["upper"], pat["lower"]]
    if not is_now:
        lvls.append(closes[-1])  # NOW price line level
    # v2.4: robust y-range — use 2nd/98th percentile of candle range to avoid
    # a single spike squishing the whole chart (was min/max, too fragile for M1).
    # Key levels (neck/SL/TP) still expand the range if outside.
    _los = sorted(lows)
    _his = sorted(highs)
    _n = len(_los)
    _plo = _los[min(_n-1, int(_n*0.02))]
    _phi = _his[min(_n-1, int(_n*0.98))]
    lo, hi = _plo, _phi
    if lvls:
        lo, hi = min(lo, min(lvls)), max(hi, max(lvls))
    pad = (hi - lo) * 0.12 or 1.0
    # v2.0 pattern: neckline + kind label
    # label on the LEFT edge to avoid clashing with the right-edge SL/TP/entry labels
    _is_donch = pat and pat.get("kind") == "DONCHIAN BREAKOUT" and "upper" in pat
    if pat and not _is_donch:
        ax.axhline(pat["neck"], color="#ff9800", ls=":", lw=1.5, alpha=0.9)
        ax.text(xs[0], pat["neck"], f"neckline ${pat['neck']:.0f} ({pat['kind']})  ",
                color="#ff9800", va="bottom", ha="left", fontsize=9,
                bbox=TV_BBOX)
        # v2.4: draw pattern legs (M/W shape) if timestamps available
        if pat.get("p1_t") and pat.get("neck_t") and pat.get("p2_t"):
            bts = [b["t"] for b in bars]
            def _fidx(t):
                return min(range(len(bts)), key=lambda i: abs(bts[i] - t))
            try:
                i1, i_n, i2 = _fidx(pat["p1_t"]), _fidx(pat["neck_t"]), _fidx(pat["p2_t"])
                # only draw if within chart range
                if max(abs(bts[i1]-pat["p1_t"]), abs(bts[i_n]-pat["neck_t"]), abs(bts[i2]-pat["p2_t"])) < 3600:
                    ax.plot([xs[i1], xs[i_n]], [pat["p1"], pat["neck"]],
                            color="#ff9800", lw=2.0, alpha=0.9, zorder=4)
                    ax.plot([xs[i_n], xs[i2]], [pat["neck"], pat["p2"]],
                            color="#ff9800", lw=2.0, alpha=0.9, zorder=4)
                    # dots at the three key points
                    for _xi, _yp in [(i1, pat["p1"]), (i_n, pat["neck"]), (i2, pat["p2"])]:
                        ax.scatter([xs[_xi]], [_yp], s=45, color="#ff9800", zorder=5,
                                   edgecolors="black", linewidths=0.7)
            except Exception:
                pass
    # v2.1 brutal: Donchian channel (both bands) for DONCHIAN BREAKOUT signals
    if _is_donch:
        ax.axhline(pat["upper"], color="#ff9800", ls=":", lw=1.2, alpha=0.7)
        ax.text(xs[0], pat["upper"], f"Donchian upper ${pat['upper']:.0f}  ",
                color="#ff9800", va="bottom", ha="left", fontsize=9,
                bbox=TV_BBOX)
        ax.axhline(pat["lower"], color="#ff9800", ls=":", lw=1.2, alpha=0.7)
        ax.text(xs[0], pat["lower"], f"Donchian lower ${pat['lower']:.0f}  ",
                color="#ff9800", va="top", ha="left", fontsize=9,
                bbox=TV_BBOX)
    if not is_now:
        if not is_setup:
            # SL / TPs (dimmed dashed when historical) — labels show PRICES
            sl_col = "#9e9e9e" if is_hist else "#d32f2f"
            tp_col = "#9e9e9e" if is_hist else "#2e7d32"
            ax.axhline(sl_lv, color=sl_col, ls="--" if is_hist else "-",
                       lw=1.0 if is_hist else 1.4, alpha=0.7 if is_hist else 1.0)
            ax.text(xs[-1], sl_lv, f"  SL ${sl_lv:.0f}", color=sl_col, va="center",
                    fontsize=9 if is_hist else 10,
                    fontweight="normal" if is_hist else "bold",
                    bbox=TV_BBOX)
            for n, v in tp_vals:
                ax.axhline(v, color=tp_col, ls=":", lw=1.0 if is_hist else 1.3,
                           alpha=0.6 if is_hist else 1.0)
                ax.text(xs[-1], v, f"  {n} ${v:.0f}", color=tp_col, va="center",
                        fontsize=8 if is_hist else 9,
                        bbox=TV_BBOX)
        # NOW price line — so you can see current price vs entry/SL/TP at a glance
        now_px = closes[-1]
        ax.axhline(now_px, color="#7b1fa2", ls="--", lw=1.2, alpha=0.9)
        ax.text(xs[-1], now_px, f"  NOW ${now_px:.0f}", color="#7b1fa2",
                va="bottom", fontsize=9, fontweight="bold",
                bbox=TV_BBOX)
        if not is_hist and not is_setup:
            # risk zone (entry->SL, red tint) and first profit zone (entry->TP1, green tint)
            tp1_v = tp_vals[0][1]
            if sig == "BUY":
                ax.axhspan(sl_lv, entry, color="#d32f2f", alpha=0.06, zorder=1)
                ax.axhspan(entry, tp1_v, color="#2e7d32", alpha=0.06, zorder=1)
            else:
                ax.axhspan(entry, sl_lv, color="#d32f2f", alpha=0.06, zorder=1)
                ax.axhspan(tp1_v, entry, color="#2e7d32", alpha=0.06, zorder=1)
        # signal marker: vertical dotted line at the signal bar (if known)
        sig_t = d.get("sig_t")
        if sig_t:
            bts = [b["t"] for b in bars]
            idx = min(range(len(bts)), key=lambda i: abs(bts[i] - sig_t))
            if abs(bts[idx] - sig_t) < 7200:  # signal bar within chart range
                ax.axvline(xs[idx], color="#ff9800", ls=":", lw=1.3, alpha=0.85, zorder=4)
                ax.text(xs[idx], hi + pad * 0.02, " ▼ signal", color="#ff9800",
                        fontsize=8, ha="left", va="bottom",
                        bbox=TV_BBOX)
    # entry marker on last bar (or NOW price line in live mode)
    i = len(bars) - 1
    if is_now:
        ax.axhline(entry, color="#7b1fa2", ls="-", lw=1.6)
        ax.text(xs[-1], entry, f"  NOW ${entry:.0f}", color="#7b1fa2", va="bottom",
                fontsize=10, fontweight="bold",
                bbox=TV_BBOX)
    elif entry_line or is_hist:
        # horizontal entry line (for /chart: signal bar is old)
        ecol = "#9e9e9e" if is_hist else ("#2e7d32" if sig == "BUY" else "#d32f2f")
        ax.axhline(entry, color=ecol, ls="--" if is_hist else "-",
                   lw=1.0 if is_hist else 1.6, alpha=0.7 if is_hist else 1.0)
        elabel = f"  ENTRY {sig} @ ${entry:.0f}"
        if is_hist and d.get("hist_label"):
            elabel += f" {d['hist_label']}"
        ax.text(xs[-1], entry, elabel, color=ecol, va="bottom",
                fontsize=9 if is_hist else 10,
                fontweight="normal" if is_hist else "bold",
                bbox=TV_BBOX)
    else:
        marker = "^" if sig == "BUY" else "v"
        mcol = "#2e7d32" if sig == "BUY" else "#d32f2f"
        ax.scatter([i], [closes[i]], s=220, marker=marker, color=mcol, zorder=5,
                   edgecolors="black", linewidths=0.8)
        _mlabel = f"WATCH {sig}" if is_setup else f"ENTRY {sig}"
        ax.text(i, closes[i] + (pad * 0.35 if sig == "BUY" else -pad * 0.55),
                _mlabel, color=mcol, fontsize=11, fontweight="bold",
                ha="center", va="bottom" if sig == "BUY" else "top",
                bbox=dict(fc="white", ec=mcol, alpha=0.9, pad=2))

    ax.set_xlim(-1, len(bars))
    ax.set_ylim(lo - pad, hi + pad)
    step = max(1, len(bars) // 8)
    ax.set_xticks(xs[::step])
    ax.set_xticklabels([t.strftime("%H:%M") for t in times[::step]], fontsize=9)
    mode = "LIVE" if is_now else ("HIST" if is_hist else ("SETUP WATCH" if is_setup else sig))
    _tf = d.get("tf", "M5")  # multi-TF: M1/M5/M15 (default M5 for old callers)
    ax.set_title(f"XAUUSD {_tf} · {mode} · {d['bar_time_wib']} WIB · ${entry:.0f}",
                 fontsize=13, fontweight="bold", loc="left", pad=12, color=TV_TEXT)
    ax.grid(True, alpha=0.25, color=TV_GRID)
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.tight_layout()
    fig.savefig(d["out"], dpi=110)
    print("wrote", d["out"])

if __name__ == "__main__":
    main()
