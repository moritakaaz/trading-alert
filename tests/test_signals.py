"""Regression tests for signals.py (B54/B58).

Cases A/B/C from the improvement document section 7:
  A. close below neckline + red candle   -> ENTRY SELL (detect_dtb), no setup
  B. close below neckline + green candle -> NO setup (B03: price already broke)
  C. wick touches neckline, close above  -> NO entry, SETUP WATCH SELL

Every SELL case has a BUY mirror (symmetry requirement).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from signals import detect_dtb, detect_setup  # noqa: E402


def make_bars(last, base=4125.0):
    """90 bars with a double-top formation baked in; `last` = (o,h,l,c) of bar 89.

    Geometry (SELL): p1 peak at bar 60 (h=4140), neckline valley at bar 70
    (l=4122), p2 peak at bar 80 (h=4140.5). ATR-like scale ~20.
    """
    bars = []
    for i in range(90):
        t = 1000 + 300 * i
        bars.append([t, base, base + 5, base - 5, base])
    bars[60] = [1000 + 300 * 60, 4130, 4140, 4128, 4132]   # p1 peak 4140
    for i in range(61, 70):
        bars[i] = [1000 + 300 * i, 4126, 4128, 4124, 4125]
    bars[70] = [1000 + 300 * 70, 4126, 4126, 4122, 4124]   # neckline valley 4122
    for i in range(71, 80):
        bars[i] = [1000 + 300 * i, 4125, 4128, 4126, 4126]
    bars[80] = [1000 + 300 * 80, 4130, 4140.5, 4129, 4131]  # p2 peak 4140.5
    for i in range(81, 89):
        bars[i] = [1000 + 300 * i, 4126, 4128, 4124, 4126]
    o, h, l, c = last
    bars[89] = [1000 + 300 * 89, o, h, l, c]
    return [(b[0], b[1], b[2], b[3], b[4]) for b in bars]


def make_bars_buy(last, base=4125.0):
    """Mirror: double-bottom formation; `last` = (o,h,l,c) of bar 89.

    p1 valley at bar 60 (l=4110), neckline peak at bar 70 (h=4128),
    p2 valley at bar 80 (l=4109.5).
    """
    bars = []
    for i in range(90):
        t = 1000 + 300 * i
        bars.append([t, base, base + 5, base - 5, base])
    bars[60] = [1000 + 300 * 60, 4120, 4122, 4110, 4118]   # p1 valley 4110
    for i in range(61, 70):
        bars[i] = [1000 + 300 * i, 4124, 4126, 4122, 4125]
    bars[70] = [1000 + 300 * 70, 4124, 4128, 4124, 4126]   # neckline peak 4128
    for i in range(71, 80):
        bars[i] = [1000 + 300 * i, 4125, 4126, 4122, 4124]
    bars[80] = [1000 + 300 * 80, 4120, 4121, 4109.5, 4119]  # p2 valley 4109.5
    for i in range(81, 89):
        bars[i] = [1000 + 300 * i, 4124, 4126, 4122, 4124]
    o, h, l, c = last
    bars[89] = [1000 + 300 * 89, o, h, l, c]
    return [(b[0], b[1], b[2], b[3], b[4]) for b in bars]


# --- Case A: close below neckline + red -> ENTRY ------------------------------

def test_A_entry_sell_on_close_red():
    sig, pat = detect_dtb(make_bars((4123, 4124, 4120, 4121)), a1=20.0)
    assert sig == "SELL"
    assert pat["kind"] == "DOUBLE TOP"
    # setup must NOT fire on a confirmed bar
    assert detect_setup(make_bars((4123, 4124, 4120, 4121)), a1=20.0)[0] is None


def test_A_entry_buy_on_close_green():
    sig, pat = detect_dtb(make_bars_buy((4126, 4130, 4125, 4129)), a1=20.0)
    assert sig == "BUY"
    assert pat["kind"] == "DOUBLE BOTTOM"
    assert detect_setup(make_bars_buy((4126, 4130, 4125, 4129)), a1=20.0)[0] is None


# --- Case B: close beyond neckline but wrong color -> nothing -----------------

def test_B_no_setup_when_below_neckline_green():
    # B03 regression: price already below neckline must not emit SETUP WATCH
    assert detect_dtb(make_bars((4119, 4123, 4118, 4121)), a1=20.0)[0] is None
    assert detect_setup(make_bars((4119, 4123, 4118, 4121)), a1=20.0)[0] is None


def test_B_no_setup_when_above_neckline_red():
    assert detect_dtb(make_bars_buy((4131, 4132, 4127, 4129)), a1=20.0)[0] is None
    assert detect_setup(make_bars_buy((4131, 4132, 4127, 4129)), a1=20.0)[0] is None


# --- Case C: wick touch, close back -> setup, not entry -----------------------

def test_C_wick_touch_is_setup_not_entry():
    sig, pat = detect_dtb(make_bars((4126, 4127, 4120, 4125)), a1=20.0)
    assert sig is None
    s_sig, s_pat = detect_setup(make_bars((4126, 4127, 4120, 4125)), a1=20.0)
    assert s_sig == "SELL"
    assert s_pat["kind"] == "DOUBLE TOP"


def test_C_wick_touch_is_setup_not_entry_buy():
    sig, pat = detect_dtb(make_bars_buy((4124, 4130, 4123, 4125)), a1=20.0)
    assert sig is None
    s_sig, s_pat = detect_setup(make_bars_buy((4124, 4130, 4123, 4125)), a1=20.0)
    assert s_sig == "BUY"
    assert s_pat["kind"] == "DOUBLE BOTTOM"


# --- Sanity: far-away price -> no setup ---------------------------------------

def test_no_setup_when_far_from_neckline():
    # price > 0.5 ATR above neckline: not actionable
    assert detect_setup(make_bars((4136, 4138, 4134, 4136)), a1=20.0)[0] is None


def test_no_setup_when_far_from_neckline_buy():
    assert detect_setup(make_bars_buy((4114, 4116, 4112, 4114)), a1=20.0)[0] is None
