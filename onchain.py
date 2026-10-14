"""SDB – enriquecimento on-chain via Helius (somente leitura).

Enriquece um subconjunto prioritário (top tokens por market cap) com:
  - holders  : maiores contas + concentração (getTokenLargestAccounts + getTokenSupply)
  - eventos  : ações corporativas do mint (mint/burn/fee/authority) via getSignaturesForAddress
  - pools    : existência do pool Raydium e seu programa (getAccountInfo)

Roda fora do caminho do usuário (nunca no request). Budget: top_n controla o
custo em credits; começa pequeno e cresce.
"""
import time

import db
import helius

# tipos de instrução (Token / Token-2022, jsonParsed) -> classe de evento
_INIT = {"initializeMint", "initializeMint2", "initializeAccount"}
_MINT = {"mintTo", "mintToChecked"}
_BURN = {"burn", "burnChecked"}
_AUTH = {"setAuthority"}
_FEE = {"transferFeeExtension", "initializeTransferFeeConfig",
        "initializePermanentDelegate", "initializeNonTransferable"}


def _classify(tx):
    """Extrai as classes de ação corporativa de uma transação jsonParsed."""
    kinds = set()
    try:
        msg = tx.get("transaction", {}).get("message", {})
        for instr in msg.get("instructions", []):
            t = (instr.get("parsed") or {}).get("type")
            if not t:
                continue
            if t in _INIT:
                kinds.add("initialize")
            elif t in _MINT:
                kinds.add("mint")
            elif t in _BURN:
                kinds.add("burn")
            elif t in _AUTH:
                kinds.add("authority")
            elif t in _FEE:
                kinds.add("fee")
        # instruções aninhadas (innerInstructions)
        for inner in msg.get("innerInstructions", []):
            for instr in inner.get("instructions", []):
                t = (instr.get("parsed") or {}).get("type")
                if t in _MINT:
                    kinds.add("mint")
                elif t in _BURN:
                    kinds.add("burn")
                elif t in _AUTH:
                    kinds.add("authority")
                elif t in _FEE:
                    kinds.add("fee")
    except Exception:
        pass
    return kinds


def _enrich_holders(conn, mint, captured_at):
    try:
        res = helius.get_token_largest_accounts(mint)
        val = (res or {}).get("value") or []
        sup = helius.get_token_supply(mint)
        total = float((sup or {}).get("value", {}).get("uiAmountString") or 0)
        for it in val[:20]:
            amt = float(it.get("uiAmountString") or it.get("uiAmount") or 0)
            pct = (amt / total) if total else 0.0
            conn.execute(
                "INSERT OR REPLACE INTO holders (mint, owner, amount_ui, pct, captured_at) "
                "VALUES (?,?,?,?,?)",
                (mint, it.get("address"), amt, pct, captured_at))
        if total:
            top10 = sum(float(x.get("uiAmountString") or 0) for x in val[:10])
            conn.execute(
                "UPDATE tokens SET holder_top10_share=? WHERE mint=?",
                (round(top10 / total, 4), mint))
    except Exception:
        pass


def _extract_burn_raw(tx):
    """Soma dos valores raw das instruções burn/burnChecked numa transação jsonParsed."""
    total = 0
    try:
        msg = tx.get("transaction", {}).get("message", {})
        instrs = list(msg.get("instructions", []))
        for inner in msg.get("innerInstructions", []):
            instrs += inner.get("instructions", [])
        for instr in instrs:
            p = instr.get("parsed") or {}
            if p.get("type") in ("burn", "burnChecked"):
                amt = (p.get("info") or {}).get("amount")
                if amt:
                    total += int(amt)
    except Exception:
        pass
    return total


def _enrich_events(conn, mint, creator, max_sigs, captured_at):
    try:
        sigs = helius.get_signatures_for_address(mint, limit=max_sigs)
        if not isinstance(sigs, list):
            return
        decimals = None
        for s in sigs:
            sig = s.get("signature")
            if not sig:
                continue
            tx = helius.get_transaction(sig)
            if not tx:
                continue
            for kind in _classify(tx):
                conn.execute(
                    "INSERT OR IGNORE INTO token_events "
                    "(mint, wallet, kind, signature, captured_at) VALUES (?,?,?,?,?)",
                    (mint, creator, kind, sig, captured_at))
            burn_raw = _extract_burn_raw(tx)
            if burn_raw > 0:
                if decimals is None:
                    sup = helius.get_token_supply(mint)
                    decimals = (sup or {}).get("value", {}).get("decimals", 0)
                amount_ui = burn_raw / (10 ** decimals) if decimals else burn_raw
                conn.execute(
                    "INSERT OR IGNORE INTO burns "
                    "(mint, signature, amount_raw, decimals, amount_ui, captured_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (mint, sig, burn_raw, decimals, amount_ui, captured_at))
    except Exception:
        pass


def _enrich_pool(conn, mint, pool, captured_at):
    try:
        info = helius.get_account_info(pool)
        v = (info or {}).get("value")
        if not v:
            return
        owner = v.get("owner")
        conn.execute(
            "INSERT OR REPLACE INTO pools (mint, pool, program, captured_at) "
            "VALUES (?,?,?,?)",
            (mint, pool, owner, captured_at))
    except Exception:
        pass


def enrich(conn, top_n=100, max_dev_sigs=20):
    """Enriquece os top_n tokens por market cap. Incremental: UPSERT, nunca destrói."""
    captured_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    rows = conn.execute(
        "SELECT mint, creator, pool FROM tokens "
        "WHERE market_cap_usd IS NOT NULL "
        "ORDER BY market_cap_usd DESC LIMIT ?",
        (top_n,)).fetchall()
    for r in rows:
        mint, creator, pool = r["mint"], r["creator"], r["pool"]
        _enrich_holders(conn, mint, captured_at)
        _enrich_events(conn, mint, creator, max_dev_sigs, captured_at)
        if pool:
            _enrich_pool(conn, mint, pool, captured_at)
    conn.commit()
    return len(rows)


def enrich_token(conn, mint, max_dev_sigs=20):
    """Enriquecimento on-chain sob demanda de UM token (usado pelo /refresh, tier pago)."""
    row = conn.execute(
        "SELECT creator, pool FROM tokens WHERE mint=?", (mint,)).fetchone()
    if not row:
        return False
    captured_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _enrich_holders(conn, mint, captured_at)
    _enrich_events(conn, mint, row["creator"], max_dev_sigs, captured_at)
    if row["pool"]:
        _enrich_pool(conn, mint, row["pool"], captured_at)
    conn.commit()
    return True


if __name__ == "__main__":
    import sys
    conn = db.connect()
    db.init_db(conn)
    top = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    t0 = time.time()
    n = enrich(conn, top_n=top)
    h = conn.execute("SELECT COUNT(*) FROM holders").fetchone()[0]
    e = conn.execute("SELECT COUNT(*) FROM token_events").fetchone()[0]
    p = conn.execute("SELECT COUNT(*) FROM pools").fetchone()[0]
    print(f"enriquecidos {n} tokens em {time.time()-t0:.0f}s | "
          f"holders={h} eventos={e} pools={p}")
    conn.close()
