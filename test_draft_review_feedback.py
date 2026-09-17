import base64
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

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
                "LEGALAI_OPERATOR_API_TOKEN": "operator-secret",
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
        with patch.object(legalai, "load_exact_draft_request", return_value=ready_item()), patch.object(
            legalai, "notify_draft_review_feedback", return_value=True
        ) as notify:
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
        notify.assert_called_once()

    def test_b2_archive_uses_deterministic_bounded_object(self):
        record = {
            "schema_version": 1,
            "submitted_at": 1789670000,
            "reviewer": "johncuomo@gmail.com",
            "case_id": CASE_ID,
            "request_id": REQUEST_ID,
            "decision": "approve",
            "accuracy_rating": 5,
            "usefulness_rating": 5,
            "missing_or_overstated": "",
            "citation_problems": "",
            "comments": "Good.",
        }
        env = {
            "B2_ENDPOINT": "https://s3.example",
            "B2_REGION": "us-test-1",
            "B2_KEY_ID": "key",
            "B2_APPLICATION_KEY": "secret",
            "B2_BUCKET": "legalai-corpus",
        }
        client = MagicMock()
        with patch.dict(os.environ, env, clear=False), patch.object(
            legalai.boto3, "client", return_value=client
        ):
            self.assertTrue(legalai.archive_draft_review_feedback_to_b2(record))
        call = client.put_object.call_args.kwargs
        self.assertEqual(call["Bucket"], "legalai-corpus")
        self.assertIn(
            f"cases/{CASE_ID}/derived/attorney-feedback/{REQUEST_ID}/1789670000-",
            call["Key"],
        )
        self.assertEqual(call["ContentType"], "application/json")
        self.assertEqual(len(call["Metadata"]["sha256"]), 64)

    def test_notification_excludes_private_comments(self):
        response = MagicMock()
        response.__enter__.return_value.status = 200
        record = {
            "reviewer": "johncuomo@gmail.com",
            "case_id": CASE_ID,
            "request_id": REQUEST_ID,
            "decision": "needs_revision",
            "accuracy_rating": 4,
            "usefulness_rating": 3,
            "comments": "PRIVATE COMMENT",
        }
        with patch.dict(
            os.environ,
            {"PUSHOVER_APP_TOKEN": "token", "PUSHOVER_USER_KEY": "user"},
            clear=False,
        ), patch.object(legalai.urllib.request, "urlopen", return_value=response) as send:
            self.assertTrue(legalai.notify_draft_review_feedback(record))
        body = send.call_args.args[0].data.decode("utf-8")
        self.assertIn("needs+revision", body)
        self.assertNotIn("PRIVATE", body)

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

    def test_operator_api_submits_and_reuses_exact_review(self):
        payload = {
            "reviewer": "johncuomo@gmail.com",
            "case_id": CASE_ID,
            "request_id": REQUEST_ID,
            "decision": "needs_revision",
            "accuracy_rating": 3,
            "usefulness_rating": 3,
            "missing_or_overstated": "Retrieve the complete pleading.",
            "citation_problems": "Only isolated pages were cited.",
            "comments": "Do not regenerate yet.",
        }
        headers = {
            "Authorization": "Bearer operator-secret",
            "Content-Type": "application/json",
        }
        with patch.object(legalai, "archive_draft_review_feedback_to_b2", return_value=True), patch.object(
            legalai, "notify_draft_review_feedback", return_value=True
        ) as notify:
            created = self.client.post("/internal/reviews", headers=headers, json=payload)
            reused = self.client.post("/internal/reviews", headers=headers, json=payload)
            verified = self.client.get(
                "/internal/reviews",
                headers={"Authorization": "Bearer operator-secret"},
                query_string={
                    "reviewer": payload["reviewer"],
                    "case_id": payload["case_id"],
                    "request_id": payload["request_id"],
                },
            )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(reused.status_code, 200)
        self.assertFalse(created.get_json()["reused"])
        self.assertTrue(reused.get_json()["reused"])
        self.assertTrue(verified.get_json()["exists"])
        with open(os.path.join(self.temp.name, "draft_feedback.jsonl"), encoding="utf-8") as stream:
            self.assertEqual(len(stream.readlines()), 1)
        notify.assert_called_once()

    def test_operator_api_rejects_missing_token(self):
        response = self.client.get("/internal/reviews")
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
