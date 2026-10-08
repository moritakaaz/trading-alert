#!/usr/bin/env python3
"""B44: Shared state helper with lock + atomic write.

Minimal helper to avoid duplicating fcntl-lock + tempfile+os.replace
logic across scripts. Usage:

    from state import load_state, save_state, save_state_keys

    st = load_state("~/hooks/state/xauusd_entry_m5.json")
    save_state_keys("~/hooks/state/xauusd_entry_m5.json", {"alert_on": True})
"""
import fcntl
import json
import os
import tempfile


def _lock_path(path):
    return path + ".lock"


def load_state(path):
    """Load JSON state file, return {} on any error."""
    try:
        with open(os.path.expanduser(path)) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(path, data):
    """Atomic write of full state dict under an exclusive lock."""
    path = os.path.expanduser(path)
    lock_path = _lock_path(path)
    with open(lock_path, "a+") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            d = os.path.dirname(path) or "."
            os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=d, prefix=".state_tmp_")
            try:
                with os.fdopen(fd, "w") as tf:
                    json.dump(data, tf)
                os.replace(tmp, path)
            finally:
                try:
                    os.unlink(tmp)
                except Exception:
                    pass
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def save_state_keys(path, updates):
    """Read-modify-write: merge `updates` dict into existing state.

    Never writes back a stale full dict — always re-reads under lock first.
    """
    path = os.path.expanduser(path)
    lock_path = _lock_path(path)
    with open(lock_path, "a+") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            try:
                with open(path) as rf:
                    s = json.load(rf)
            except Exception:
                s = {}
            s.update(updates)
            d = os.path.dirname(path) or "."
            os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=d, prefix=".state_tmp_")
            try:
                with os.fdopen(fd, "w") as tf:
                    json.dump(s, tf)
                os.replace(tmp, path)
            finally:
                try:
                    os.unlink(tmp)
                except Exception:
                    pass
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)
