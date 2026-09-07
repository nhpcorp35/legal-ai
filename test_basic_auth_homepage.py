"""Basic Auth gate for the attorney home page and linked surfaces."""

from __future__ import annotations

import base64
import os
import unittest
from unittest.mock import patch

import app as legalai


SAMPLE_CASE = {
    "case_id": "2025-06955",
    "title": "Sample Case",
    "formatted_text": "Holding text.",
    "text": "Holding text.",
    "court": "Appellate Division",
    "outcome": "affirmed",
    "citation": "1 N.Y.3d 1",
    "date": "2025-01-01",
    "file": "sample.pdf",
    "court_rank": 1,
    "motion": "",
    "primary_cause": "",
    "record_type": "decision",
    "holding": "Holding.",
    "key_points": [],
    "rule": "Rule.",
    "trust_signals": [],
    "similarity_signals": [],
    "snippet": "Holding text.",
    "summary": "Summary.",
    "docket": "2025-06955",
    "case_number": "2025-06955",
}


def _auth_headers():
    token = base64.b64encode(b"allen@example.com:secret").decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _assert_basic_auth_challenge(test_case, response, path):
    test_case.assertEqual(response.status_code, 401, path)
    test_case.assertEqual(response.get_data(as_text=True), "Authentication required.")
    challenge = response.headers.get("WWW-Authenticate", "")
    test_case.assertIn('Basic realm="Case-00 Attorney Review"', challenge, path)


class BasicAuthHomepageTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {
                "LEGALAI_REVIEW_GATEWAY_URL": "https://gateway.example",
                "LEGALAI_REVIEW_GATEWAY_SECRET": "secret",
                "LEGALAI_REVIEW_USERS_JSON": '{"allen@example.com":"secret"}',
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client = legalai.app.test_client()

    def test_unauthenticated_get_root_is_challenged(self):
        response = self.client.get("/")
        _assert_basic_auth_challenge(self, response, "/")

    def test_authenticated_get_root_succeeds(self):
        with patch.object(legalai, "load_cases", return_value=[SAMPLE_CASE]), patch.object(
            legalai, "get_similar_cases", return_value=[]
        ):
            response = self.client.get("/", headers=_auth_headers())

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Matter Builder", body)
        self.assertIn("/matter", body)

    def test_root_page_links_do_not_bypass_auth(self):
        for path in ("/matter", "/case/2025-06955", "/pdf/sample.pdf"):
            with self.subTest(path=path):
                response = self.client.get(path)
                _assert_basic_auth_challenge(self, response, path)

    def test_authenticated_home_linked_surfaces_succeed(self):
        matter_stub = {
            "selected_case": None,
            "matter_name": "Test Matter",
            "document_count": 0,
            "index_number": "—",
            "issue_packet": {
                "engine": "Issue Engine v3.4",
                "scored_issues": [],
                "core_issues": [],
                "attack_points": [],
                "missing_evidence": [],
                "weak_claims": [],
                "priority_ranking": [],
                "fact_risk_flags": [],
                "credibility_flags": [],
            },
            "contradiction_analysis": {"cards": []},
            "groups": {},
        }
        with patch.object(legalai, "load_cases", return_value=[SAMPLE_CASE]), patch.object(
            legalai, "get_similar_cases", return_value=[]
        ), patch.object(
            legalai,
            "get_matter",
            return_value=matter_stub,
        ), patch.object(
            legalai,
            "send_from_directory",
            return_value=legalai.Response(b"%PDF-1.4", mimetype="application/pdf"),
        ):
            matter = self.client.get("/matter", headers=_auth_headers())
            case = self.client.get("/case/2025-06955", headers=_auth_headers())
            pdf = self.client.get("/pdf/sample.pdf", headers=_auth_headers())

        self.assertEqual(matter.status_code, 200)
        self.assertEqual(case.status_code, 200)
        self.assertEqual(pdf.status_code, 200)

    def test_workspace_auth_behavior_unchanged(self):
        unauthenticated = self.client.get("/workspace")
        _assert_basic_auth_challenge(self, unauthenticated, "/workspace")

        with patch.object(
            legalai, "available_case00_review_questions", return_value=[]
        ), patch.object(
            legalai, "load_registered_cases", return_value=[]
        ), patch.object(
            legalai, "load_draft_requests", return_value=[]
        ), patch.object(
            legalai, "load_szymczyk_review_packet", return_value=None
        ):
            authenticated = self.client.get("/workspace", headers=_auth_headers())

        self.assertEqual(authenticated.status_code, 200)
        self.assertIn("LegalAI Attorney Workspace", authenticated.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
