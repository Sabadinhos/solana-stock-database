"""Read-only Solana RPC client used by SDB collectors.

Reads RPC_URL from the environment and never logs it.

Features:
  - credit accounting per method, persisted to data/rpc-stats.json
  - per-method TTL cache and in-process deduplication of identical calls
  - retry with jitter, Retry-After support on 429, simple circuit breaker
  - global request throttle sized for the Helius free plan
"""
import atexit
import json
import os
import sys
import random
import tempfile
import threading
import time
import urllib.error
import urllib.request

TIMEOUT = 30
MAX_RETRIES = 5
RATE_QPS = float(os.environ.get("SDB_RPC_QPS", "8"))
BREAKER_FAILURES = 5
BREAKER_COOLDOWN = 60.0

# Credits per request, from helius.dev/docs/billing/credits.
CREDITS = {
    "getProgramAccounts": 10,
    "getAsset": 10,
    "getTokenAccounts": 10,
}
DEFAULT_CREDITS = 1

# Seconds a result stays valid inside one process. 0 means no cache.
TTL = {
    "getTokenSupply": 300,
    "getAccountInfo": 300,
    "getAsset": 86400,
}

STATS_FILE = os.path.join(
    os.environ.get("SDB_DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")),
    "rpc-stats.json")


class RpcError(RuntimeError):
    pass


class CircuitOpen(RpcError):
    pass


def rpc_url():
    return (os.environ.get("RPC_URL") or os.environ.get("SDB_RPC_URL") or "").strip()


_lock = threading.Lock()
_last = [0.0]
_cache = {}
_breaker = {"failures": 0, "open_until": 0.0}
STATS = {}


def _stat(method):
    return STATS.setdefault(method, {"calls": 0, "credits": 0, "errors": 0,
                                     "rateLimited": 0, "cacheHits": 0})


def reset():
    """Clear cache, breaker and counters. Used by tests and benchmarks."""
    _cache.clear()
    STATS.clear()
    _breaker.update(failures=0, open_until=0.0)


def _throttle():
    with _lock:
        gap = 1.0 / RATE_QPS
        wait = _last[0] + gap - time.time()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()


def _backoff(attempt, retry_after=None):
    if retry_after is not None:
        try:
            return min(float(retry_after), 30.0)
        except ValueError:
            pass
    return min(2 ** attempt, 15) * (0.5 + random.random())


def _post(body):
    """Send one JSON-RPC body. Returns (status, headers, parsed_json). Tests replace this."""
    req = urllib.request.Request(rpc_url(), data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, dict(r.headers), json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), None


def _sleep(seconds):
    time.sleep(seconds)


def _rpc(method, params):
    key = None
    ttl = TTL.get(method, 0)
    if ttl:
        key = (method, json.dumps(params, sort_keys=True))
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            _stat(method)["cacheHits"] += 1
            return hit[1]
    if not rpc_url():
        raise RpcError("RPC_URL is not configured")
    if time.time() < _breaker["open_until"]:
        raise CircuitOpen(f"RPC circuit open, skipping {method}")
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    st = _stat(method)
    last_error = None
    for attempt in range(MAX_RETRIES):
        _throttle()
        st["calls"] += 1
        try:
            status, headers, data = _post(body)
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            last_error = exc
            _sleep(_backoff(attempt))
            continue
        if status == 429:
            st["rateLimited"] += 1
            _sleep(_backoff(attempt, headers.get("Retry-After") or headers.get("retry-after")))
            continue
        if status >= 500:
            last_error = RpcError(f"HTTP {status}")
            _sleep(_backoff(attempt))
            continue
        if status != 200 or data is None:
            st["errors"] += 1
            raise RpcError(f"{method}: HTTP {status}")
        st["credits"] += CREDITS.get(method, DEFAULT_CREDITS)
        _breaker["failures"] = 0
        if "error" in data:
            st["errors"] += 1
            raise RpcError(f"{method}: {data['error']}")
        result = data.get("result")
        if key:
            _cache[key] = (time.time(), result)
        return result
    st["errors"] += 1
    _breaker["failures"] += 1
    if _breaker["failures"] >= BREAKER_FAILURES:
        _breaker["open_until"] = time.time() + BREAKER_COOLDOWN
    raise RpcError(f"{method} failed after {MAX_RETRIES} attempts: {last_error}")


def record_external(method, calls, credits_each=None):
    """Account for RPC calls made outside this module, such as the Node DBC collector."""
    st = _stat(method)
    st["calls"] += int(calls)
    st["credits"] += int(calls) * (credits_each if credits_each is not None
                                   else CREDITS.get(method, DEFAULT_CREDITS))


def snapshot():
    total = {"calls": 0, "credits": 0, "errors": 0, "rateLimited": 0, "cacheHits": 0}
    for st in STATS.values():
        for k in total:
            total[k] += st[k]
    return {"methods": {k: dict(v) for k, v in sorted(STATS.items())}, "total": total}


def flush(label=None, path=None):
    """Merge this process's counters into the daily totals file. Never stores the RPC URL."""
    path = path or STATS_FILE
    if not STATS:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        doc = {"version": 1, "days": {}, "runs": []}
    day = time.strftime("%Y-%m-%d", time.gmtime())
    bucket = doc.setdefault("days", {}).setdefault(day, {})
    for method, st in STATS.items():
        agg = bucket.setdefault(method, {"calls": 0, "credits": 0, "errors": 0,
                                         "rateLimited": 0, "cacheHits": 0})
        for k in agg:
            agg[k] += st.get(k, 0)
    run = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "label": label or os.path.basename(sys.argv[0] or "python")}
    run.update(snapshot()["total"])
    doc.setdefault("runs", []).append(run)
    doc["runs"] = doc["runs"][-200:]
    for old in sorted(doc["days"])[:-60]:
        del doc["days"][old]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".rpc-stats-", dir=os.path.dirname(path))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(doc, f)
    os.replace(tmp, path)
    STATS.clear()
    return run


atexit.register(lambda: flush() if os.environ.get("SDB_RPC_STATS", "1") != "0" else None)


# ---- token / holders ----
def get_token_largest_accounts(mint):
    """Top 20 token accounts of a mint."""
    return _rpc("getTokenLargestAccounts", [mint])


def get_token_supply(mint):
    return _rpc("getTokenSupply", [mint])


def get_asset(mint):
    """Helius DAS metadata for a token mint."""
    return _rpc("getAsset", {"id": mint})


def get_token_accounts_by_owner(owner, mint=None):
    cfg = {"mint": mint} if mint else {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"}
    return _rpc("getTokenAccountsByOwner", [owner, cfg, {"encoding": "jsonParsed"}])


# ---- accounts ----
def get_account_info(pubkey, encoding="jsonParsed"):
    return _rpc("getAccountInfo", [pubkey, {"encoding": encoding}])


def get_token_account_balance(pubkey):
    return _rpc("getTokenAccountBalance", [pubkey])


def get_balance(pubkey):
    return _rpc("getBalance", [pubkey])


# ---- transactions ----
def get_signatures_for_address(addr, limit=100, before=None, until=None):
    opts = {"limit": limit}
    if before:
        opts["before"] = before
    if until:
        opts["until"] = until
    return _rpc("getSignaturesForAddress", [addr, opts])


def get_transaction(sig, encoding="jsonParsed", max_version=0):
    return _rpc("getTransaction", [sig, {
        "encoding": encoding,
        "maxSupportedTransactionVersion": max_version,
        "commitment": "confirmed",
    }])
