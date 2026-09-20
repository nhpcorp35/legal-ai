import os
import secrets
import tempfile
import unittest
from unittest.mock import patch

import app as legalai


CASE_ID = "NY-Nassau-613561-2026-Desousa-v-Rennick"
SOURCE_ID = "draft-1789868106-307fde012f99"
REPLACEMENT_ID = "draft-1789999999-aaaaaaaaaaaa"
REVIEWER = "reviewer@example.com"
OPERATOR_TOKEN = secrets.token_urlsafe(24)
REVIEWER_PASSWORD = secrets.token_urlsafe(24)
SECOND_REVIEWER_PASSWORD = secrets.token_urlsafe(24)


class OperatorDraftRegenerationTests(unittest.TestCase):
    def setUp(self):
        self.client = legalai.app.test_client()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env = patch.dict(
            os.environ,
            {
                "LEGALAI_OPERATOR_API_TOKEN": OPERATOR_TOKEN,
                "LEGALAI_REVIEW_DATA_DIR": self.temp_dir.name,
                "LEGALAI_REVIEW_ALLEN_USERNAME": REVIEWER,
                "LEGALAI_REVIEW_ALLEN_PASSWORD": REVIEWER_PASSWORD,
                "LEGALAI_REVIEW_JOHN_USERNAME": "second@example.com",
                "LEGALAI_REVIEW_JOHN_PASSWORD": SECOND_REVIEWER_PASSWORD,
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp_dir.cleanup()

    @staticmethod
    def _headers():
        return {
            "Authorization": f"Bearer {OPERATOR_TOKEN}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _payload(**overrides):
        payload = {
            "case_id": CASE_ID,
            "request_id": SOURCE_ID,
            "reviewer": REVIEWER,
            "operator": "hal",
            "action_id": "operator-regen-20260920-rennick-01",
            "paid_generation_confirmed": True,
        }
        payload.update(overrides)
        return payload

    def test_requires_operator_authentication(self):
        response = self.client.post(
            "/internal/drafts/regenerate", json=self._payload()
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"], "unauthorized")

    def test_requires_explicit_paid_generation_confirmation(self):
        response = self.client.post(
            "/internal/drafts/regenerate",
            json=self._payload(paid_generation_confirmed=False),
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.get_json()["error"], "paid generation confirmation required"
        )

    def test_preserves_owner_links_original_and_archives_operator(self):
        original = {
            "request_id": SOURCE_ID,
            "question": "What elements or issues are weakest for Defendants?",
            "requested_by": REVIEWER,
            "status": "READY",
            "draft": {"summary": "Original", "findings": []},
        }
        with patch.object(
            legalai, "load_exact_draft_request", return_value=original
        ), patch.object(
            legalai,
            "create_draft_request",
            return_value={"request_id": REPLACEMENT_ID, "reused": False},
        ) as create:
            response = self.client.post(
                "/internal/drafts/regenerate",
                json=self._payload(),
                headers=self._headers(),
            )

        self.assertEqual(response.status_code, 201)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["regeneration"]["reviewer"], REVIEWER)
        self.assertEqual(body["regeneration"]["operator"], "hal")
        self.assertEqual(body["regeneration"]["source_request_id"], SOURCE_ID)
        self.assertEqual(
            body["regeneration"]["replacement_request_id"], REPLACEMENT_ID
        )
        create.assert_called_once_with(
            CASE_ID,
            original["question"],
            REVIEWER,
            regenerate_from=SOURCE_ID,
        )

    def test_action_id_is_idempotent_and_does_not_repeat_paid_request(self):
        original = {
            "request_id": SOURCE_ID,
            "question": "What is weakest?",
            "requested_by": REVIEWER,
            "status": "READY",
        }
        with patch.object(
            legalai, "load_exact_draft_request", return_value=original
        ), patch.object(
            legalai,
            "create_draft_request",
            return_value={"request_id": REPLACEMENT_ID, "reused": False},
        ) as create:
            first = self.client.post(
                "/internal/drafts/regenerate",
                json=self._payload(),
                headers=self._headers(),
            )
            second = self.client.post(
                "/internal/drafts/regenerate",
                json=self._payload(),
                headers=self._headers(),
            )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.get_json()["reused"])
        self.assertEqual(create.call_count, 1)

    def test_rejects_mismatched_reviewer(self):
        original = {
            "request_id": SOURCE_ID,
            "question": "What is weakest?",
            "requested_by": "second@example.com",
            "status": "READY",
        }
        with patch.object(
            legalai, "load_exact_draft_request", return_value=original
        ), patch.object(legalai, "create_draft_request") as create:
            response = self.client.post(
                "/internal/drafts/regenerate",
                json=self._payload(),
                headers=self._headers(),
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"], "source draft reviewer mismatch")
        create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
