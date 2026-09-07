"""Attorney-facing UI consistency: global nav, Matter Builder copy, READY link."""

from __future__ import annotations

import base64
import os
import unittest
from unittest.mock import patch

import app as legalai


CASE_ID = "NY-Nassau-613561-2026-Desousa-v-Rennick"
NAV_HOME = 'href="/">Home</a>'
NAV_WORKSPACE = 'href="/workspace">Attorney Workspace</a>'
NAV_MATTER = 'href="/matter">Matter Builder</a>'
STYLESHEET = 'href="/static/attorney_workspace.css"'
DEV_TAGLINE = (
    "Matter Builder v3 architecture with isolated litigation issue analysis "
    "engine and source-traceable attorney reasoning."
)


def _auth_headers():
    token = base64.b64encode(b"allen@example.com:secret").decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _assert_global_nav(test_case, body, path):
    test_case.assertIn('class="attorney-top-nav"', body, path)
    test_case.assertIn(NAV_HOME, body, path)
    test_case.assertIn(NAV_WORKSPACE, body, path)
    test_case.assertIn(NAV_MATTER, body, path)
    test_case.assertIn(STYLESHEET, body, path)


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


class AttorneyUiConsistencyTests(unittest.TestCase):
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

    def test_inject_attorney_ui_is_idempotent(self):
        bare = "<!doctype html><html><head><title>T</title></head><body><main></main></body></html>"
        once = legalai.inject_attorney_ui(bare)
        twice = legalai.inject_attorney_ui(once)
        self.assertEqual(once.count(STYLESHEET), 1)
        self.assertEqual(once.count('class="attorney-top-nav"'), 1)
        self.assertEqual(twice, once)
        self.assertIn(">Home</a>", once)
        self.assertIn(">Attorney Workspace</a>", once)
        self.assertIn(">Matter Builder</a>", once)

    def test_global_nav_on_key_attorney_pages(self):
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
        registered = [{"case_id": CASE_ID, "stage": "Verified source indexed"}]
        draft_ready = {
            "request_id": "draft-1-abcdef123456",
            "question": "What relief is requested?",
            "requested_by": "allen@example.com",
            "status": "READY",
            "draft": {
                "summary": "Summary.",
                "findings": [],
                "missing_information": [],
            },
        }
        with patch.object(legalai, "load_cases", return_value=[SAMPLE_CASE]), patch.object(
            legalai, "get_similar_cases", return_value=[]
        ), patch.object(legalai, "get_matter", return_value=matter_stub), patch.object(
            legalai, "available_case00_review_questions", return_value=["Q1"]
        ), patch.object(legalai, "load_registered_cases", return_value=registered), patch.object(
            legalai, "load_draft_requests", return_value=[draft_ready]
        ), patch.object(legalai, "load_szymczyk_review_packet", return_value="# Candidate\n"), patch.object(
            legalai, "search_szymczyk_verified_pages", return_value=[]
        ), patch.object(
            legalai,
            "read_latest_szymczyk_feedback",
            return_value={"submitted_at": "2026-01-01", "feedback_markdown": "notes"},
        ), patch.object(
            legalai, "load_case00_review_packet", return_value="# Packet\n"
        ), patch.object(
            legalai, "selected_case00_review_question", return_value="Q1"
        ), patch.object(
            legalai, "packet_for_review_display", return_value="# Packet\n"
        ), patch.object(
            legalai, "packet_for_review_html", return_value="# Candidate\n"
        ):
            paths = [
                "/",
                "/matter",
                "/workspace",
                f"/workspace/matters/{CASE_ID}/draft",
                f"/workspace/matters/{CASE_ID}/drafts",
                f"/workspace/matters/{CASE_ID}/drafts/{draft_ready['request_id']}",
                "/workspace/szymczyk",
                "/szymczyk/review",
                "/szymczyk/feedback/latest",
                "/case-00/review?question=Q1",
            ]
            for path in paths:
                with self.subTest(path=path):
                    response = self.client.get(path, headers=_auth_headers())
                    self.assertEqual(response.status_code, 200, path)
                    body = response.get_data(as_text=True)
                    _assert_global_nav(self, body, path)

    def test_matter_builder_hides_developer_tagline(self):
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
            legalai, "get_matter", return_value=matter_stub
        ):
            response = self.client.get("/matter", headers=_auth_headers())

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertNotIn(DEV_TAGLINE, body)
        self.assertNotIn("v3 architecture", body)
        self.assertNotIn("Issue Engine v3.4", body)
        self.assertIn("Source-traceable issue analysis", body)
        self.assertIn(
            "Build a matter view from the selected case with source-traceable litigation issues and attorney reasoning.",
            body,
        )

    def test_ready_submission_shows_direct_answered_question_link(self):
        request_id = "draft-9-abcdef123456"
        ready_item = {
            "request_id": request_id,
            "question": "What relief is requested?",
            "requested_by": "allen@example.com",
            "status": "READY",
            "draft": {
                "summary": "Summary.",
                "findings": [],
                "missing_information": [],
            },
        }
        with patch.object(
            legalai, "load_registered_cases", return_value=[{"case_id": CASE_ID, "stage": "Verified source indexed"}]
        ), patch.object(legalai, "load_draft_requests", return_value=[ready_item]):
            response = self.client.get(
                f"/workspace/matters/{CASE_ID}/draft?submitted={request_id}&reused=1",
                headers=_auth_headers(),
            )

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("View answered question →", body)
        self.assertIn(
            f'/workspace/matters/{CASE_ID}/drafts/{request_id}',
            body,
        )
        self.assertNotIn("Automatic draft job queued.", body)

    def test_processing_submission_keeps_processing_message(self):
        request_id = "draft-8-abcdef123456"
        queued_item = {
            "request_id": request_id,
            "question": "What relief is requested?",
            "requested_by": "allen@example.com",
            "status": "QUEUED",
            "draft": None,
        }
        with patch.object(
            legalai, "load_registered_cases", return_value=[{"case_id": CASE_ID, "stage": "Verified source indexed"}]
        ), patch.object(legalai, "load_draft_requests", return_value=[queued_item]):
            response = self.client.get(
                f"/workspace/matters/{CASE_ID}/draft?submitted={request_id}&reused=0",
                headers=_auth_headers(),
            )

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Automatic draft job queued.", body)
        self.assertNotIn("View answered question →", body)
        self.assertIn("Questions processing", body)

    def test_pdf_responses_are_not_html_wrapped(self):
        with patch.object(
            legalai,
            "send_from_directory",
            return_value=legalai.Response(b"%PDF-1.4 sample", mimetype="application/pdf"),
        ):
            response = self.client.get("/pdf/sample.pdf", headers=_auth_headers())
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/pdf", response.content_type or "")
        raw = response.get_data()
        self.assertTrue(raw.startswith(b"%PDF"))
        self.assertNotIn(b"attorney-top-nav", raw)


if __name__ == "__main__":
    unittest.main()
