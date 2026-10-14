"""Seed the creator watchlist from the live creator leaderboard."""
import json
import sys

import db
import creator_scan
import m4


def seed(conn, limit=50):
    rows = m4.top_creators(conn, limit=limit, min_launches=2)
    creators = [row["creator"] for row in rows if row.get("creator")]
    creator_scan.add_watchlist(conn, creators, source="leaderboard", priority=limit)
    return {"source": "leaderboard", "limit": limit, "watchlisted": len(creators), "creators": creators}


if __name__ == "__main__":
    conn = db.connect()
    db.init_db(conn)
    try:
        print(json.dumps(seed(conn, int(sys.argv[1]) if len(sys.argv) > 1 else 50)))
    finally:
        conn.close()