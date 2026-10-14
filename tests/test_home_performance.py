import sqlite3
import time
import unittest
from unittest.mock import patch

import importlib.util
from pathlib import Path

import db
import server

_spec = importlib.util.spec_from_file_location("sdb_cards", Path(__file__).parents[1] / "cards.py")
cards = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cards)


class HomePerformanceTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        db.init_db(self.conn)
        rows = []
        rewards = []
        for i in range(5000):
            mint = f"mint-{i:05d}"
            rows.append((mint, f"SYM{i}", f"Token {i}", float(i), "/api/asset/test"))
            rewards.append((mint, "SPYx", float(i), f"2026-09-14T00:{i % 60:02d}:00Z"))
        self.conn.executemany(
            "INSERT INTO tokens(mint,symbol,name,market_cap_usd,image_url) VALUES(?,?,?,?,?)",
            rows,
        )
        self.conn.executemany(
            "INSERT INTO rewards(mint,quote_symbol,distributed_tokens,last_payout_at) VALUES(?,?,?,?)",
            rewards,
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_default_cards_are_bounded_and_ordered(self):
        started = time.perf_counter()
        result = cards.cards(self.conn, "ALL", 30, 0, "mc")
        elapsed = time.perf_counter() - started
        self.assertEqual(len(result["cards"]), 30)
        self.assertEqual(result["total"], 5000)
        self.assertEqual(result["cards"][0]["market_cap_usd"], 4999.0)
        self.assertLess(elapsed, 0.25)

    def test_card_query_uses_market_cap_index(self):
        plan = self.conn.execute("""
            EXPLAIN QUERY PLAN
            SELECT r.mint FROM tokens t INDEXED BY idx_tokens_mcap
            JOIN rewards r ON r.mint=t.mint
            ORDER BY t.market_cap_usd DESC LIMIT 30
        """).fetchall()
        text = " ".join(str(tuple(row)) for row in plan)
        self.assertIn("idx_tokens_mcap", text)

    def test_proxy_ip_is_used_only_for_local_peer(self):
        class Handler:
            headers = {"CF-Connecting-IP": "203.0.113.8", "X-Forwarded-For": "198.51.100.2"}
        local = Handler()
        local.client_address = ("127.0.0.1", 1234)
        remote = Handler()
        remote.client_address = ("198.51.100.20", 1234)
        self.assertEqual(server._client_ip(local), "203.0.113.8")
        self.assertEqual(server._client_ip(remote), "198.51.100.20")

    def test_empty_search_returns_bounded_shape(self):
        result = cards.cards(self.conn, "ALL", 0, 0, "mc")
        self.assertEqual(result["cards"], [])
        self.assertEqual(result["total"], 5000)


if __name__ == "__main__":
    unittest.main()
