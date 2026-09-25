"""Tests for the no-cost pre-generation verified-input gate."""

import unittest

from scripts.run_verified_case_draft import PreGenerationGateError, pre_generation_checks


SHA = "a" * 64
PAGE = {
    "source_sha256": SHA,
    "filename": "Verified Complaint.pdf",
    "page_number": 1,
    "text": "Verified pleading text.",
}


class PreGenerationGateTests(unittest.TestCase):
    def test_valid_input_reports_verified_integrity_without_model(self):
        result = pre_generation_checks(
            [PAGE],
            (),
            "Identify claims and relief in the main action.",
            {
                "verified_pleading_inventory": [{"source_sha256": SHA, "filename": PAGE["filename"]}],
                "pleading_operatives": {"claim_page_count": 1, "relief_page_count": 1},
            },
        )

        self.assertEqual(result["status"], "PASSED")
        self.assertFalse(result["model_called"])
        self.assertFalse(result["b2_write"])
        self.assertEqual(result["duplicate_selected_citation_count"], 0)

    def test_duplicate_selected_citation_fails_before_model(self):
        with self.assertRaisesRegex(PreGenerationGateError, "duplicate_selected_citation"):
            pre_generation_checks([PAGE, dict(PAGE)], (), "General record question.", {})

    def test_claim_request_without_claim_coverage_fails_closed(self):
        with self.assertRaisesRegex(PreGenerationGateError, "missing_claim_coverage"):
            pre_generation_checks(
                [PAGE],
                (),
                "Identify claims and relief in the main action.",
                {
                    "verified_pleading_inventory": [
                        {"source_sha256": SHA, "filename": PAGE["filename"]}
                    ],
                    "pleading_operatives": {"claim_page_count": 0, "relief_page_count": 1},
                },
            )


if __name__ == "__main__":
    unittest.main()
