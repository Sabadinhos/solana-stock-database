"""Bounded, read-only Solana activity collector for configured launchpads.

This first layer intentionally collects program activity and evidence, not guessed token
launches. Protocol-specific decoders can consume the persisted signatures later.
"""
import json
import os
import re
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from urllib.parse import urlparse

DEFAULT_LIMIT = 100
MAX_LIMIT = 1000
DEFAULT_TIMEOUT = 20
MAX_RPC_BYTES = 16 * 1024 * 1024
PROGRAM_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


def validate_rpc_url(url):
    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("rpc URL must use http(s)")
    return url


def validate_program_id(program_id):
    if not isinstance(program_id, str) or not PROGRAM_RE.fullmatch(program_id):
        raise ValueError("invalid Solana program ID")
    return program_id


def validate_source(source):
    if not isinstance(source, str) or not re.fullmatch(r"[a-z0-9_]{2,40}", source):
        raise ValueError("invalid source slug")
    return source


def _read_limited(response):
    length = response.headers.get("Content-Length")
    if length and int(length) > MAX_RPC_BYTES:
        raise CollectionError("RPC response too large")
    data = response.read(MAX_RPC_BYTES + 1)
    if len(data) > MAX_RPC_BYTES:
        raise CollectionError("RPC response too large")
    return data


def _json_depth(value, depth=0):
    if depth > 80:
        raise CollectionError("RPC JSON nesting too deep")
    if isinstance(value, dict):
        for item in value.values(): _json_depth(item, depth + 1)
    elif isinstance(value, list):
        for item in value: _json_depth(item, depth + 1)
    return value


def _rpc(url, method, params, timeout=DEFAULT_TIMEOUT):
    validate_rpc_url(url)
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(url, body, {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = _json_depth(json.loads(_read_limited(response).decode()))
    except (OSError, ValueError) as exc:
        raise CollectionError(f"RPC {method} failed: {exc}") from exc
    if data.get("error"):
        raise CollectionError(f"RPC {method} failed: {data['error']}")
    return data.get("result")



class CollectionError(RuntimeError):
    pass


def configured_sources(environ=None):
    env = environ or os.environ
    raw = env.get("SDB_LAUNCHPAD_PROGRAMS", "")
    sources = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise ValueError("SDB_LAUNCHPAD_PROGRAMS must use slug=programId pairs")
        slug, program = (x.strip() for x in item.split("=", 1))
        validate_source(slug)
        validate_program_id(program)
        sources.append((slug, program))
    return sources


def collect_program(url, slug, program_id, limit=DEFAULT_LIMIT, before=None, timeout=DEFAULT_TIMEOUT):
    validate_source(slug)
    validate_program_id(program_id)
    if not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise ValueError("limit must be between 1 and 1000")
    params = [program_id, {"limit": limit, "commitment": "confirmed"}]
    if before:
        params[1]["before"] = before
    rows = _rpc(url, "getSignaturesForAddress", params, timeout)
    if not isinstance(rows, list):
        raise CollectionError("RPC returned an invalid signature list")
    captured = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return [{
        "source": slug,
        "programId": program_id,
        "signature": row.get("signature"),
        "slot": row.get("slot"),
        "blockTime": row.get("blockTime"),
        "err": row.get("err"),
        "confirmationStatus": row.get("confirmationStatus"),
        "capturedAt": captured,
    } for row in rows if isinstance(row, dict) and row.get("signature")]


def collect_all(url, sources=None, limit=DEFAULT_LIMIT, before=None, sleep_seconds=0.1):
    sources = configured_sources() if sources is None else sources
    events = []
    for index, (slug, program_id) in enumerate(sources):
        if index and sleep_seconds:
            time.sleep(sleep_seconds)
        events.extend(collect_program(url, slug, program_id, limit, before))
    return {"version": 1, "complete": True, "capturedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "events": events}


def main():
    url = os.environ.get("RPC_URL") or os.environ.get("SDB_RPC_URL")
    if not url:
        raise SystemExit("RPC_URL or SDB_RPC_URL is required")
    print(json.dumps(collect_all(url), ensure_ascii=False))

if __name__ == "__main__":
    main()
