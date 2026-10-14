import json
import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["SDB_RPC_STATS"] = "0"
os.environ.setdefault("RPC_URL", "http://unit.invalid")
import helius  # noqa: E402


class Fake:
    def __init__(self, responses):
        self.responses = list(responses)
        self.bodies = []

    def __call__(self, body):
        self.bodies.append(json.loads(body))
        return self.responses.pop(0)


class RpcClientTest(unittest.TestCase):
    def setUp(self):
        helius.reset()
        self.sleeps = []
        helius._sleep = self.sleeps.append
        helius._throttle = lambda: None

    def test_retry_after_is_respected_and_counted(self):
        helius._post = Fake([(429, {"Retry-After": "3"}, None),
                             (200, {}, {"result": {"value": 1}})])
        self.assertEqual(helius.get_balance("A"), {"value": 1})
        self.assertEqual(self.sleeps, [3.0])
        st = helius.snapshot()["methods"]["getBalance"]
        self.assertEqual((st["calls"], st["rateLimited"], st["credits"]), (2, 1, 1))

    def test_ttl_cache_dedupes_supply(self):
        fake = Fake([(200, {}, {"result": {"value": {"decimals": 6}}})])
        helius._post = fake
        helius.get_token_supply("M")
        helius.get_token_supply("M")
        self.assertEqual(len(fake.bodies), 1)
        self.assertEqual(helius.snapshot()["methods"]["getTokenSupply"]["cacheHits"], 1)

    def test_credit_prices(self):
        helius._post = Fake([(200, {}, {"result": {}})])
        helius.get_asset("M")
        self.assertEqual(helius.snapshot()["methods"]["getAsset"]["credits"], 10)

    def test_circuit_breaker_opens(self):
        helius._post = Fake([(503, {}, None)] * helius.MAX_RETRIES * helius.BREAKER_FAILURES)
        for _ in range(helius.BREAKER_FAILURES):
            with self.assertRaises(helius.RpcError):
                helius.get_balance("A")
        with self.assertRaises(helius.CircuitOpen):
            helius.get_balance("A")

    def test_flush_writes_aggregates_without_url(self):
        import tempfile
        helius._post = Fake([(200, {}, {"result": 1})])
        helius.get_balance("A")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "rpc-stats.json")
            helius.flush("unit", path)
            text = open(path, encoding="utf-8").read()
        self.assertIn("getBalance", text)
        self.assertNotIn("unit.invalid", text)


class IncrementalOnchainTest(unittest.TestCase):
    def test_second_run_only_fetches_new_transactions(self):
        import importlib
        os.environ["SDB_ONCHAIN_LEGACY"] = "0"
        import onchain
        onchain = importlib.reload(onchain)
        helius.reset()
        helius._throttle = lambda: None
        sigs = [{"signature": "s2", "err": None}, {"signature": "s1", "err": {"e": 1}}]
        calls = []

        def post(body):
            req = json.loads(body)
            calls.append(req["method"])
            m, p = req["method"], req["params"]
            if m == "getSignaturesForAddress":
                until = p[1].get("until")
                out = []
                for s in sigs:
                    if s["signature"] == until:
                        break
                    out.append(s)
                return 200, {}, {"result": out}
            if m == "getTransaction":
                return 200, {}, {"result": {"transaction": {"message": {"instructions": []}},
                                            "meta": {"innerInstructions": [{"instructions": [
                                                {"parsed": {"type": "burn", "info": {"amount": "5"}}}]}]}}}
            if m == "getTokenSupply":
                return 200, {}, {"result": {"value": {"uiAmountString": "100", "decimals": 0}}}
            if m == "getTokenLargestAccounts":
                return 200, {}, {"result": {"value": []}}
            return 200, {}, {"result": {"value": {"owner": "P"}}}

        helius._post = post
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
          CREATE TABLE tokens (mint TEXT PRIMARY KEY, creator TEXT, pool TEXT, market_cap_usd REAL, holder_top10_share REAL);
          CREATE TABLE holders (mint TEXT, owner TEXT, amount_ui REAL, pct REAL, captured_at TEXT, PRIMARY KEY (mint, owner));
          CREATE TABLE token_events (mint TEXT, wallet TEXT, kind TEXT, signature TEXT, captured_at TEXT, UNIQUE (mint, kind, signature));
          CREATE TABLE pools (mint TEXT, pool TEXT, program TEXT, captured_at TEXT, PRIMARY KEY (mint, pool));
          CREATE TABLE burns (mint TEXT, signature TEXT PRIMARY KEY, amount_raw INTEGER, decimals INTEGER, amount_ui REAL, captured_at TEXT);
          INSERT INTO tokens VALUES ('M', 'C', 'P1', 2000000, NULL);
        """)
        onchain.enrich(conn, top_n=1)
        self.assertEqual(calls.count("getTransaction"), 1)  # failed tx skipped
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM burns").fetchone()[0], 1)
        calls.clear()
        onchain.enrich(conn, top_n=1)
        self.assertEqual(calls.count("getTransaction"), 0)
        self.assertEqual(calls.count("getAccountInfo"), 0)  # pool still fresh


if __name__ == "__main__":
    unittest.main()
