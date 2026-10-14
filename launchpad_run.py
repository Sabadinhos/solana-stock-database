"""Collect configured launchpad activity and persist it into the local SDB database.

This runner records program activity only. Token-level launch detection requires a
protocol decoder and is intentionally a separate step.
"""
import argparse
import json
import os

import db
import launchpad_collect
import launchpad_ingest


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--rpc-url", default=None)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--before", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    rpc_url = args.rpc_url or os.environ.get("RPC_URL") or os.environ.get("SDB_RPC_URL")
    if not rpc_url:
        parser.error("RPC_URL or SDB_RPC_URL is required")
    payload = launchpad_collect.collect_all(rpc_url, limit=args.limit, before=args.before)
    if args.dry_run:
        print(json.dumps({"ok": True, "dryRun": True, "events": len(payload["events"])}))
        return 0
    conn = db.connect()
    try:
        result = launchpad_ingest.ingest(conn, payload)
    finally:
        conn.close()
    print(json.dumps({"ok": True, "collection": {"events": len(payload["events"])}, "ingest": result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
