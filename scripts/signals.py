#!/usr/bin/env python3
"""Pure signal-detection functions for the XAUUSD double top/bottom strategy.

B54: extracted from the xauusd_entry_tf.sh heredoc so the logic can be
imported and unit-tested without running the live engine.

All functions are PURE: no I/O, no globals, no network. Inputs:
    bars: list of (t, o, h, l, c) tuples, oldest-first, CLOSED bars only.
    a1:   H1 ATR(14) as a float.

Strategy parameters (DO NOT change without owner approval):
    - fractal N=2 for peak/valley detection
    - |p1-p2| <= 0.25 * ATR
    - p1/p2 5-50 bars apart, intervening extreme >= 3 bars from each side
    - valley >= 0.5 * ATR deep (tops) / peak >= 0.5 * ATR high (bottoms)
    - v2.3: p1 = first-valid peak/valley (not greedy-nearest)
    - v2.4: clean check (no higher-high / lower-low between p1 and p2)
    - entry confirmation: close beyond neckline + candle in signal direction
    - quality score 0-100 (Grade A/B/C), informational only
"""


def rsi_series(closes, period=14):
    """Wilder's RSI; returns list aligned with closes. Pure."""
    n = len(closes)
    out = [50.0] * n
    if n <= period:
        return out
    gains = [0.0] * n
    losses = [0.0] * n
    for i in range(1, n):
        d = closes[i] - closes[i - 1]
        gains[i] = d if d > 0 else 0.0
        losses[i] = -d if d < 0 else 0.0
    ag = sum(gains[1:period + 1]) / period
    al = sum(losses[1:period + 1]) / period
    if al == 0:
        out[period] = 100.0
    else:
        out[period] = 100.0 - 100.0 / (1.0 + ag / al)
    for i in range(period + 1, n):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period
        out[i] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    return out


def score_pattern(sig, p1, p2, xn, neck, bars, a1):
    """Quality score 0-100 for a completed double top/bottom pattern.

    Pure: bars and a1 passed explicitly (no globals).
    Components: peak match 25 + RSI divergence 20 + height 15
                + symmetry 10 + prior trend 15 (rescaled /85 -> 100).
    Returns (score:int, grade:str, rsi_div:bool).
    """
    H = [b[2] for b in bars]
    L = [b[3] for b in bars]
    C = [b[4] for b in bars]
    if sig == "SELL":
        ext = max(H[p1], H[p2])
        match = max(0.0, 1.0 - abs(H[p2] - H[p1]) / max(0.25 * a1, 1e-9))
    else:
        ext = min(L[p1], L[p2])
        match = max(0.0, 1.0 - abs(L[p2] - L[p1]) / max(0.25 * a1, 1e-9))
    s1 = 25.0 * match
    r = rsi_series(C)
    rsi_div = (r[p2] < r[p1]) if sig == "SELL" else (r[p2] > r[p1])
    s2 = 20.0 if rsi_div else 0.0
    h = abs(ext - neck)
    s4 = 15.0 * min(1.0, h / max(3.0 * a1, 1e-9))
    l1, l2 = xn - p1, p2 - xn
    sym = min(l1, l2) / max(max(l1, l2), 1)
    s5 = 10.0 * sym
    lo_i = max(0, p1 - 60)
    if sig == "SELL":
        pre = min(L[lo_i:p1 + 1]) if lo_i < p1 else ext
        prior = max(0.0, ext - pre)
    else:
        pre = max(H[lo_i:p1 + 1]) if lo_i < p1 else ext
        prior = max(0.0, pre - ext)
    s6 = 15.0 * min(1.0, prior / max(h, 1e-9))
    score = int(round((s1 + s2 + s4 + s5 + s6) / 85.0 * 100.0))
    grade = "A" if score >= 75 else ("B" if score >= 55 else "C")
    return score, grade, rsi_div


def _fractals(bars):
    """N=2 fractal peaks/valleys. Returns (is_peak, is_valley) lists."""
    n = len(bars)
    H = [b[2] for b in bars]
    L = [b[3] for b in bars]
    is_peak = [False] * n
    is_valley = [False] * n
    for i in range(2, n - 2):
        if H[i] > H[i - 1] and H[i] > H[i - 2] and H[i] > H[i + 1] and H[i] > H[i + 2]:
            is_peak[i] = True
        if L[i] < L[i - 1] and L[i] < L[i - 2] and L[i] < L[i + 1] and L[i] < L[i + 2]:
            is_valley[i] = True
    return is_peak, is_valley


def detect_dtb(bars, a1):
    """Double top/bottom entry detector (close-confirmed).

    Pure: bars (closed only, oldest-first) and a1 passed explicitly.
    The confirmation candle is the LAST bar in `bars`.
    SELL: close < neckline AND close < open (red).
    BUY:  close > neckline AND close > open (green).
    Returns (sig, pattern_dict) or (None, None).
    """
    n = len(bars)
    if n < 80 or a1 <= 0:
        return None, None
    H = [b[2] for b in bars]
    L = [b[3] for b in bars]
    is_peak, is_valley = _fractals(bars)
    k = n - 1
    so, sc = bars[k][1], bars[k][4]
    # double tops -> SELL
    for p2 in range(k - 1, max(1, k - 24), -1):  # B16: newest first
        if not is_peak[p2]:
            continue
        # v2.3: p1 = first-valid peak (not greedy-nearest)
        p1, vlo, vi = None, None, None
        for q in range(p2 - 5, max(1, p2 - 50), -1):
            if not is_peak[q]:
                continue
            if abs(H[p2] - H[q]) > 0.25 * a1:
                continue
            _seg = L[q + 1:p2]
            if not _seg:
                continue
            _vlo = min(_seg)
            if min(H[q], H[p2]) - _vlo < 0.5 * a1:
                continue
            _vi = q + 1 + _seg.index(_vlo)
            if _vi - q < 3 or p2 - _vi < 3:
                continue
            p1, vlo, vi = q, _vlo, _vi
            break
        if p1 is None:
            continue
        # v2.4 clean check: no higher high between the peaks
        if max(H[p1 + 1:p2]) > max(H[p1], H[p2]) + 1e-9:
            continue
        if sc < vlo and sc < so:  # close below neckline + red
            _score, _grade, _rsi_div = score_pattern("SELL", p1, p2, vi, vlo, bars, a1)
            return "SELL", {"kind": "DOUBLE TOP", "p1": H[p1],
                            "p2": H[p2], "neck": vlo,
                            "p2_t": bars[p2][0],
                            "p1_t": bars[p1][0],
                            "neck_t": bars[vi][0],
                            "score": _score, "grade": _grade,
                            "rsi_div": _rsi_div}
    # double bottoms -> BUY
    for p2 in range(k - 1, max(1, k - 24), -1):  # B16: newest first
        if not is_valley[p2]:
            continue
        p1, vhi, pi = None, None, None
        for q in range(p2 - 5, max(1, p2 - 50), -1):
            if not is_valley[q]:
                continue
            if abs(L[p2] - L[q]) > 0.25 * a1:
                continue
            _seg = H[q + 1:p2]
            if not _seg:
                continue
            _vhi = max(_seg)
            if _vhi - max(L[q], L[p2]) < 0.5 * a1:
                continue
            _pi = q + 1 + _seg.index(_vhi)
            if _pi - q < 3 or p2 - _pi < 3:
                continue
            p1, vhi, pi = q, _vhi, _pi
            break
        if p1 is None:
            continue
        # v2.4 clean check: no lower low between the valleys
        if min(L[p1 + 1:p2]) < min(L[p1], L[p2]) - 1e-9:
            continue
        if sc > vhi and sc > so:  # close above neckline + green
            _score, _grade, _rsi_div = score_pattern("BUY", p1, p2, pi, vhi, bars, a1)
            return "BUY", {"kind": "DOUBLE BOTTOM", "p1": L[p1],
                           "p2": L[p2], "neck": vhi,
                           "p2_t": bars[p2][0],
                           "p1_t": bars[p1][0],
                           "neck_t": bars[pi][0],
                           "score": _score, "grade": _grade,
                           "rsi_div": _rsi_div}
    return None, None


def detect_setup(bars, a1):
    """Setup-watch detector: pattern geometry complete but NOT confirmed yet.

    Pure: bars (closed only, oldest-first) and a1 passed explicitly.
    B03: price must be within 0.5*ATR on the correct side of the neckline
    (SELL: 0 <= sc - neck <= 0.5*a1; BUY: 0 <= neck - sc <= 0.5*a1).
    Returns (sig, pattern_dict) or (None, None); most recent pattern wins.
    """
    n = len(bars)
    if n < 80 or a1 <= 0:
        return None, None
    H = [b[2] for b in bars]
    L = [b[3] for b in bars]
    is_peak, is_valley = _fractals(bars)
    k = n - 1
    sc = bars[k][4]
    best = None  # (p2, sig, pattern) — keep the most recent
    # double tops forming -> potential SELL
    for p2 in range(k - 1, max(1, k - 24), -1):  # B16: newest first
        if not is_peak[p2]:
            continue
        p1, vlo, vi = None, None, None
        for q in range(p2 - 5, max(1, p2 - 50), -1):
            if not is_peak[q]:
                continue
            if abs(H[p2] - H[q]) > 0.25 * a1:
                continue
            _seg = L[q + 1:p2]
            if not _seg:
                continue
            _vlo = min(_seg)
            if min(H[q], H[p2]) - _vlo < 0.5 * a1:
                continue
            _vi = q + 1 + _seg.index(_vlo)
            if _vi - q < 3 or p2 - _vi < 3:
                continue
            p1, vlo, vi = q, _vlo, _vi
            break
        if p1 is None:
            continue
        if max(H[p1 + 1:p2]) > max(H[p1], H[p2]) + 1e-9:
            continue
        # B03: price must be AT or ABOVE neckline (not yet broken), max 0.5 ATR away
        if not (0.0 <= sc - vlo <= 0.5 * a1):
            continue
        _score, _grade, _rsi_div = score_pattern("SELL", p1, p2, vi, vlo, bars, a1)
        best = (p2, "SELL", {"kind": "DOUBLE TOP", "p1": H[p1],
                             "p2": H[p2], "neck": vlo,
                             "p2_t": bars[p2][0],
                             "p1_t": bars[p1][0],
                             "neck_t": bars[vi][0],
                             "score": _score, "grade": _grade,
                             "rsi_div": _rsi_div})
    # double bottoms forming -> potential BUY
    for p2 in range(k - 1, max(1, k - 24), -1):  # B16: newest first
        if not is_valley[p2]:
            continue
        p1, vhi, pi = None, None, None
        for q in range(p2 - 5, max(1, p2 - 50), -1):
            if not is_valley[q]:
                continue
            if abs(L[p2] - L[q]) > 0.25 * a1:
                continue
            _seg = H[q + 1:p2]
            if not _seg:
                continue
            _vhi = max(_seg)
            if _vhi - max(L[q], L[p2]) < 0.5 * a1:
                continue
            _pi = q + 1 + _seg.index(_vhi)
            if _pi - q < 3 or p2 - _pi < 3:
                continue
            p1, vhi, pi = q, _vhi, _pi
            break
        if p1 is None:
            continue
        if min(L[p1 + 1:p2]) < min(L[p1], L[p2]) - 1e-9:
            continue
        # B03: price must be AT or BELOW neckline (not yet broken), max 0.5 ATR away
        if not (0.0 <= vhi - sc <= 0.5 * a1):
            continue
        if best is None or p2 > best[0]:
            _score, _grade, _rsi_div = score_pattern("BUY", p1, p2, pi, vhi, bars, a1)
            best = (p2, "BUY", {"kind": "DOUBLE BOTTOM", "p1": L[p1],
                                "p2": L[p2], "neck": vhi,
                                "p2_t": bars[p2][0],
                                "p1_t": bars[p1][0],
                                "neck_t": bars[pi][0],
                                "score": _score, "grade": _grade,
                                "rsi_div": _rsi_div})
    if best:
        return best[1], best[2]
    return None, None
