"""Tests for the read-only cross-case retrieval regression contract."""

import unittest

from scripts.run_cross_case_retrieval_regression import evaluate_target


SHA = "b" * 64
PAGE = {
    "source_sha256": SHA,
    "filename": "Verified pleading.pdf",
    "page_number": 1,
    "text": "Verified complaint, affirmative defense, and requested relief.",
}


class CrossCaseRetrievalRegressionTests(unittest.TestCase):
    def test_target_reports_no_model_preflight(self):
        target = {
            "name": "synthetic_main_action",
            "case_id": "NY-NewYork-158068-2018-Szymczyk-v-Hudson-36-37",
            "question": "Identify claims and relief in the main action.",
            "minimum_authority_count": 0,
            "required_source_types": ("pleading",),
        }

        result = evaluate_target(
            target,
            [PAGE],
            (),
            {
                "verified_pleading_inventory": [
                    {"source_sha256": SHA, "filename": PAGE["filename"]}
                ],
                "pleading_operatives": {
                    "claim_page_count": 1,
                    "relief_page_count": 1,
                },
            },
        )

        self.assertEqual(result["selected_page_count"], 1)
        self.assertFalse(result["pre_generation_check"]["model_called"])

    def test_missing_required_source_type_fails(self):
        target = {
            "name": "synthetic_motion",
            "case_id": "NY-Nassau-613561-2026-Desousa-v-Rennick",
            "question": "I need to make a motion. Which motions should I consider?",
            "minimum_authority_count": 0,
            "required_source_types": ("regulatory_record",),
        }

        with self.assertRaisesRegex(AssertionError, "missing required source types"):
            evaluate_target(target, [PAGE], (), {})


if __name__ == "__main__":
    unittest.main()
