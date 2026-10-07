#!/usr/bin/env python3
"""Fetch XAU/USD OHLC from Twelve Data.

Usage: xauusd_ohlc.py --interval 5min|1h --outputsize N
Prints JSON: {"values":[{"t":epoch_utc,"o":..,"h":..,"l":..,"c":..}, ...]} oldest-first.
Exits non-zero with {"error": ...} on failure.
"""
import sys, json, argparse, urllib.request, datetime

sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
from dynamic_credentials import url_with_surrogate_query_param, read_json_response

HOSTS = ["api.twelvedata.com"]
CRED = "custom.twelve-data"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", required=True, choices=["5min", "1h"])
    ap.add_argument("--outputsize", type=int, default=60)
    a = ap.parse_args()
    base = (f"https://api.twelvedata.com/time_series?symbol=XAU/USD"
            f"&interval={a.interval}&outputsize={a.outputsize}"
            f"&timezone=UTC&order=ASC&dp=2")
    try:
        url = url_with_surrogate_query_param(base, CRED, allowed_hosts=HOSTS)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = read_json_response(urllib.request.urlopen(req, timeout=25))
    except Exception as e:
        print(json.dumps({"error": f"request failed: {e}"})); sys.exit(1)
    if "values" not in data:
        print(json.dumps({"error": data.get("message", "no values in response")})); sys.exit(1)
    out = []
    for v in data["values"]:
        try:
            dt = datetime.datetime.strptime(v["datetime"], "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=datetime.timezone.utc)
            out.append({"t": int(dt.timestamp()), "o": float(v["open"]),
                        "h": float(v["high"]), "l": float(v["low"]),
                        "c": float(v["close"])})
        except (KeyError, ValueError):
            continue
    print(json.dumps({"values": out}))

if __name__ == "__main__":
    main()
