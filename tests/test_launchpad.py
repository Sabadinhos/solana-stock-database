import sqlite3
import unittest

import db
import launchpad_ingest
import launchpad_collect


class LaunchpadTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        db.init_db(self.conn)

    def tearDown(self):
        self.conn.close()

    def payload(self):
        return {
            "version": 1,
            "complete": True,
            "capturedAt": "2026-09-16T00:00:00Z",
            "events": [
                {"source": "pump_fun", "programId": "Pump111111111111111111111111111111111111111", "signature": "sig-a", "slot": 10, "blockTime": 1, "confirmationStatus": "confirmed"},
                {"source": "raydium_launchlab", "programId": "Rayd11111111111111111111111111111111111111", "signature": "sig-b", "slot": 11, "blockTime": 2, "confirmationStatus": "confirmed"},
            ],
        }

    def test_ingest_is_idempotent(self):
        first = launchpad_ingest.ingest(self.conn, self.payload())
        second = launchpad_ingest.ingest(self.conn, self.payload())
        self.assertEqual(first["newEvents"], 2)
        self.assertEqual(second["newEvents"], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM launchpad_events").fetchone()[0], 2)

    def test_duplicate_signatures_in_one_envelope_rejected(self):
        payload = self.payload()
        payload["events"].append(dict(payload["events"][0]))
        with self.assertRaises(ValueError):
            launchpad_ingest.ingest(self.conn, payload)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM launchpad_events").fetchone()[0], 0)

    def test_source_configuration(self):
        self.assertEqual(
            launchpad_collect.configured_sources({"SDB_LAUNCHPAD_PROGRAMS": "pump_fun=Pump111111111111111111111111111111111111111,raydium=Rayd11111111111111111111111111111111111111"}),
            [("pump_fun", "Pump111111111111111111111111111111111111111"), ("raydium", "Rayd11111111111111111111111111111111111111")],
        )

    def test_invalid_source_is_rejected(self):
        with self.assertRaises(ValueError):
            launchpad_collect.configured_sources({"SDB_LAUNCHPAD_PROGRAMS": "bad-source=not-a-program"})


if __name__ == "__main__":
    unittest.main()
