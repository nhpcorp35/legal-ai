"""Archived-answer correction stays visible without changing the saved draft."""

import unittest
from unittest.mock import patch

import app as legalai


class ThirdActionCorrectionTests(unittest.TestCase):
    def test_correction_links_verified_answer_and_preserves_archived_statement(self):
        case_id = legalai.SZYMCZYK_PAGE17_CASE_ID
        request_id = "draft-1234567890-abcdef123456"
        statement = (
            "Third action—Owner against Quality Services; defenses: —; "
            "unresolved: No corresponding answer was identified."
        )
        item = {
            "request_id": request_id, "status": "READY",
            "question": "Map the four third-party actions.",
            "draft": {
                "summary": "Four actions mapped for review.",
                "findings": [{
                    "section": "Third-party claims", "statement": statement,
                    "citations": [], "authority_citations": [],
                }],
                "missing_information": [],
            },
        }
        with patch.object(legalai, "basic_review_user", return_value="reviewer"), patch.object(
            legalai, "load_exact_draft_request", return_value=item,
        ):
            response = legalai.app.test_client().get(
                f"/workspace/matters/{case_id}/drafts/{request_id}"
            )
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertEqual(page.count("Verified record correction to this archived draft."), 1)
        self.assertIn("ANSWER_WITH_CROSS_C_81.pdf", page)
        self.assertIn("#page=7", page)
        self.assertIn(statement, page)
        self.assertEqual(item["draft"]["findings"][0]["statement"], statement)

    def test_unaffected_answer_has_no_correction(self):
        self.assertFalse(legalai.szymczyk_third_action_correction_html(
            legalai.SZYMCZYK_PAGE17_CASE_ID,
            {"findings": [{"section": "Third-party claims", "statement": "Answer identified."}]},
        ))


if __name__ == "__main__":
    unittest.main()
