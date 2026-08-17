"""Focused regression for bounded party-role evidence packet coverage."""

import unittest

from engines import drafting_engine as de


class PartyRolePacketCoverageRegressionTests(unittest.TestCase):
    def test_budget_reserves_role_bearing_passages_before_identity_repetition(self):
        def hit(page, text, score, *, doc_type="complaint"):
            return {
                "result_id": f"coverage-{page}-{doc_type}",
                "page_id": f"nyscef-990-page-{page:04d}-{doc_type}",
                "nyscef_document_number": 990 if doc_type == "complaint" else 991,
                "pdf_page": page,
                "source_filename": f"coverage_{doc_type}.pdf",
                "document_type": doc_type,
                "excerpt": text,
                "page_text": text,
                "classifications": ["party_identity"],
                "assertion_kind": "verified_record_fact",
                "score": score,
            }

        hits = [
            hit(1, "Alpha LLC, Plaintiff, -against- Beta Inc., Defendant.", 30.0),
            hit(2, "PARTIES\nPlaintiff Alpha LLC. Defendant Beta Inc.", 29.0),
        ]
        hits.extend(
            hit(
                page,
                f"Answer repeats Plaintiff Alpha LLC and Defendant Beta Inc. page {page}.",
                25.0 - page,
                doc_type="answer",
            )
            for page in range(1, 7)
        )
        hits.extend(
            [
                hit(
                    8,
                    "Defendant Beta Inc. served as the contractor and insurance broker.",
                    1.0,
                ),
                hit(
                    9,
                    "In the related action, Defendant Beta Inc. was the plaintiff.",
                    0.5,
                ),
            ]
        )

        selected, meta = de.apply_party_role_packet_budget(
            hits, max_hits=4, max_chars=24000
        )
        excerpts = [item["excerpt"] for item in selected]
        self.assertEqual(len(selected), 4)
        self.assertTrue(any("insurance broker" in value for value in excerpts))
        self.assertTrue(any("related action" in value for value in excerpts))
        self.assertEqual(meta["role_coverage_hit_count"], 2)


if __name__ == "__main__":
    unittest.main()
