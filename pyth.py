"""Optional Pyth Hermes collector for persisted terminal-asset prices.

Configuration is intentionally explicit: PYTH_API_KEY and PYTH_FEEDS_JSON must be
provided by the operator. Without them the collector exits cleanly and records no
fabricated values.
"""
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import db

API_URL = os.environ.get(
    "PYTH_HERMES_URL",
    "https://hermes.pyth.network/v2/updates/price/latest",
)


def _feeds():
    raw = os.environ.get("PYTH_FEEDS_JSON", "")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return {str(k).upper(): str(v) for k, v in data.items() if v}
    except (TypeError, ValueError):
        return {}


def collect():
    key = os.environ.get("PYTH_API_KEY", "").strip()
    feeds = _feeds()
    if not key:
        return {"status": "unavailable", "reason": "missing_api_key", "collected": 0}
    if not feeds:
        return {"status": "unavailable", "reason": "missing_feed_map", "collected": 0}
    ids = list(feeds.values())
    query = urllib.parse.urlencode([( "ids[]", feed) for feed in ids])
    request = urllib.request.Request(
        f"{API_URL}?{query}",
        headers={"Authorization": f"Bearer {key}", "User-Agent": "SDB/1.0"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.loads(response.read())
    parsed = payload.get("parsed") or []
    by_id = {str(item.get("id", "")).lower(): item for item in parsed}
    captured = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = db.connect()
    try:
        db.init_db(conn)
        saved = 0
        for terminal, feed_id in feeds.items():
            item = by_id.get(feed_id.lower())
            price = (item or {}).get("price") or {}
            if not price.get("price") or price.get("expo") is None:
                continue
            value = float(price["price"]) * (10 ** int(price["expo"]))
            if value <= 0:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO asset_feeds(terminal,feed_id,asset_type,resolved_at) VALUES(?,?,?,?)",
                (terminal, feed_id, "equity", captured),
            )
            conn.execute(
                "INSERT OR IGNORE INTO asset_prices(terminal,price_usd,conf,publish_time,captured_at) VALUES(?,?,?,?,?)",
                (terminal, value, float(price["conf"]) * (10 ** int(price["expo"])) if price.get("conf") is not None else None,
                 int(price["publish_time"]) if price.get("publish_time") is not None else None, captured),
            )
            saved += 1
        conn.commit()
        return {"status": "ok", "collected": saved, "capturedAt": captured}
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        result = collect()
        print(json.dumps(result, separators=(",", ":")), flush=True)
    except Exception as exc:
        print(json.dumps({"status": "error", "reason": type(exc).__name__}, separators=(",", ":")), flush=True)
        raise
