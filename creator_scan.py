"""Read-only creator wallet verifier.

Scans Solana transaction signatures and records token mints for which the
wallet appears as the mint authority in an initializeMint instruction. This
is evidence of creation authority, not proof of identity or ownership.
"""
import argparse
import json
import time

import db
import helius


def _instructions(tx):
    msg = ((tx or {}).get("transaction") or {}).get("message") or {}
    out = list(msg.get("instructions") or [])
    for group in msg.get("innerInstructions") or []:
        out.extend(group.get("instructions") or [])
    return out


def _created_mints(tx, creator):
    found = []
    for instr in _instructions(tx):
        parsed = instr.get("parsed") or {}
        if parsed.get("type") not in ("initializeMint", "initializeMint2"):
            continue
        info = parsed.get("info") or {}
        if info.get("mintAuthority") == creator and info.get("mint"):
            found.append(info["mint"])
    return sorted(set(found))


def scan_creator(conn, creator, max_pages=50, page_size=100, before=None):
    if not creator or len(creator) < 20:
        raise ValueError("invalid creator address")
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    run = conn.execute(
        "INSERT INTO creator_scan_runs (creator,started_at,status,cursor_before) VALUES (?,?,?,?)",
        (creator, started, "running", before),
    )
    run_id = run.lastrowid
    conn.commit()
    signatures = checked = found = 0
    cursor = before
    try:
        for _ in range(max_pages):
            batch = helius.get_signatures_for_address(creator, limit=page_size, before=cursor)
            if not batch:
                break
            signatures += len(batch)
            for item in batch:
                sig = item.get("signature")
                if not sig:
                    continue
                tx = helius.get_transaction(sig)
                checked += 1
                for mint in _created_mints(tx, creator):
                    cur = conn.execute(
                        "INSERT OR IGNORE INTO creator_token_evidence "
                        "(creator,mint,first_seen_at,signature,slot,evidence_type,source) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (creator, mint, item.get("blockTime") and time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(item["blockTime"])) or started,
                         sig, item.get("slot"), "mint-authority", "solana-rpc"),
                    )
                    found += cur.rowcount
            conn.commit()
            cursor = batch[-1].get("signature")
            if len(batch) < page_size:
                break
        finished = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        conn.execute(
            "UPDATE creator_scan_runs SET finished_at=?,status=?,signatures_scanned=?,transactions_checked=?,tokens_found=?,cursor_after=? WHERE id=?",
            (finished, "ok", signatures, checked, found, cursor, run_id),
        )
        conn.commit()
        return {"runId": run_id, "creator": creator, "status": "ok", "signaturesScanned": signatures,
                "transactionsChecked": checked, "tokensFound": found, "cursorAfter": cursor}
    except Exception as exc:
        conn.execute(
            "UPDATE creator_scan_runs SET finished_at=?,status=?,signatures_scanned=?,transactions_checked=?,tokens_found=?,cursor_after=?,error=? WHERE id=?",
            (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "error", signatures, checked, found, cursor, str(exc)[:500], run_id),
        )
        conn.commit()
        raise


def add_watchlist(conn, creators, source='leaderboard', priority=0):
    now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    for creator in sorted(set(creators)):
        if creator and len(creator) >= 20:
            conn.execute(
                'INSERT INTO creator_watchlist (creator,label,source,priority,enabled,added_at) VALUES (?,?,?,?,1,?) '
                'ON CONFLICT(creator) DO UPDATE SET source=excluded.source, priority=MAX(priority, excluded.priority), enabled=1',
                (creator, None, source, priority, now),
            )
    conn.commit()
    return len(set(creators))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("creator")
    ap.add_argument("--max-pages", type=int, default=50)
    ap.add_argument("--before")
    ap.add_argument("--watchlist", action="store_true")
    args = ap.parse_args()
    conn = db.connect()
    db.init_db(conn)
    try:
        if args.watchlist:
            print(json.dumps({"watchlisted": add_watchlist(conn, [args.creator], source="manual", priority=100)}, ensure_ascii=False))
        else:
            print(json.dumps(scan_creator(conn, args.creator, args.max_pages, before=args.before), ensure_ascii=False))
    finally:
        conn.close()


if __name__ == "__main__":
    main()