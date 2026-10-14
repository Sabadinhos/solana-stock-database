"""Low-cost, resumable launchpad history scraper.

It paginates program signatures, fetches only successful transactions, stores raw JSON,
and resumes from SQLite checkpoints. It deliberately does not claim token launches;
protocol decoders consume these immutable records later.
"""
import argparse
import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

MAX_RPC_BYTES = 16 * 1024 * 1024

PROGRAM_RE = re.compile(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$')


def validate_rpc_url(url):
    parsed = urlparse(url or '')
    if parsed.scheme not in {'https', 'http'} or not parsed.netloc:
        raise ValueError('rpc URL must use http(s)')
    return url


def validate_program_id(program_id):
    if not isinstance(program_id, str) or not PROGRAM_RE.fullmatch(program_id):
        raise ValueError('invalid Solana program ID')
    return program_id


def validate_source(source):
    if not isinstance(source, str) or not re.fullmatch(r'[a-z0-9_]{2,40}', source):
        raise ValueError('invalid source slug')
    return source


def _read_limited(response):
    length = response.headers.get('Content-Length')
    if length and int(length) > MAX_RPC_BYTES:
        raise RuntimeError('RPC response too large')
    data = response.read(MAX_RPC_BYTES + 1)
    if len(data) > MAX_RPC_BYTES:
        raise RuntimeError('RPC response too large')
    return data


def _json_depth(value, depth=0):
    if depth > 80:
        raise RuntimeError('RPC JSON nesting too deep')
    if isinstance(value, dict):
        for item in value.values(): _json_depth(item, depth + 1)
    elif isinstance(value, list):
        for item in value: _json_depth(item, depth + 1)
    return value


_orig_rpc_marker = None


PAGE_LIMIT = 1000
MAX_PAGES_PER_RUN = 20
DEFAULT_DELAY = 0.25


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def rpc(url, method, params, timeout=30):
    validate_rpc_url(url)
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(url, body, {"Content-Type": "application/json"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = _json_depth(json.loads(_read_limited(r).decode()))
            if data.get("error"):
                raise RuntimeError(data["error"])
            return data.get("result")
        except (OSError, ValueError, RuntimeError) as exc:
            if attempt == 4:
                raise
            time.sleep(min(2 ** attempt, 12))
    raise RuntimeError(f"RPC failed: {method}")


def ensure_schema(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS launchpad_backfill_transactions (
      signature TEXT PRIMARY KEY, source TEXT NOT NULL, program_id TEXT NOT NULL,
      slot INTEGER, block_time INTEGER, err_json TEXT, tx_json TEXT,
      fetched_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS launchpad_backfill_checkpoints (
      source TEXT PRIMARY KEY, program_id TEXT NOT NULL, before_signature TEXT,
      pages INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_backfill_source_slot
      ON launchpad_backfill_transactions(source, slot DESC);
    """)
    conn.commit()


def scrape(conn, rpc_url, source, program_id, max_pages=1, delay=DEFAULT_DELAY, successful_only=True):
    validate_rpc_url(rpc_url)
    validate_source(source)
    validate_program_id(program_id)
    max_pages = max(1, min(MAX_PAGES_PER_RUN, int(max_pages)))
    ensure_schema(conn)
    checkpoint = conn.execute(
        "SELECT before_signature, pages FROM launchpad_backfill_checkpoints WHERE source=?", (source,)
    ).fetchone()
    if checkpoint and conn.execute("SELECT program_id FROM launchpad_backfill_checkpoints WHERE source=?", (source,)).fetchone()[0] != program_id:
        raise ValueError("program ID changed for existing source checkpoint")
    before = checkpoint[0] if checkpoint else None
    fetched = inserted = 0
    for page in range(max_pages):
        opts = {"limit": PAGE_LIMIT, "commitment": "confirmed"}
        if before:
            opts["before"] = before
        rows = rpc(rpc_url, "getSignaturesForAddress", [program_id, opts]) or []
        if not rows:
            break
        records = []
        for row in rows:
            sig = row.get("signature")
            if not sig or (successful_only and row.get("err") is not None):
                continue
            tx = rpc(rpc_url, "getTransaction", [sig, {
                "encoding": "jsonParsed", "maxSupportedTransactionVersion": 0,
                "commitment": "confirmed"
            }])
            fetched += 1
            records.append((sig, source, program_id, row.get("slot"), row.get("blockTime"),
                            json.dumps(row.get("err"), separators=(",", ":")),
                            json.dumps(tx, separators=(",", ":")), now()))
        before = rows[-1].get("signature")
        conn.execute("BEGIN IMMEDIATE")
        try:
            cur = conn.executemany("""INSERT OR IGNORE INTO launchpad_backfill_transactions
                (signature, source, program_id, slot, block_time, err_json, tx_json, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", records)
            inserted += cur.rowcount
            conn.execute("""INSERT INTO launchpad_backfill_checkpoints
                (source, program_id, before_signature, pages, updated_at) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET program_id=excluded.program_id,
                before_signature=excluded.before_signature, pages=excluded.pages,
                updated_at=excluded.updated_at""", (source, program_id, before, (checkpoint[1] if checkpoint else 0) + page + 1, now()))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        if len(rows) < PAGE_LIMIT:
            break
        if delay:
            time.sleep(max(0.0, float(delay)))
    return {"source": source, "pages": page + 1 if 'page' in locals() else 0, "fetched": fetched, "inserted": inserted, "before": before}


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--rpc-url", default=os.environ.get("RPC_URL") or os.environ.get("SDB_RPC_URL"))
    p.add_argument("--db", default=os.environ.get("SDB_DB", "data/sdb.db"))
    p.add_argument("--source", required=True)
    p.add_argument("--program-id", required=True)
    p.add_argument("--pages", type=int, default=1)
    p.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    args = p.parse_args(argv)
    if not args.rpc_url:
        p.error("RPC_URL or SDB_RPC_URL is required")
    conn = sqlite3.connect(args.db)
    try:
        print(json.dumps(scrape(conn, args.rpc_url, args.source, args.program_id, args.pages, args.delay)))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
