from datetime import datetime, timedelta, timezone

RANGES = {
    "1H": timedelta(hours=1),
    "4H": timedelta(hours=4),
    "7D": timedelta(days=7),
    "30D": timedelta(days=30),
    "ALL": None,
}


def cutoff_for(key):
    d = RANGES.get(key, RANGES["ALL"])
    if d is None:
        return None
    return (datetime.now(timezone.utc) - d).strftime("%Y-%m-%dT%H:%M:%SZ")


def cards(conn, range_key="ALL", limit=30, offset=0, sort="mc"):
    cutoff = cutoff_for(range_key)
    where = "WHERE t.created_at >= ?" if cutoff else ""
    params = [cutoff] if cutoff else []
    order = "t.market_cap_usd DESC" if sort == "mc" else "COALESCE(r.distributed_tokens, 0) DESC"
    q = f"""
        SELECT t.mint,
               COALESCE(t2.terminal_symbol, t.quote_symbol) AS terminal,
               r.distributed_tokens, r.payout_count, r.holder_count, r.last_payout_at,
               t.symbol, t.name, t.image_url, t.market_cap_usd, t.price_change_24h,
               t.fdv_usd, t.price_usd, t.volume_24h_usd, t.peak_market_cap_usd,
               t.depth, t.stacked_tax_bps, t.mode, t.status, t.created_at
        FROM tokens t
        LEFT JOIN rewards r ON r.mint = t.mint
        LEFT JOIN tokens t2 ON t2.mint = t.quote_mint
        {where}
        ORDER BY {order}
        LIMIT ? OFFSET ?
    """
    rows = conn.execute(q, params + [limit, offset]).fetchall()
    total = conn.execute(f"SELECT COUNT(*) c FROM tokens t {where}", params).fetchone()["c"]
    return {"total": total, "cards": [dict(r) for r in rows]}
