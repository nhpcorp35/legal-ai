"""Tests for the read-only cross-case retrieval regression contract."""

import unittest
from unittest import mock

from scripts.run_cross_case_retrieval_regression import evaluate_target
from scripts import run_verified_case_draft as worker


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

    def test_missing_competing_expert_record_fails(self):
        target = {
            "name": "synthetic_motion",
            "case_id": "NY-Nassau-613561-2026-Desousa-v-Rennick",
            "question": "My opponent made a motion. How should I answer it?",
            "minimum_authority_count": 0,
            "required_source_types": ("pleading",),
            "required_filename_suffixes": ("EXHIBIT_S__48.pdf",),
        }
        with self.assertRaisesRegex(AssertionError, "missing competing expert record"):
            evaluate_target(target, [PAGE], (), {})

    def test_motion_retrieval_reserves_competing_expert_rebuttal(self):
        source = "a" * 64
        pages = [
            {"filename": f"Filing_{number}.pdf", "page_number": 1,
             "text": "motion access waterfront measurement " * 25}
            for number in range(55)
        ] + [
            {"filename": "Initial_AFFIRMATION.pdf", "page_number": 1,
             "text": "Professional engineer opines on a 20 foot corridor."},
            {"filename": "Rebuttal_EXHIBIT_S__48.pdf", "page_number": 1,
             "text": "REBUTTAL TO THE AFFIRMATION OF AN ENGINEER. Expert opinion."},
            {"filename": "Rebuttal_EXHIBIT_S__48.pdf", "page_number": 2,
             "text": "I disagree with the method and assess navigation access."},
        ]
        with mock.patch.object(worker, "verified_sources", return_value=[source]), \
                mock.patch.object(worker, "verified_page_records", return_value=pages):
            for question in (
                "I need to make a motion. Which motions should I consider?",
                "My opponent made a motion. How should I answer it?",
            ):
                selected = worker.evidence(None, "synthetic-case", question)
                self.assertTrue(selected.coverage["competing_expert_rebuttal_selected"])
                self.assertTrue(any(page["filename"].endswith("EXHIBIT_S__48.pdf")
                                    for page in selected))
                self.assertLessEqual(len(selected), worker.MAX_PAGES)


if __name__ == "__main__":
    unittest.main()
