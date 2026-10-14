"""SDB on-chain enrichment over Solana RPC (read-only).

Enriches the top tokens by market cap with:
  - holders: largest accounts and top-10 concentration (getTokenLargestAccounts, getTokenSupply)
  - events: initialize, mint, burn, authority and fee actions (getSignaturesForAddress, getTransaction)
  - pools: owning program of the pool account (getAccountInfo)

Credit strategy (default):
  - signatures are read incrementally with `until` from a stored cursor per mint,
    so a transaction is fetched at most once
  - failed transactions are skipped, they cannot change supply or authority
  - pool owner is refreshed once per POOL_TTL_HOURS
Set SDB_ONCHAIN_LEGACY=1 to restore the previous full re-read for comparison.
"""
import calendar
import os
import time

import db
import helius

LEGACY = os.environ.get("SDB_ONCHAIN_LEGACY", "0") == "1"
MAX_PAGES = int(os.environ.get("SDB_ONCHAIN_MAX_PAGES", "5"))
POOL_TTL_HOURS = float(os.environ.get("SDB_POOL_TTL_HOURS", "24"))
FAILURES = {"count": 0}

# Token / Token-2022 parsed instruction types mapped to event classes
_INIT = {"initializeMint", "initializeMint2", "initializeAccount"}
_MINT = {"mintTo", "mintToChecked"}
_BURN = {"burn", "burnChecked"}
_AUTH = {"setAuthority"}
_FEE = {"transferFeeExtension", "initializeTransferFeeConfig",
        "initializePermanentDelegate", "initializeNonTransferable"}


def _inner(tx):
    groups = list(((tx or {}).get("meta") or {}).get("innerInstructions") or [])
    groups += ((tx or {}).get("transaction") or {}).get("message", {}).get("innerInstructions") or []
    return groups


def _classify(tx):
    """Return the corporate-action classes found in a jsonParsed transaction."""
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
        # inner instructions live in meta for jsonParsed transactions
        for inner in _inner(tx):
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


def _ensure_cursor_table(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS rpc_cursors ("
                 "address TEXT PRIMARY KEY, last_signature TEXT NOT NULL, updated_at TEXT NOT NULL)")


def _fail(exc):
    FAILURES["count"] += 1
    print(f"[onchain] {type(exc).__name__}: {str(exc)[:160]}", flush=True)


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
    except Exception as exc:
        _fail(exc)


def _extract_burn_raw(tx):
    """Sum of raw burn amounts in a jsonParsed transaction."""
    total = 0
    try:
        msg = tx.get("transaction", {}).get("message", {})
        instrs = list(msg.get("instructions", []))
        for inner in _inner(tx):
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


def _new_signatures(conn, mint, max_sigs):
    """Signatures newer than the stored cursor, newest first."""
    if LEGACY:
        sigs = helius.get_signatures_for_address(mint, limit=max_sigs)
        return sigs if isinstance(sigs, list) else []
    row = conn.execute("SELECT last_signature FROM rpc_cursors WHERE address=?", (mint,)).fetchone()
    until = row[0] if row else None
    if not until:
        sigs = helius.get_signatures_for_address(mint, limit=max_sigs)
        return sigs if isinstance(sigs, list) else []
    out, before = [], None
    for _ in range(MAX_PAGES):
        page = helius.get_signatures_for_address(mint, limit=max_sigs, before=before, until=until)
        if not isinstance(page, list) or not page:
            break
        out.extend(page)
        if len(page) < max_sigs:
            break
        before = page[-1].get("signature")
    return out


def _enrich_events(conn, mint, creator, max_sigs, captured_at):
    try:
        sigs = _new_signatures(conn, mint, max_sigs)
        decimals = None
        for s in sigs:
            sig = s.get("signature")
            if not sig:
                continue
            if not LEGACY and s.get("err") is not None:
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
        if sigs and not LEGACY:
            conn.execute(
                "INSERT INTO rpc_cursors (address, last_signature, updated_at) VALUES (?,?,?) "
                "ON CONFLICT(address) DO UPDATE SET last_signature=excluded.last_signature, "
                "updated_at=excluded.updated_at",
                (mint, sigs[0]["signature"], captured_at))
    except Exception as exc:
        _fail(exc)


def _pool_is_fresh(conn, mint, pool):
    if LEGACY:
        return False
    row = conn.execute("SELECT captured_at FROM pools WHERE mint=? AND pool=?", (mint, pool)).fetchone()
    if not row or not row[0]:
        return False
    try:
        age = time.time() - calendar.timegm(time.strptime(row[0], "%Y-%m-%dT%H:%M:%SZ"))
    except ValueError:
        return False
    return age < POOL_TTL_HOURS * 3600


def _enrich_pool(conn, mint, pool, captured_at):
    if _pool_is_fresh(conn, mint, pool):
        return
    try:
        info = helius.get_account_info(pool)
        v = (info or {}).get("value")
        if not v:
            return
        conn.execute(
            "INSERT OR REPLACE INTO pools (mint, pool, program, captured_at) VALUES (?,?,?,?)",
            (mint, pool, v.get("owner"), captured_at))
    except Exception as exc:
        _fail(exc)


def enrich(conn, top_n=100, max_dev_sigs=20):
    """Enrich the top_n tokens by market cap. Incremental upserts, never deletes."""
    _ensure_cursor_table(conn)
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
    """On-demand enrichment of one token, used by /api/token/{mint}/refresh."""
    _ensure_cursor_table(conn)
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
    top = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("SDB_ONCHAIN_TOP_N", "100"))
    t0 = time.time()
    n = enrich(conn, top_n=top)
    stats = helius.snapshot()["total"]
    print(f"enriched {n} tokens in {time.time()-t0:.0f}s | rpc calls={stats['calls']} "
          f"credits={stats['credits']} cache_hits={stats['cacheHits']} failures={FAILURES['count']}")
    helius.flush("onchain")
    conn.close()
