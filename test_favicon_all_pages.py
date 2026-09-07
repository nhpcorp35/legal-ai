"""Favicon coverage: every HTML page served by legal-ai includes the LegalAI icon."""

from __future__ import annotations

import base64
import os
import unittest
from unittest.mock import patch

import app as legalai


CASE_ID = "NY-Nassau-613561-2026-Desousa-v-Rennick"
FAVICON_LINK = '<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">'


def _auth_headers():
    token = base64.b64encode(b"allen@example.com:secret").decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _assert_favicon(test_case, response, path):
    test_case.assertEqual(response.status_code, 200, path)
    test_case.assertIn("text/html", response.content_type or "", path)
    body = response.get_data(as_text=True)
    test_case.assertIn(FAVICON_LINK, body, path)


class FaviconCoverageTests(unittest.TestCase):
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

    def test_favicon_asset_and_ico_compat_route(self):
        asset = self.client.get("/static/favicon.svg")
        self.assertEqual(asset.status_code, 200)
        self.assertIn("image/svg+xml", asset.content_type or "")
        self.assertIn(b"<svg", asset.get_data()[:200])

        ico = self.client.get("/favicon.ico", follow_redirects=False)
        self.assertIn(ico.status_code, {301, 302})
        self.assertEqual(ico.headers.get("Location"), "/static/favicon.svg")

    def test_inject_favicon_helper_is_idempotent(self):
        bare = "<!doctype html><html><head><title>T</title></head><body></body></html>"
        once = legalai.inject_favicon_link(bare)
        twice = legalai.inject_favicon_link(once)
        self.assertEqual(once.count(FAVICON_LINK), 1)
        self.assertEqual(twice, once)

    def test_public_html_pages_include_favicon(self):
        cases = [
            {
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
        ]
        with patch.object(legalai, "load_cases", return_value=cases), patch.object(
            legalai, "get_similar_cases", return_value=[]
        ):
            for path in ("/", "/matter", "/case/2025-06955"):
                _assert_favicon(
                    self, self.client.get(path, headers=_auth_headers()), path
                )

    def test_workspace_and_review_html_pages_include_favicon(self):
        registered = [{"case_id": CASE_ID, "stage": "Verified source indexed"}]
        questions = ["Q1"]
        draft_ready = {
            "request_id": "draft-1-abcdef123456",
            "question": "What relief is requested?",
            "requested_by": "allen@example.com",
            "status": "READY",
            "created_at": 1,
            "draft": {
                "summary": "Draft summary.",
                "findings": [{"statement": "Finding.", "citations": []}],
                "missing_information": [],
            },
            "failure_code": None,
        }
        source_map = [
            {"source_sha256": "a" * 64, "filename": "Record.pdf", "pages": 2}
        ]
        case00_docs = [{"filename": "Complaint.pdf", "pages": 3}]

        with patch.object(legalai, "load_registered_cases", return_value=registered), patch.object(
            legalai, "available_case00_review_questions", return_value=questions
        ), patch.object(legalai, "load_draft_requests", return_value=[draft_ready]), patch.object(
            legalai, "load_szymczyk_review_packet", return_value="# Candidate\n"
        ), patch.object(
            legalai, "search_case00_verified_pages", return_value=[]
        ), patch.object(
            legalai, "load_case00_source_map", return_value=case00_docs
        ), patch.object(
            legalai, "search_indexed_case", return_value=[]
        ), patch.object(
            legalai, "load_case_source_map", return_value=source_map
        ), patch.object(
            legalai, "search_szymczyk_verified_pages", return_value=[]
        ), patch.object(
            legalai, "load_case00_review_packet", return_value="# Case-00 packet\n"
        ), patch.object(
            legalai, "selected_case00_review_question", return_value="Q1"
        ), patch.object(
            legalai, "packet_for_review_display", return_value="packet text"
        ), patch.object(
            legalai, "packet_for_review_html", return_value="packet html"
        ), patch.object(
            legalai,
            "read_latest_szymczyk_feedback",
            return_value={
                "submitted_at": "2026-01-01T00:00:00Z",
                "feedback_markdown": "notes",
            },
        ):
            paths = [
                "/workspace",
                "/workspace/case-00/search",
                "/workspace/case-00/answered",
                "/workspace/case-00/sources",
                "/workspace/case-00/draft",
                "/workspace/case-00/drafts",
                f"/workspace/case-00/drafts/{draft_ready['request_id']}",
                f"/workspace/matters/{CASE_ID}/search",
                f"/workspace/matters/{CASE_ID}/sources",
                f"/workspace/matters/{CASE_ID}/draft",
                f"/workspace/matters/{CASE_ID}/drafts",
                f"/workspace/matters/{CASE_ID}/drafts/{draft_ready['request_id']}",
                "/workspace/szymczyk",
                "/case-00/review",
                "/szymczyk/review",
                "/szymczyk/feedback/latest",
            ]
            for path in paths:
                _assert_favicon(self, self.client.get(path, headers=_auth_headers()), path)

    def test_html_template_files_declare_favicon(self):
        templates_dir = os.path.join(legalai.BASE_DIR, "templates")
        for name in sorted(os.listdir(templates_dir)):
            if not name.endswith(".html"):
                continue
            path = os.path.join(templates_dir, name)
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            self.assertIn(
                FAVICON_LINK,
                text,
                f"templates/{name} must declare the LegalAI favicon link",
            )


if __name__ == "__main__":
    unittest.main()
