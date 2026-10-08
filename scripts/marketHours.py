#!/usr/bin/env python3
"""B34: Shared forex market hours logic.

Single source of truth for the forex-hours gate, used by both
xauusd_entry_tf.sh and xauusd_watchdog.py. Previously duplicated.

Forex hours: Sun 22:00 UTC -> Fri 21:00 UTC, excluding the daily
21:00-22:00 UTC break. All times UTC (DST-immune).
"""
import datetime


def in_forex_hours(now):
    """Return True if `now` (epoch seconds) is within forex trading hours."""
    dt = datetime.datetime.fromtimestamp(now, datetime.timezone.utc)
    hm = dt.strftime("%H:%M")
    if "21:00" <= hm < "22:00":
        return False  # daily break
    wd = dt.weekday()  # Mon=0
    if wd == 5:
        return False  # Saturday
    if wd == 6:
        return dt.hour >= 22  # Sunday from 22:00
    if wd == 4 and dt.hour >= 21:
        return False  # Friday after 21:00
    return True


def in_forex_hours_wd_hm(wd, hm):
    """Variant taking weekday (Mon=0) and HH:MM string, for the engine's
    numeric gate. wd/hm must be UTC."""
    if "21:00" <= hm < "22:00":
        return False
    if wd == 5:
        return False
    if wd == 6:
        return hm >= "22:00"
    if wd == 4 and hm >= "21:00":
        return False
    return True
