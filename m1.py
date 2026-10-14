"""SDB — M1 Cadeia de Lastro (núcleo)."""
import json


def token_metrics(conn, mint):
    row = conn.execute("SELECT * FROM tokens WHERE mint=?", (mint,)).fetchone()
    if row is None:
        return None
    chain = json.loads(row["chain_json"] or "[]")

    # Taxa Empilhada (pré-calculada no ingest, guardada em stacked_tax_bps).
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

    # Liquidez de Saída Real: a API StonkFun NÃO expõe liquidityUsd (gap conhecido).
    # Usamos marketCapUsd mínimo da cadeia como proxy de FRAGILIDADE (não de liquidez).
    # A liquidez real do pool Raydium (SOL/USDC) será lida via DexScreener — ver BACKLOG.
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
        # Fragilidade de Lastro (proxy): marketCap mínimo da cadeia.
        "thinnestLinkMarketCapUsd": min(chain_mcaps),
        "liquidity": {
            "source": "proxy",
            "note": "marketCap mínimo da cadeia; liquidez real do pool em backlog (DexScreener)",
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
    """Ranking de lastro mais frágil: menor proxy de liquidez de saída relativo ao mcap."""
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
