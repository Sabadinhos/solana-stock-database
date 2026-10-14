import sqlite3
import unittest
from unittest.mock import patch

import launchpad_backfill


class BackfillTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")

    def tearDown(self):
        self.conn.close()

    def test_resumes_and_deduplicates(self):
        pages = [[
            {"signature": "sig-2", "slot": 2, "blockTime": 2, "err": None},
            {"signature": "sig-1", "slot": 1, "blockTime": 1, "err": None},
        ], []]
        def fake_rpc(url, method, params):
            if method == "getSignaturesForAddress":
                return pages.pop(0)
            return {"slot": 1, "transaction": {}}
        with patch.object(launchpad_backfill, "rpc", side_effect=fake_rpc):
            result = launchpad_backfill.scrape(self.conn, "https://rpc.test", "pump_fun", "Program111111111111111111111111111111111111", max_pages=2)
        self.assertEqual(result["inserted"], 2)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM launchpad_backfill_transactions").fetchone()[0], 2)

    def test_failed_page_rolls_back(self):
        def fake_rpc(url, method, params):
            if method == "getSignaturesForAddress":
                return [{"signature": "sig-1", "slot": 1, "err": None}]
            raise RuntimeError("boom")
        with patch.object(launchpad_backfill, "rpc", side_effect=fake_rpc):
            with self.assertRaises(RuntimeError):
                launchpad_backfill.scrape(self.conn, "https://rpc.test", "pump_fun", "Program111111111111111111111111111111111111")
        self.assertEqual(self.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='launchpad_backfill_transactions'").fetchone()[0], "launchpad_backfill_transactions")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM launchpad_backfill_transactions").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
