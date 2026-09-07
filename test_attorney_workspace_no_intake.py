"""Attorney workspace must not expose Gateway GitHub-OAuth admin intake."""

from __future__ import annotations

import base64
import os
import unittest
from unittest.mock import patch

import app as legalai


CASE_ID = "NY-Nassau-613561-2026-Desousa-v-Rennick"
GATEWAY_URL = "https://gateway.example"


def _auth_headers():
    token = base64.b64encode(b"allen@example.com:secret").decode("ascii")
    return {"Authorization": f"Basic {token}"}


class AttorneyWorkspaceNoIntakeTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {
                "LEGALAI_REVIEW_GATEWAY_URL": GATEWAY_URL,
                "LEGALAI_REVIEW_GATEWAY_SECRET": "secret",
                "LEGALAI_REVIEW_USERS_JSON": '{"allen@example.com":"secret"}',
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_workspace_html_has_no_gateway_intake_link(self):
        registered = [
            {"case_id": "NY-Pending-Only-Registered", "stage": "Registered"},
            {"case_id": CASE_ID, "stage": "Verified source indexed"},
        ]
        with patch.object(
            legalai,
            "available_case00_review_questions",
            return_value=[{"id": "Q1", "label": "Prepared question"}],
        ), patch.object(
            legalai,
            "load_registered_cases",
            return_value=registered,
        ), patch.object(
            legalai,
            "load_draft_requests",
            return_value=[],
        ), patch.object(
            legalai,
            "load_szymczyk_review_packet",
            return_value=None,
        ):
            response = legalai.app.test_client().get("/workspace", headers=_auth_headers())

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("/intake", body)
        self.assertNotIn(f"{GATEWAY_URL}/intake", body)
        self.assertNotIn("New verified matter", body)
        self.assertNotIn("Administrator intake", body)
        self.assertNotIn("Upload and verify a new source matter", body)
        self.assertNotIn("Add verified source ZIP and manifest", body)
        self.assertNotIn("NY-Pending-Only-Registered", body)

        # Attorney Basic-Auth workspace features remain present.
        self.assertIn("LegalAI Attorney Workspace", body)
        self.assertIn("/workspace/case-00/search", body)
        self.assertIn("/workspace/case-00/sources", body)
        self.assertIn("/workspace/case-00/draft", body)
        self.assertIn("/workspace/case-00/answered", body)
        self.assertIn(f"/workspace/matters/{CASE_ID}/search", body)
        self.assertIn(f"/workspace/matters/{CASE_ID}/sources", body)
        self.assertIn(f"/workspace/matters/{CASE_ID}/draft", body)
        self.assertIn("Search verified record", body)
        self.assertIn("View verified record map", body)
        self.assertIn("Ask a new review question", body)


if __name__ == "__main__":
    unittest.main()
