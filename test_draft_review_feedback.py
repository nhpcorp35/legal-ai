import base64
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import app as legalai


CASE_ID = "Case-00-Triborough"
REQUEST_ID = "draft-1789581938-543896260b2f"


def auth_headers():
    token = base64.b64encode(b"johncuomo@gmail.com:secret").decode("ascii")
    return {"Authorization": f"Basic {token}"}


def ready_item():
    return {
        "request_id": REQUEST_ID,
        "question": "Review the verified record.",
        "requested_by": "allen@nhpcorp.com",
        "status": "READY",
        "draft": {"summary": "Summary.", "findings": [], "missing_information": []},
    }


class DraftReviewFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(
            os.environ,
            {
                "LEGALAI_REVIEW_JOHN_USERNAME": "johncuomo@gmail.com",
                "LEGALAI_REVIEW_JOHN_PASSWORD": "secret",
                "LEGALAI_REVIEW_GATEWAY_SECRET": "gateway-secret",
                "LEGALAI_DRAFT_REVIEW_FEEDBACK_DIR": self.temp.name,
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client = legalai.app.test_client()

    def test_get_shows_structured_review_form(self):
        with patch.object(legalai, "load_exact_draft_request", return_value=ready_item()):
            response = self.client.get(
                f"/workspace/case-00/drafts/{REQUEST_ID}", headers=auth_headers()
            )
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('id="attorney-review"', body)
        self.assertIn('name="decision" value="approve"', body)
        self.assertIn('name="accuracy_rating"', body)
        self.assertIn('name="feedback_csrf_token"', body)

    def test_valid_review_is_archived_and_redirected(self):
        token = legalai.draft_review_feedback_csrf_token(
            "johncuomo@gmail.com", CASE_ID, REQUEST_ID
        )
        with patch.object(legalai, "load_exact_draft_request", return_value=ready_item()):
            response = self.client.post(
                f"/workspace/case-00/drafts/{REQUEST_ID}",
                headers=auth_headers(),
                data={
                    "feedback_csrf_token": token,
                    "decision": "needs_revision",
                    "accuracy_rating": "4",
                    "usefulness_rating": "5",
                    "missing_or_overstated": "Missing chronology.",
                    "citation_problems": "None.",
                    "comments": "Useful draft.",
                },
            )
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["Location"].endswith("?review=saved"))
        path = os.path.join(self.temp.name, "draft_feedback.jsonl")
        with open(path, encoding="utf-8") as stream:
            saved = json.loads(stream.readline())
        self.assertEqual(saved["reviewer"], "johncuomo@gmail.com")
        self.assertEqual(saved["request_id"], REQUEST_ID)
        self.assertEqual(saved["decision"], "needs_revision")
        self.assertEqual(saved["accuracy_rating"], 4)

    def test_tampered_token_is_rejected_without_write(self):
        with patch.object(legalai, "load_exact_draft_request", return_value=ready_item()):
            response = self.client.post(
                f"/workspace/case-00/drafts/{REQUEST_ID}",
                headers=auth_headers(),
                data={
                    "feedback_csrf_token": "tampered",
                    "decision": "approve",
                    "accuracy_rating": "5",
                    "usefulness_rating": "5",
                },
            )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(os.path.exists(os.path.join(self.temp.name, "draft_feedback.jsonl")))


if __name__ == "__main__":
    unittest.main()
