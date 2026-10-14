"""SDB: M3 yield in stock (core, the product headline).

Reward coins pay the transfer tax to holders in the quote token. A reward
coin paired with NVDAX pays NVDAX. This module measures that, in terminal asset units.
"""


def resolve_terminal(conn, quote_mint, quote_symbol):
    """Resolve the terminal asset of a reward coin: if the quote is another StonkFun token,
    use its precomputed terminal; otherwise the quote is the terminal."""
    if quote_mint:
        r = conn.execute(
            "SELECT terminal_symbol, terminal_category, terminal_category_label "
            "FROM tokens WHERE mint=?",
            (quote_mint,),
        ).fetchone()
        if r and r["terminal_symbol"]:
            return r["terminal_symbol"], r["terminal_category"], r["terminal_category_label"]
    return quote_symbol, None, None


def rendimento_por_terminal(conn):
    """Aggregate distributed yield by terminal asset. Return a ranking by total."""
    rows = conn.execute("SELECT * FROM rewards").fetchall()
    agg = {}
    for r in rows:
        tsym, tcat, tlabel = resolve_terminal(conn, r["quote_mint"], r["quote_symbol"])
        key = tsym or "unknown"
        a = agg.setdefault(key, {
            "terminal": key, "category": tcat, "categoryLabel": tlabel,
            "distributedTokens": 0.0, "coins": 0, "payouts": 0, "holders": 0,
        })
        a["distributedTokens"] += r["distributed_tokens"] or 0.0
        a["coins"] += 1
        a["payouts"] += r["payout_count"] or 0
        a["holders"] += r["holder_count"] or 0
    out = sorted(agg.values(), key=lambda x: -x["distributedTokens"])
    return out


def leaderboard_rendimento(conn, category="xstock", limit=50):
    """Which memstocks (reward coins) paid the most in assets of a category (e.g. xstock).

    Sorted by total distributed in terminal asset units.
    """
    rows = conn.execute("SELECT * FROM rewards").fetchall()
    results = []
    for r in rows:
        tsym, tcat, tlabel = resolve_terminal(conn, r["quote_mint"], r["quote_symbol"])
        if category and tcat != category:
            continue
        tok = conn.execute(
            "SELECT symbol, name FROM tokens WHERE mint=?", (r["mint"],)
        ).fetchone()
        results.append({
            "mint": r["mint"],
            "symbol": tok["symbol"] if tok else None,
            "name": tok["name"] if tok else None,
            "quoteMint": r["quote_mint"],
            "terminal": tsym,
            "terminalCategory": tcat,
            "terminalCategoryLabel": tlabel,
            "distributedTokens": r["distributed_tokens"] or 0.0,
            "distributedRaw": r["distributed_raw"],
            "payoutCount": r["payout_count"] or 0,
            "holderCount": r["holder_count"] or 0,
            "lastPayoutAt": r["last_payout_at"],
        })
    results.sort(key=lambda x: -x["distributedTokens"])
    return results[:limit]


def fee_distribution_simulation(held_usd, volume_24h_usd, market_cap_usd,
                                stacked_fee_bps, terminal_price_usd,
                                periods=(1, 30, 365)):
    """Estimate fee rewards for a proportional holder without making claims.

    Returns a stable, JSON-friendly shape. Missing or non-positive inputs produce an
    unavailable result instead of a fabricated zero. The calculation is deliberately
    separate from HTTP and the frontend so it can be tested and reused by MCP later.
    """
    values = (held_usd, volume_24h_usd, market_cap_usd,
              stacked_fee_bps, terminal_price_usd)
    try:
        held, volume, market_cap, fee_bps, terminal_price = (float(x) for x in values)
    except (TypeError, ValueError):
        return {"available": False, "reason": "invalid_input", "periods": {}}
    if any(x < 0 for x in (held, volume, market_cap, fee_bps, terminal_price)):
        return {"available": False, "reason": "invalid_input", "periods": {}}
    if not held:
        return {"available": True, "reason": "zero_holding", "periods": {
            str(int(days)): {"usd": 0.0, "terminalUnits": 0.0} for days in periods}}
    if not volume or not market_cap or not fee_bps:
        return {"available": False, "reason": "missing_volume_market_cap_or_fee", "periods": {}}
    if not terminal_price:
        return {"available": False, "reason": "missing_terminal_price", "periods": {}}
    daily_usd = volume * (fee_bps / 10000.0) * (held / market_cap)
    result = {}
    for days in periods:
        try:
            n_days = float(days)
        except (TypeError, ValueError):
            continue
        if n_days <= 0:
            continue
        usd = daily_usd * n_days
        result[str(int(n_days) if n_days.is_integer() else n_days)] = {
            "usd": usd, "terminalUnits": usd / terminal_price,
        }
    return {"available": True, "reason": None, "periods": result}


def token_rewards(conn, mint):
    """Yield detail for a specific reward coin."""
    r = conn.execute("SELECT * FROM rewards WHERE mint=?", (mint,)).fetchone()
    if r is None:
        return None
    tsym, tcat, tlabel = resolve_terminal(conn, r["quote_mint"], r["quote_symbol"])
    return {
        "mint": r["mint"],
        "quoteMint": r["quote_mint"],
        "quoteSymbol": r["quote_symbol"],
        "terminal": tsym,
        "terminalCategory": tcat,
        "terminalCategoryLabel": tlabel,
        "distributedTokens": r["distributed_tokens"],
        "distributedRaw": r["distributed_raw"],
        "payoutCount": r["payout_count"],
        "holderCount": r["holder_count"],
        "lastPayoutAt": r["last_payout_at"],
    }
