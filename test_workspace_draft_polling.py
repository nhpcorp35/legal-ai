"""Focused browser polling behavior for queued internal drafts."""

from __future__ import annotations

import base64
import os
import unittest
from unittest.mock import patch

import app as legalai


CASE_ID = "NY-NewYork-158068-2018-Szymczyk-v-Hudson-36-37"
REQUEST_ID = "draft-1000-aaaaaaaaaaaa"


def _auth_headers():
    token = base64.b64encode(b"allen@example.com:secret").decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _request(status=None):
    item = {
        "request_id": REQUEST_ID,
        "question": "What relief is requested?",
        "requested_by": "allen@example.com",
        "status": status,
        "created_at": 1_000,
        "draft": None,
    }
    return item


class WorkspaceDraftPollingTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(
            os.environ, {"LEGALAI_REVIEW_USERS_JSON": '{"allen@example.com":"secret"}'}, clear=False
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_submission_with_status_not_yet_listed_starts_polling(self):
        with patch.object(
            legalai, "load_registered_cases",
            return_value=[{"case_id": CASE_ID, "stage": "Verified source indexed"}],
        ), patch.object(legalai, "load_draft_requests", return_value=[]):
            response = legalai.app.test_client().get(
                f"/workspace/matters/{CASE_ID}/draft?submitted={REQUEST_ID}",
                headers=_auth_headers(),
            )

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("window.setInterval(check,15000)", html)
        self.assertIn("window.location.assign(update.answer_url)", html)

    def test_completed_submission_does_not_start_polling(self):
        ready = _request(status="READY")
        ready["draft"] = {"summary": "ready"}
        with patch.object(
            legalai, "load_registered_cases",
            return_value=[{"case_id": CASE_ID, "stage": "Verified source indexed"}],
        ), patch.object(legalai, "load_draft_requests", return_value=[ready]):
            response = legalai.app.test_client().get(
                f"/workspace/matters/{CASE_ID}/draft?submitted={REQUEST_ID}",
                headers=_auth_headers(),
            )

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("window.setInterval(check,15000)", html)


if __name__ == "__main__":
    unittest.main()
