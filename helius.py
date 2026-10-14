"""SDB – cliente Helius RPC (somente leitura, métodos nativos Solana).

Uses RPC_URL from the environment. Never logs the key.

"""
import json
import os
import threading
import time
import urllib.error
import urllib.request

TIMEOUT = 30
MAX_RETRIES = 5
RATE_QPS = 8  # folga sob o free tier de 10 req/s


def rpc_url():
    return (os.environ.get("RPC_URL") or os.environ.get("SDB_RPC_URL") or "").strip()

_lock = threading.Lock()
_last = [0.0]


def _throttle():
    with _lock:
        gap = 1.0 / RATE_QPS
        wait = _last[0] + gap - time.time()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()


def _rpc(method, params):
    url = rpc_url()
    if not url:
        raise RuntimeError("RPC_URL is not configured")
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                       "params": params}).encode()
    for attempt in range(MAX_RETRIES):
        _throttle()
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                d = json.loads(r.read())
            if "error" in d:
                raise RuntimeError(f"Helius {method}: {d['error']}")
            return d.get("result")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(min(2 ** attempt + 1, 15))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(min(2 ** attempt + 1, 15))
    raise RuntimeError(f"Helius {method} falhou após {MAX_RETRIES} tentativas")


# ---- token / holders ----
def get_token_largest_accounts(mint):
    """20 maiores contas de um mint (native getTokenLargestAccounts)."""
    return _rpc("getTokenLargestAccounts", [mint])


def get_token_supply(mint):
    return _rpc("getTokenSupply", [mint])


def get_asset(mint):
    """Helius DAS metadata for a token mint, read-only."""
    return _rpc("getAsset", [mint])


def get_token_accounts_by_owner(owner, mint=None):
    """Contas token de uma carteira (opcional: filtradas por mint)."""
    cfg = {"encoding": "jsonParsed"}
    if mint:
        cfg["mint"] = mint
    return _rpc("getTokenAccountsByOwner", [owner, cfg, {"encoding": "jsonParsed"}])


# ---- contas / saldos ----
def get_account_info(pubkey, encoding="jsonParsed"):
    return _rpc("getAccountInfo", [pubkey, {"encoding": encoding}])


def get_token_account_balance(pubkey):
    return _rpc("getTokenAccountBalance", [pubkey])


def get_balance(pubkey):
    return _rpc("getBalance", [pubkey])


# ---- transações ----
def get_signatures_for_address(addr, limit=100, before=None):
    params = [addr, {"limit": limit}]
    if before:
        params[1]["before"] = before
    return _rpc("getSignaturesForAddress", params)


def get_transaction(sig, encoding="jsonParsed", max_version=0):
    return _rpc("getTransaction", [sig, {
        "encoding": encoding,
        "maxSupportedTransactionVersion": max_version,
        "commitment": "confirmed",
    }])
