#!/usr/bin/env python3
"""Upcoming high-impact US release dates from FRED.

Usage: release_calendar.py [--days N]  (default 14 ahead)
Prints JSON: {"events":[{"date":"YYYY-MM-DD","name":..,"release_id":..}, ...]}
sorted by date. Exits non-zero with {"error": ...} on failure.
"""
import sys, json, argparse, urllib.request, datetime

sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
from dynamic_credentials import url_with_surrogate_query_param, read_json_response

HOSTS = ["api.stlouisfed.org"]
CRED = "custom.fred"

# release_id -> (short name, release time ET as (hour, minute))
# NOTE: FRED release 101 (FOMC) emits a placeholder date every day -> unusable;
# FOMC warnings stay on the Finnhub headline keyword detector.
TRACKED = {
    50:  ("NFP", (8, 30)),
    10:  ("CPI", (8, 30)),
    46:  ("PPI", (8, 30)),
    53:  ("GDP", (8, 30)),
}

def get(path):
    url = url_with_surrogate_query_param(
        f"https://api.stlouisfed.org{path}", CRED, allowed_hosts=HOSTS)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return read_json_response(urllib.request.urlopen(req, timeout=25))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    a = ap.parse_args()
    # B36 (P1): use UTC date (not machine timezone)
    today = datetime.datetime.now(datetime.timezone.utc).date()
    horizon = today + datetime.timedelta(days=a.days)
    out = []
    try:
        for rid, (name, _) in TRACKED.items():
            d = get(f"/fred/release/dates?release_id={rid}&file_type=json"
                    f"&include_release_dates_with_no_data=true&sort_order=asc&limit=10000")
            for x in d.get("release_dates", []):
                ds = x.get("date", "")
                # B36: skip placeholder rows (no usable date)
                if not ds or len(ds) < 10:
                    continue
                if today.isoformat() <= ds <= horizon.isoformat():
                    out.append({"date": ds, "name": name, "release_id": rid})
    except Exception as e:
        print(json.dumps({"error": str(e)[:200]})); sys.exit(1)
    out.sort(key=lambda e: (e["date"], e["release_id"]))
    print(json.dumps({"events": out, "tracked": {str(k): v[0] for k, v in TRACKED.items()}}))

if __name__ == "__main__":
    main()
