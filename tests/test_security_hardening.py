import unittest
from unittest.mock import patch

import launchpad_backfill


class RpcSecurityTests(unittest.TestCase):
    def test_rpc_bounds_and_input_validation(self):
        with self.assertRaises(ValueError):
            launchpad_backfill.validate_rpc_url("file:///tmp/x")
        with self.assertRaises(ValueError):
            launchpad_backfill.validate_program_id("bad")
        with self.assertRaises(ValueError):
            launchpad_backfill.validate_source("bad-source")


if __name__ == "__main__":
    unittest.main()
