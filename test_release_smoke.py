"""Deterministic import smoke checks for production releases."""

import importlib
import unittest


class ReleaseSmokeTests(unittest.TestCase):
    def test_web_and_verified_draft_modules_import(self):
        app = importlib.import_module("app")
        worker = importlib.import_module("scripts.run_verified_case_draft")
        self.assertTrue(callable(app.app))
        self.assertTrue(callable(worker.load_reviewed_authorities))
        self.assertEqual(app.app.name, "app")


if __name__ == "__main__":
    unittest.main()
