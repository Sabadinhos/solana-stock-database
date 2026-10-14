"""Bounded process wrapper for the isolated Meteora DBC Node collector."""
import json
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
COLLECTOR = os.path.join(HERE, "collectors", "meteora-dbc", "collector.js")
DEFAULT_TIMEOUT = 660
DEFAULT_MAX_OUTPUT = 32 * 1024 * 1024

class CollectionError(RuntimeError):
    pass

def collect(rpc_url=None, timeout=DEFAULT_TIMEOUT, max_output=DEFAULT_MAX_OUTPUT, env=None):
    if not isinstance(timeout, (int, float)) or timeout <= 0 or timeout > DEFAULT_TIMEOUT:
        raise ValueError("timeout out of bounds")
    if not isinstance(max_output, int) or max_output < 1024 or max_output > DEFAULT_MAX_OUTPUT:
        raise ValueError("max_output out of bounds")
    child_env = os.environ.copy()
    if env:
        child_env.update(env)
    if rpc_url:
        child_env["DBC_RPC_URL"] = rpc_url
    try:
        proc = subprocess.Popen(["node", COLLECTOR], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=child_env)
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise CollectionError("collector timed out")
    if len(out) > max_output:
        raise CollectionError("collector output exceeded limit")
    if proc.returncode:
        raise CollectionError((err[:4096].decode("utf-8", "replace") or "collector failed").strip())
    try:
        return json.loads(out.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CollectionError("collector returned invalid JSON") from exc

def main():
    from dbc_ingest import ingest
    import db
    # DBC uses the same read-only Solana RPC by default. Keep an explicit
    # override for a dedicated provider, but never launch the collector with
    # an empty URL because that fails only after the scheduler reaches DBC.
    rpc_url = os.environ.get("DBC_RPC_URL") or os.environ.get("RPC_URL")
    if not rpc_url or not rpc_url.startswith(("http://", "https://")):
        raise CollectionError("DBC_RPC_URL or RPC_URL must be an http(s) URL")
    payload = collect(rpc_url=rpc_url)
    conn = db.connect()
    try:
        run_id = ingest(conn, payload)
        import helius
        method = payload.get("rpcMethod", "getProgramAccounts")
        requests = int(payload.get("stats", {}).get("rpcRequests", 0))
        if requests:
            helius.record_external("getSlot", 1)
            helius.record_external(method, requests - 1)
            helius.flush("dbc")
        print(json.dumps({"ok": True, "runId": run_id, "stats": payload["stats"]}))
    finally:
        conn.close()

if __name__ == "__main__":
    main()
