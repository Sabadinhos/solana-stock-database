"""Truthful read model for source-backed editorial and curated creator identity."""


def news(conn, limit=30, offset=0, asset=None):
    limit = min(max(int(limit), 1), 100)
    offset = max(int(offset), 0)
    where = "WHERE asset_symbol=?" if asset else ""
    args = [asset] if asset else []
    total = conn.execute(f"SELECT COUNT(*) c FROM news_evidence {where}", args).fetchone()["c"]
    rows = conn.execute(
        f"""SELECT id, source_label sourceLabel, source_url sourceUrl, title,
                   published_at publishedAt, retrieved_at retrievedAt,
                   asset_symbol assetSymbol, project_key projectKey, summary
            FROM news_evidence {where}
            ORDER BY published_at DESC, id DESC LIMIT ? OFFSET ?""",
        args + [limit, offset],
    ).fetchall()
    return {"available": bool(total), "total": total, "limit": limit,
            "offset": offset, "items": [dict(r) for r in rows]}


def creators(conn, limit=50, offset=0):
    limit = min(max(int(limit), 1), 100)
    offset = max(int(offset), 0)
    total = conn.execute("SELECT COUNT(*) c FROM creator_registry").fetchone()["c"]
    rows = conn.execute(
        """SELECT wallet, display_name displayName, avatar_url avatarUrl,
                  profile_url profileUrl, source_label sourceLabel, source_url sourceUrl,
                  verified_at verifiedAt, note
           FROM creator_registry ORDER BY display_name, wallet LIMIT ? OFFSET ?""",
        (limit, offset),
    ).fetchall()
    return {"available": bool(total), "total": total, "limit": limit,
            "offset": offset, "items": [dict(r) for r in rows],
            "identityPolicy": "Only curated source-backed identities appear here; other wallets remain indexed activity."}


def creator(conn, wallet):
    row = conn.execute(
        """SELECT wallet, display_name displayName, avatar_url avatarUrl,
                  profile_url profileUrl, source_label sourceLabel, source_url sourceUrl,
                  verified_at verifiedAt, note FROM creator_registry WHERE wallet=?""",
        (wallet,),
    ).fetchone()
    return dict(row) if row else None


def init_schema(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS news_evidence (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      source_label TEXT NOT NULL, source_url TEXT NOT NULL UNIQUE,
      title TEXT NOT NULL, published_at TEXT, retrieved_at TEXT NOT NULL,
      asset_symbol TEXT, project_key TEXT, summary TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_news_published ON news_evidence(published_at DESC);
    CREATE INDEX IF NOT EXISTS idx_news_asset ON news_evidence(asset_symbol);
    CREATE TABLE IF NOT EXISTS creator_registry (
      wallet TEXT PRIMARY KEY, display_name TEXT NOT NULL, avatar_url TEXT,
      profile_url TEXT NOT NULL, source_label TEXT NOT NULL, source_url TEXT NOT NULL,
      verified_at TEXT NOT NULL, note TEXT
    );
    """)
    conn.commit()
