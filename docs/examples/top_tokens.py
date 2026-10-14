"""Print SDB tokens above a market cap floor.

Usage: python top_tokens.py [min_market_cap_usd] [base_url]
"""
import json
import sys
import urllib.request

floor = float(sys.argv[1]) if len(sys.argv) > 1 else 1_000_000
base = sys.argv[2] if len(sys.argv) > 2 else "https://solanastockdatabase.com"

req = urllib.request.Request(f"{base}/api/cards?limit=500", headers={"User-Agent": "sdb-example/1.0"})
with urllib.request.urlopen(req, timeout=30) as r:
    cards = json.load(r)["cards"]

top = [c for c in cards if (c.get("market_cap_usd") or 0) >= floor]
top.sort(key=lambda c: c["market_cap_usd"], reverse=True)
for c in top:
    print(f"{c['symbol']:<10} {c['terminal'] or '-':<6} ${c['market_cap_usd']:>14,.0f}  {c['mint']}")
print(f"{len(top)} tokens >= ${floor:,.0f}")
