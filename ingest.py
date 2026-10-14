"""SDB — ingestão (D1-7): carrega o scan em SQLite + busca rewards (M3) e launches (M4).

Fluxo:
  1. lê data/raw/tokens.jsonl (dedupe por mint), monta o grafo de lastro;
  2. grava tokens (catálogo + cadeia) e o primeiro snapshot (série temporal);
  3. busca GET /rewards -> tabela rewards;
  4. busca GET /launches -> tabela launches;
  5. registra um ciclo em `cycles`.
"""
import json
import os
import time

import db
from fetch import paginate, fetch_json, BASE

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("SDB_DATA_DIR", os.path.join(HERE, "data"))
RAW_PATH = os.path.join(DATA_DIR, "raw", "tokens.jsonl")


def log(msg):
    print(msg, flush=True)


def _load_raw_tokens():
    by_mint = {}
    with open(RAW_PATH, encoding="utf-8") as f:
        for line in f:
            t = json.loads(line)
            by_mint[t["mint"]] = t
    return by_mint


def _build_graph(by_mint):
    all_mints = set(by_mint.keys())
    records = {}
    for mint, t in by_mint.items():
        chain = []
        seen = {mint}
        cur = t
        depth = 0
        is_cycle = False
        while cur.get("quote", {}).get("mint") in all_mints:
            nxt = cur["quote"]["mint"]
            if nxt in seen:
                is_cycle = True
                break
            seen.add(nxt)
            chain.append({
                "mint": nxt,
                "symbol": by_mint[nxt].get("symbol"),
                "category": by_mint[nxt].get("quote", {}).get("category"),
            })
            depth += 1
            cur = by_mint[nxt]
        if not is_cycle:
            depth += 1
        term = cur.get("quote", {})
        records[mint] = {
            "depth": depth, "is_cycle": is_cycle,
            "terminal_mint": term.get("mint"),
            "terminal_symbol": term.get("symbol"),
            "terminal_name": term.get("name"),
            "terminal_category": term.get("category"),
            "terminal_category_label": term.get("categoryLabel"),
            "chain_json": json.dumps(chain, ensure_ascii=False),
        }
    return records


def load_tokens(conn, captured_at):
    by_mint = _load_raw_tokens()
    graph = _build_graph(by_mint)
    for mint, t in by_mint.items():
        g = graph[mint]
        m = t.get("market") or {}
        q = t.get("quote") or {}
        links = t.get("links") or {}
        chain = json.loads(g["chain_json"] or "[]")
        stacked = (t.get("transferFee") or {}).get("bps") or 0
        for hop in chain:
            stacked += (by_mint.get(hop["mint"], {}).get("transferFee") or {}).get("bps") or 0
        conn.execute(
            """INSERT OR REPLACE INTO tokens (
              mint,pool,name,symbol,creator,launchpad,mode,quote_only_fees,
              transfer_fee_bps,quote_mint,quote_symbol,quote_name,
              quote_category,quote_category_label,status,graduation_progress,
              graduated_at,created_at,price_usd,market_cap_usd,fdv_usd,
              volume_24h_usd,price_change_24h,peak_market_cap_usd,
              depth,terminal_mint,terminal_symbol,terminal_name,
              terminal_category,terminal_category_label,chain_json,is_cycle,
              image_url,stacked_tax_bps,twitter,website)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                mint, t.get("pool"), t.get("name"), t.get("symbol"), t.get("creator"),
                t.get("launchpad"), t.get("mode"),
                1 if t.get("quoteOnlyFees") else 0,
                (t.get("transferFee") or {}).get("bps"),
                q.get("mint"), q.get("symbol"), q.get("name"),
                q.get("category"), q.get("categoryLabel"),
                t.get("status"), t.get("graduationProgress"),
                t.get("graduatedAt"), t.get("createdAt"),
                m.get("priceUsd"), m.get("marketCapUsd"), m.get("fdvUsd"),
                m.get("volume24hUsd"), m.get("priceChange24h"), m.get("peakMarketCapUsd"),
                g["depth"], g["terminal_mint"], g["terminal_symbol"],
                g["terminal_name"], g["terminal_category"],
                g["terminal_category_label"], g["chain_json"], 1 if g["is_cycle"] else 0,
                t.get("imageUrl"), stacked, links.get("twitter"), links.get("website"),
            ),
        )
        conn.execute(
            """INSERT OR IGNORE INTO snapshots (
              captured_at,mint,price_usd,market_cap_usd,fdv_usd,
              volume_24h_usd,status,graduation_progress,peak_market_cap_usd,
              transfer_fee_bps,quote_symbol,mode)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (captured_at, mint, m.get("priceUsd"), m.get("marketCapUsd"),
             m.get("fdvUsd"), m.get("volume24hUsd"), t.get("status"),
             t.get("graduationProgress"), m.get("peakMarketCapUsd"),
             (t.get("transferFee") or {}).get("bps"), q.get("symbol"), t.get("mode")),
        )
    conn.commit()
    return len(by_mint)


def load_rewards(conn, captured_at):
    # /rewards NÃO pagina o array `data.launches`: devolve os ~12.790 reward coins
    # inteiros em qualquer request. Uma chamada só basta (recentDistributions é paginado
    # e é ignorado aqui).
    d = fetch_json(f"{BASE}/rewards?page=1&pageSize=1")
    items = d.get("data", {}).get("launches", [])
    for it in items:
        q = it.get("quote") or {}
        conn.execute(
            """INSERT OR REPLACE INTO rewards (
              mint,quote_mint,quote_symbol,quote_decimals,
              distributed_raw,distributed_tokens,payout_count,holder_count,
              last_payout_at,captured_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (it.get("mint"), q.get("mint"), q.get("symbol"), q.get("decimals"),
             it.get("distributedRaw"), it.get("distributedTokens"),
             it.get("payoutCount"), it.get("holderCount"),
             it.get("lastPayoutAt"), captured_at),
        )
    conn.commit()
    return len(items)


def load_launches(conn):
    items = paginate("launches", "launches", log=log)
    for it in items:
        q = it.get("quote") or {}
        conn.execute(
            """INSERT OR REPLACE INTO launches (
              mint,pool,name,symbol,creator,quote_mint,quote_symbol,
              launchpad,mode,transfer_fee_bps,start_market_cap_usd,
              target_market_cap_usd,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (it.get("mint"), it.get("pool"), it.get("name"), it.get("symbol"),
             it.get("creator"), q.get("mint"), q.get("symbol"),
             it.get("launchpad"), it.get("mode"),
             (it.get("transferFee") or {}).get("bps"),
             it.get("startMarketCapUsd"), it.get("targetMarketCapUsd"),
             it.get("createdAt")),
        )
    conn.commit()
    return len(items)


def main():
    captured_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    conn = db.connect()
    db.init_db(conn)

    log("=== D1-7 ingest ===")
    t0 = time.time()
    n_tokens = load_tokens(conn, captured_at)
    log(f"tokens + snapshots: {n_tokens} ({time.time()-t0:.1f}s)")

    n_rewards = load_rewards(conn, captured_at)
    log(f"rewards: {n_rewards} ({time.time()-t0:.1f}s)")

    n_launches = load_launches(conn)
    log(f"launches: {n_launches} ({time.time()-t0:.1f}s)")

    # backfill: /tokens não devolve `creator` para ~95% dos tokens; /launches tem.
    conn.execute(
        """UPDATE tokens SET creator = (
             SELECT l.creator FROM launches l WHERE l.mint = tokens.mint
           ) WHERE creator IS NULL"""
    )
    conn.commit()

    # Persist one bounded aggregate per underlying asset and capture timestamp.
    # These rows are the source for asset graphs; they are never reconstructed from current state.
    conn.execute("""
        INSERT OR REPLACE INTO asset_snapshots(
          terminal,captured_at,token_count,market_cap_usd,volume_24h_usd,
          live_count,graduated_count,creator_count
        )
        SELECT terminal_symbol, ?, COUNT(*),
               SUM(COALESCE(market_cap_usd,0)),
               SUM(COALESCE(volume_24h_usd,0)),
               SUM(CASE WHEN status IN ('live','active') THEN 1 ELSE 0 END),
               SUM(CASE WHEN status='graduated' THEN 1 ELSE 0 END),
               COUNT(DISTINCT creator)
        FROM tokens
        WHERE terminal_symbol IS NOT NULL AND terminal_symbol <> ''
        GROUP BY terminal_symbol
    """, (captured_at,))
    conn.commit()

    conn.execute(
        "INSERT INTO cycles (captured_at, token_count, reward_count, launch_count) VALUES (?,?,?,?)",
        (captured_at, n_tokens, n_rewards, n_launches),
    )
    conn.commit()

    # resumo
    tot = conn.execute("SELECT COUNT(*) c FROM tokens").fetchone()["c"]
    snp = conn.execute("SELECT COUNT(*) c FROM snapshots").fetchone()["c"]
    rew = conn.execute("SELECT COUNT(*) c FROM rewards").fetchone()["c"]
    lau = conn.execute("SELECT COUNT(*) c FROM launches").fetchone()["c"]
    log(f"\n=== DB pronto === tokens={tot} snapshots={snp} rewards={rew} launches={lau} "
        f"({time.time()-t0:.1f}s)")
    conn.close()


if __name__ == "__main__":
    main()
