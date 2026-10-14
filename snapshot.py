"""Build small persistent read snapshots for fast anonymous reads."""
import json
from datetime import datetime, timezone


def _put(conn, name, payload):
    conn.execute(
        "INSERT INTO read_snapshots(name, generated_at, payload) VALUES(?,?,?) "
        "ON CONFLICT(name) DO UPDATE SET generated_at=excluded.generated_at, payload=excluded.payload",
        (name, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), json.dumps(payload, ensure_ascii=False, separators=(",", ":"))),
    )


def rebuild(conn):
    import importlib.util
    import sys
    import insights
    import prices
    cards_module = sys.modules.get("cards")
    if cards_module is None or not hasattr(cards_module, "cards"):
        spec = importlib.util.spec_from_file_location("sdb_snapshot_cards", __file__.replace("snapshot.py", "cards.py"))
        cards_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cards_module)
    rows = cards_module.cards(conn, "ALL", 30, 0, "mc")
    stats = {
        "tokenCount": conn.execute("SELECT COUNT(*) c FROM tokens").fetchone()["c"],
        "snapshotCycles": conn.execute("SELECT COUNT(DISTINCT captured_at) c FROM snapshots").fetchone()["c"],
        "rewardCoins": conn.execute("SELECT COUNT(*) c FROM rewards").fetchone()["c"],
        "launches": conn.execute("SELECT COUNT(*) c FROM launches").fetchone()["c"],
        "creators": conn.execute("SELECT COUNT(DISTINCT creator) c FROM tokens WHERE creator IS NOT NULL").fetchone()["c"],
        "firstSnapshotAt": conn.execute("SELECT MIN(captured_at) m FROM snapshots").fetchone()["m"],
        "platformsLive": conn.execute("SELECT COUNT(DISTINCT launchpad) c FROM tokens WHERE launchpad IS NOT NULL AND TRIM(launchpad) <> ''").fetchone()["c"],
        "multiLinkTokens": conn.execute("SELECT COUNT(*) c FROM tokens WHERE COALESCE(depth, 0) > 1").fetchone()["c"],
    }
    _put(conn, "home", {"cards": rows["cards"], "total": rows["total"], "stats": stats})
    assets_fn = getattr(insights, "assets", lambda _conn: [])
    ticker_fn = getattr(prices, "ticker", lambda _conn: [])
    _put(conn, "assets", {"assets": assets_fn(conn)})
    _put(conn, "ticker", {"ticker": ticker_fn(conn)})
    conn.commit()
    return {"cards": len(rows["cards"]), "total": rows["total"]}


def read(conn, name):
    row = conn.execute("SELECT payload FROM read_snapshots WHERE name=?", (name,)).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["payload"])
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    import db
    conn = db.connect()
    try:
        print(rebuild(conn))
    finally:
        conn.close()
