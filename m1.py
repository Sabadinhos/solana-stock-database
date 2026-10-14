"""SDB: M1 backing chain (core)."""
import json


def token_metrics(conn, mint):
    row = conn.execute("SELECT * FROM tokens WHERE mint=?", (mint,)).fetchone()
    if row is None:
        return None
    chain = json.loads(row["chain_json"] or "[]")

    # Stacked tax (precomputed at ingest, stored in stacked_tax_bps).
    stacked = row["stacked_tax_bps"] or 0
    terminal_price = None
    if row["terminal_symbol"]:
        price_row = conn.execute(
            "SELECT price_usd FROM terminal_prices WHERE symbol=?",
            (row["terminal_symbol"],),
        ).fetchone()
        if price_row and price_row["price_usd"] is not None:
            terminal_price = price_row["price_usd"]
        if terminal_price is None:
            token_row = conn.execute(
                "SELECT price_usd FROM tokens WHERE mint=? OR symbol=? LIMIT 1",
                (row["terminal_mint"], row["terminal_symbol"]),
            ).fetchone()
            terminal_price = token_row["price_usd"] if token_row else None

    # Real exit liquidity: the StonkFun API does NOT expose liquidityUsd (known gap).
    # The chain's minimum marketCapUsd is used as a FRAGILITY proxy (not liquidity).
    # Real Raydium pool liquidity (SOL/USDC) will come from DexScreener, see BACKLOG.
    chain_mcaps = [row["market_cap_usd"]]
    chain_fees = [row["transfer_fee_bps"] or 0]
    for hop in chain:
        r = conn.execute(
            "SELECT market_cap_usd, transfer_fee_bps FROM tokens WHERE mint=?",
            (hop["mint"],),
        ).fetchone()
        if r:
            if r["market_cap_usd"]:
                chain_mcaps.append(r["market_cap_usd"])
            chain_fees.append(r["transfer_fee_bps"] or 0)

    return {
        "mint": row["mint"],
        "symbol": row["symbol"],
        "name": row["name"],
        "image_url": row["image_url"],
        "twitter": row["twitter"],
        "website": row["website"],
        "mode": row["mode"],
        "creator": row["creator"],
        "depth": row["depth"],
        "terminal": {
            "mint": row["terminal_mint"],
            "symbol": row["terminal_symbol"],
            "name": row["terminal_name"],
            "category": row["terminal_category"],
            "categoryLabel": row["terminal_category_label"],
        },
        "chain": chain,
        "stackedTransferTaxBps": stacked,
        "quoteOnlyFees": bool(row["quote_only_fees"]),
        "terminalPriceUsd": terminal_price,
        "transferFeeBps": row["transfer_fee_bps"],
        # Backing fragility (proxy): minimum marketCap in the chain.
        "thinnestLinkMarketCapUsd": min(chain_mcaps),
        "liquidity": {
            "source": "proxy",
            "note": "minimum marketCap in the chain; real pool liquidity in backlog (DexScreener)",
        },
        "market": {
            "priceUsd": row["price_usd"],
            "marketCapUsd": row["market_cap_usd"],
            "fdvUsd": row["fdv_usd"],
            "volume24hUsd": row["volume_24h_usd"],
            "priceChange24h": row["price_change_24h"],
            "peakMarketCapUsd": row["peak_market_cap_usd"],
        },
        "status": row["status"],
        "graduationProgress": row["graduation_progress"],
        "createdAt": row["created_at"],
        "graduatedAt": row["graduated_at"],
    }


def leaderboard_lastro(conn, limit=50):
    """Most fragile backing ranking: lowest exit-liquidity proxy relative to mcap."""
    rows = conn.execute(
        """SELECT mint FROM tokens
           WHERE market_cap_usd IS NOT NULL AND market_cap_usd > 0
           ORDER BY market_cap_usd ASC LIMIT ?""",
        (limit,),
    ).fetchall()
    out = []
    for r in rows:
        m = token_metrics(conn, r["mint"])
        if m:
            out.append(m)
    return out
