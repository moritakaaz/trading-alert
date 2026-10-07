#!/usr/bin/env python3
"""Fetch latest forex/market news from Finnhub.

Usage: forex_news.py [--category forex] [--limit N]
Prints JSON: {"news":[{"t":epoch_utc,"headline":..,"summary":..,"url":..}, ...]} newest-first.
Exits non-zero with {"error": ...} on failure.
"""
import sys, json, argparse, urllib.request

sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
from dynamic_credentials import url_with_surrogate_query_param, read_json_response

HOSTS = ["finnhub.io"]
CRED = "custom.finnhub"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", default="forex",
                    choices=["general", "forex", "crypto", "merger"])
    ap.add_argument("--limit", type=int, default=5)
    a = ap.parse_args()
    base = f"https://finnhub.io/api/v1/news?category={a.category}"
    try:
        url = url_with_surrogate_query_param(base, CRED, allowed_hosts=HOSTS)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = read_json_response(urllib.request.urlopen(req, timeout=25))
    except Exception as e:
        print(json.dumps({"error": f"request failed: {e}"})); sys.exit(1)
    if not isinstance(data, list):
        print(json.dumps({"error": str(data)[:200]})); sys.exit(1)
    out = [{"t": n.get("datetime"), "headline": n.get("headline"),
            "summary": (n.get("summary") or "")[:220], "url": n.get("url")}
           for n in data[:a.limit]]
    print(json.dumps({"news": out}))

if __name__ == "__main__":
    main()
