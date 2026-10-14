from datetime import datetime, timedelta, timezone


def _cutoff(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _terminal_of_quote(conn, quote_mint, quote_symbol):
    if quote_mint:
        r = conn.execute("SELECT terminal_symbol FROM tokens WHERE mint=?", (quote_mint,)).fetchone()
        if r and r["terminal_symbol"]:
            return r["terminal_symbol"]
    return quote_symbol


def assets(conn):
    rows = conn.execute(
        """SELECT terminal_symbol, terminal_category, terminal_category_label,
                  COUNT(*) token_count, SUM(market_cap_usd) total_mcap,
                  COUNT(DISTINCT creator) creators
           FROM tokens
           WHERE terminal_symbol IS NOT NULL
           GROUP BY terminal_symbol, terminal_category, terminal_category_label
           ORDER BY token_count DESC"""
    ).fetchall()

    yield_rows = conn.execute(
        """SELECT COALESCE(t2.terminal_symbol, r.quote_symbol) terminal,
                  SUM(r.distributed_tokens) yield_total, COUNT(*) coins
           FROM rewards r LEFT JOIN tokens t2 ON t2.mint = r.quote_mint
           GROUP BY terminal"""
    ).fetchall()
    yield_map = {r["terminal"]: r for r in yield_rows}

    out = []
    for r in rows:
        y = yield_map.get(r["terminal_symbol"])
        out.append({
            "symbol": r["terminal_symbol"],
            "category": r["terminal_category"],
            "categoryLabel": r["terminal_category_label"],
            "tokenCount": r["token_count"],
            "totalMarketCapUsd": r["total_mcap"],
            "creators": r["creators"],
            "yieldTotal": y["yield_total"] if y else 0.0,
            "rewardCoins": y["coins"] if y else 0,
        })
    return out


def asset_detail(conn, symbol, limit=200, offset=0):
    meta = conn.execute(
        """SELECT terminal_symbol, terminal_category, terminal_category_label,
                  COUNT(*) token_count, SUM(market_cap_usd) total_mcap
           FROM tokens WHERE terminal_symbol=? GROUP BY terminal_symbol, terminal_category, terminal_category_label""",
        (symbol,),
    ).fetchone()
    if meta is None:
        return None

    total = conn.execute(
        "SELECT COUNT(*) c FROM tokens WHERE terminal_symbol=?", (symbol,)
    ).fetchone()["c"]
    tokens = conn.execute(
        """SELECT mint, symbol, name, image_url, market_cap_usd, price_change_24h,
                  stacked_tax_bps, depth, status, creator
           FROM tokens WHERE terminal_symbol=?
           ORDER BY market_cap_usd DESC LIMIT ? OFFSET ?""",
        (symbol, limit, offset),
    ).fetchall()

    y = conn.execute(
        """SELECT SUM(r.distributed_tokens) y, COUNT(*) coins
           FROM rewards r LEFT JOIN tokens t2 ON t2.mint = r.quote_mint
           WHERE COALESCE(t2.terminal_symbol, r.quote_symbol) = ?""",
        (symbol,),
    ).fetchone()

    return {
        "symbol": symbol,
        "category": meta["terminal_category"],
        "categoryLabel": meta["terminal_category_label"],
        "tokenCount": meta["token_count"],
        "returnedTokenCount": len(tokens),
        "tokenOffset": offset,
        "tokenLimit": limit,
        "tokenTotal": total,
        "totalMarketCapUsd": meta["total_mcap"],
        "yieldTotal": y["y"] or 0.0,
        "rewardCoins": y["coins"] or 0,
        "tokens": [dict(t) for t in tokens],
    }


def quote_market_caps(conn):
    rows = conn.execute(
        """SELECT terminal_symbol symbol, SUM(market_cap_usd) crypto_mcap
           FROM tokens
           WHERE terminal_symbol IS NOT NULL AND market_cap_usd IS NOT NULL
           GROUP BY terminal_symbol"""
    ).fetchall()
    return {r["symbol"]: {"cryptoMarketCapUsd": r["crypto_mcap"]} for r in rows}


def survival(conn):
    total = conn.execute("SELECT COUNT(*) c FROM tokens").fetchone()["c"]
    grad = conn.execute("SELECT COUNT(*) c FROM tokens WHERE status='graduated'").fetchone()["c"]

    by_cat = conn.execute(
        """SELECT terminal_category,
                  COUNT(*) total, SUM(status='graduated') graduated,
                  AVG(CASE WHEN peak_market_cap_usd > 0
                      THEN market_cap_usd / peak_market_cap_usd END) avg_drawdown
           FROM tokens
           WHERE terminal_category IS NOT NULL
           GROUP BY terminal_category
           ORDER BY total DESC"""
    ).fetchall()

    return {
        "total": total,
        "graduated": grad,
        "graduationRate": grad / total if total else 0,
        "byCategory": [dict(r) for r in by_cat],
    }


def attention(conn, days=7):
    now_cut = _cutoff(days)
    prior_cut = _cutoff(days * 2)

    cur = conn.execute(
        """SELECT COALESCE(t2.terminal_symbol, l.quote_symbol) terminal, COUNT(*) c
           FROM launches l LEFT JOIN tokens t2 ON t2.mint = l.quote_mint
           WHERE l.created_at >= ? GROUP BY terminal""",
        (now_cut,),
    ).fetchall()
    prior = conn.execute(
        """SELECT COALESCE(t2.terminal_symbol, l.quote_symbol) terminal, COUNT(*) c
           FROM launches l LEFT JOIN tokens t2 ON t2.mint = l.quote_mint
           WHERE l.created_at >= ? AND l.created_at < ? GROUP BY terminal""",
        (prior_cut, now_cut),
    ).fetchall()

    prior_map = {r["terminal"]: r["c"] for r in prior}
    out = []
    for r in cur:
        p = prior_map.get(r["terminal"], 0)
        change = ((r["c"] - p) / p) if p else None
        out.append({
            "terminal": r["terminal"],
            "launches": r["c"],
            "priorLaunches": p,
            "changePct": round(change * 100, 1) if change is not None else None,
        })
    out.sort(key=lambda x: -x["launches"])
    return {"windowDays": days, "assets": out}


def creator_x(conn, creator):
    rows = conn.execute(
        "SELECT twitter FROM tokens WHERE creator=? AND twitter IS NOT NULL", (creator,)
    ).fetchall()
    if not rows:
        return None
    from collections import Counter
    cnt = Counter(r["twitter"] for r in rows)
    total = sum(cnt.values())
    top, top_n = cnt.most_common(1)[0]
    share = round(top_n / total, 2)

    verified = None
    try:
        v = conn.execute(
            "SELECT handle FROM verified_creators WHERE wallet=?", (creator,)
        ).fetchone()
        if v:
            verified = v["handle"]
    except Exception:
        pass

    if verified:
        status, display = "verified", verified
    elif share >= 0.66 and total >= 3:
        status, display = "likely", top
    else:
        status, display = "none", top

    return {
        "verified": status == "verified",
        "status": status,
        "note": "X accounts linked by this wallet's tokens. Association only — not proof of ownership.",
        "dominant": top,
        "dominantShare": share,
        "linkedCount": total,
        "all": [{"handle": h, "count": n} for h, n in cnt.most_common(8)],
    }
