"""Tests for truthful bounded-retrieval audit visibility."""

import unittest

from app import build_retrieval_visibility


class RetrievalAuditVisibilityTests(unittest.TestCase):
    def test_distinguishes_present_but_not_selected_pleading(self):
        citations = [
            {
                "source_sha256": "a" * 64,
                "filename": "Complaint.pdf",
                "page_number": 1,
            }
        ]
        coverage = {
            "verified_pleading_inventory": [
                {
                    "source_sha256": "a" * 64,
                    "filename": "Complaint.pdf",
                    "filing_kind": "complaint",
                    "page_count": 8,
                },
                {
                    "source_sha256": "a" * 64,
                    "filename": "Answer.pdf",
                    "filing_kind": "answer",
                    "page_count": 6,
                },
            ]
        }

        visibility = build_retrieval_visibility(citations, coverage)

        self.assertTrue(visibility["verified_pleading_inventory_available"])
        self.assertEqual(visibility["selected_document_count"], 1)
        self.assertEqual(visibility["verified_pleadings_not_selected_count"], 1)
        self.assertEqual(
            visibility["verified_pleadings_not_selected"][0]["filename"],
            "Answer.pdf",
        )

    def test_selected_pages_alone_never_prove_absence(self):
        visibility = build_retrieval_visibility(
            [{"source_sha256": "b" * 64, "filename": "Order.pdf", "page_number": 1}],
            {},
        )

        self.assertFalse(visibility["verified_pleading_inventory_available"])
        self.assertIn("cannot establish", visibility["absence_boundary"])
        self.assertEqual(visibility["verified_pleadings_not_selected_count"], 0)


if __name__ == "__main__":
    unittest.main()
