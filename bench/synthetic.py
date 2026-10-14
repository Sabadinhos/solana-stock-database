"""Synthetic credit benchmark for onchain.py.

Runs the legacy strategy (SDB_ONCHAIN_LEGACY=1) and the default incremental
strategy against the same simulated chain and reports RPC calls, credits and
detected events. No network access and no real data.

    python bench/synthetic.py --tokens 100 --runs 16 --seed 7
"""
import argparse
import importlib
import json
import os
import random
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["SDB_RPC_STATS"] = "0"
os.environ.setdefault("RPC_URL", "http://synthetic.invalid")


class Chain:
    def __init__(self, tokens, seed):
        self.rng = random.Random(seed)
        self.mints = [f"Mint{i:040d}"[:44] for i in range(tokens)]
        self.sigs = {m: [] for m in self.mints}  # newest first
        self.tx = {}
        self.n = 0

    def advance(self, mean_new):
        for m in self.mints:
            for _ in range(self.rng.randint(0, mean_new * 2)):
                self.n += 1
                sig = f"sig{self.n}"
                failed = self.rng.random() < 0.1
                kind = self.rng.choices(["transfer", "burn", "mint", "setAuthority"], [90, 6, 3, 1])[0]
                self.sigs[m].insert(0, {"signature": sig, "err": {"x": 1} if failed else None})
                ins = [] if kind == "transfer" else [{"parsed": {"type": kind, "info": {"amount": "1000"}}}]
                self.tx[sig] = {"transaction": {"message": {"instructions": ins}}, "meta": {"innerInstructions": []}}

    def handle(self, method, params):
        if method == "getTokenLargestAccounts":
            return {"value": [{"address": f"acct{i}", "uiAmountString": "10"} for i in range(20)]}
        if method == "getTokenSupply":
            return {"value": {"uiAmountString": "1000", "decimals": 6}}
        if method == "getAccountInfo":
            return {"value": {"owner": "Prog1111"}}
        if method == "getSignaturesForAddress":
            mint, opts = params
            rows = self.sigs[mint]
            start = 0
            if opts.get("before"):
                start = next(i for i, r in enumerate(rows) if r["signature"] == opts["before"]) + 1
            out = []
            for r in rows[start:]:
                if r["signature"] == opts.get("until"):
                    break
                out.append(r)
                if len(out) >= opts["limit"]:
                    break
            return out
        if method == "getTransaction":
            return self.tx[params[0]]
        raise ValueError(method)


def run(legacy, tokens, runs, mean_new, seed):
    os.environ["SDB_ONCHAIN_LEGACY"] = "1" if legacy else "0"
    import helius, onchain
    importlib.reload(helius)
    onchain = importlib.reload(onchain)
    chain = Chain(tokens, seed)

    def post(body):
        req = json.loads(body)
        return 200, {}, {"jsonrpc": "2.0", "id": 1, "result": chain.handle(req["method"], req["params"])}

    helius._post = post
    helius._throttle = lambda: None
    helius.reset()
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
      CREATE TABLE tokens (mint TEXT PRIMARY KEY, creator TEXT, pool TEXT, market_cap_usd REAL, holder_top10_share REAL);
      CREATE TABLE holders (mint TEXT, owner TEXT, amount_ui REAL, pct REAL, captured_at TEXT, PRIMARY KEY (mint, owner));
      CREATE TABLE token_events (mint TEXT, wallet TEXT, kind TEXT, signature TEXT, captured_at TEXT, UNIQUE (mint, kind, signature));
      CREATE TABLE pools (mint TEXT, pool TEXT, program TEXT, captured_at TEXT, PRIMARY KEY (mint, pool));
      CREATE TABLE burns (mint TEXT, signature TEXT PRIMARY KEY, amount_raw INTEGER, decimals INTEGER, amount_ui REAL, captured_at TEXT);
    """)
    for i, m in enumerate(chain.mints):
        conn.execute("INSERT INTO tokens VALUES (?,?,?,?,NULL)", (m, "creator", f"pool{i}", 1e6 + i))
    chain.advance(mean_new)
    for _ in range(runs):
        helius._cache.clear()  # each scheduled run is a separate process
        onchain.enrich(conn, top_n=tokens)
        chain.advance(mean_new)
    failed = {r["signature"] for rows in chain.sigs.values() for r in rows if r["err"]}
    stored = [r[0] for r in conn.execute("SELECT signature FROM token_events")]
    valid = sum(1 for s in stored if s not in failed)
    from_failed = len(stored) - valid
    snap = helius.snapshot()
    return {"strategy": "legacy" if legacy else "incremental", "rpcCalls": snap["total"]["calls"],
            "credits": snap["total"]["credits"], "cacheHits": snap["total"]["cacheHits"],
            "validEventsStored": valid, "eventsFromFailedTx": from_failed,
            "byMethod": {k: v["calls"] for k, v in snap["methods"].items()}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tokens", type=int, default=100)
    ap.add_argument("--runs", type=int, default=16)
    ap.add_argument("--mean-new", type=int, default=3, help="mean new signatures per token per run")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    legacy = run(True, a.tokens, a.runs, a.mean_new, a.seed)
    new = run(False, a.tokens, a.runs, a.mean_new, a.seed)
    out = {"params": vars(a), "legacy": legacy, "incremental": new,
           "creditReductionPct": round(100 * (1 - new["credits"] / legacy["credits"]), 1)}
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
