"""Attorney-facing UI consistency: global nav, Matter Builder copy, READY link."""

from __future__ import annotations

import base64
import os
import unittest
from unittest.mock import MagicMock, patch

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
        ), patch.object(
            legalai, "load_exact_draft_request", return_value=draft_ready
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

    def test_free_retrieval_preview_does_not_queue_or_generate(self):
        preview = {
            "citations": [
                {"source_sha256": "a" * 64, "filename": "Complaint.pdf", "page_number": 1},
                {"source_sha256": "a" * 64, "filename": "Complaint.pdf", "page_number": 7},
            ],
            "pleadings": [{"filename": "Complaint.pdf", "page_count": 7}],
            "page_count": 2,
            "context_characters": 2400,
            "page_limit": 45,
            "context_limit": 75000,
            "blocked_reason": None,
            "warnings": [],
        }
        with patch.object(
            legalai, "load_registered_cases", return_value=[{"case_id": CASE_ID, "stage": "Verified source indexed"}]
        ), patch.object(legalai, "load_draft_requests", return_value=[]), patch.object(
            legalai, "preview_draft_retrieval", return_value=preview
        ) as previewer, patch.object(legalai, "create_draft_request") as creator:
            response = self.client.post(
                f"/workspace/matters/{CASE_ID}/draft",
                data={"action": "preview", "question": "What claims and relief are pleaded?"},
                headers=_auth_headers(),
            )
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Retrieval preview — no model called", body)
        self.assertIn("Complaint.pdf — p. 7", body)
        self.assertIn("Preview retrieval — free", body)
        self.assertIn('action="/workspace/matters/', body)
        self.assertIn('#retrieval-preview"', body)
        self.assertIn('id="retrieval-preview"', body)
        previewer.assert_called_once_with(CASE_ID, "What claims and relief are pleaded?")
        creator.assert_not_called()

    def test_missing_action_fails_closed_without_queueing(self):
        with patch.object(
            legalai, "load_registered_cases", return_value=[{"case_id": CASE_ID, "stage": "Verified source indexed"}]
        ), patch.object(legalai, "load_draft_requests", return_value=[]), patch.object(
            legalai, "create_draft_request"
        ) as creator:
            response = self.client.post(
                f"/workspace/matters/{CASE_ID}/draft",
                data={"question": "What claims and relief are pleaded?"},
                headers=_auth_headers(),
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "Unknown request action. Nothing was queued and no model was called.",
            response.get_data(as_text=True),
        )
        creator.assert_not_called()

    def test_submit_feedback_preserves_clicked_action_before_disabling(self):
        self.assertIn('submittedAction.name = submitter.name;', legalai.ATTORNEY_SUBMIT_FEEDBACK_HTML)
        self.assertIn('submittedAction.value = submitter.value;', legalai.ATTORNEY_SUBMIT_FEEDBACK_HTML)
        self.assertLess(
            legalai.ATTORNEY_SUBMIT_FEEDBACK_HTML.index('submittedAction.value = submitter.value;'),
            legalai.ATTORNEY_SUBMIT_FEEDBACK_HTML.index('control.disabled = true;'),
        )

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
        self.assertNotIn('<a class="answer-cta"', body)
        self.assertIn("Questions processing", body)
        self.assertIn(f"/workspace/matters/{CASE_ID}/drafts/{request_id}/status", body)
        self.assertIn("cache:'no-store'", body)

    def test_draft_status_endpoint_returns_ready_link_without_source_text(self):
        request_id = "draft-6-abcdef123456"
        ready_item = {
            "request_id": request_id,
            "question": "What relief is requested?",
            "requested_by": "allen@example.com",
            "status": "READY",
            "draft": {"summary": "Summary.", "findings": [], "missing_information": []},
        }
        portal_response = MagicMock()
        portal_response.__enter__.return_value.read.return_value = (
            b'{"status":"READY","draft_available":true}'
        )
        with patch.object(
            legalai, "load_registered_cases", return_value=[{"case_id": CASE_ID, "stage": "Verified source indexed"}]
        ), patch.object(
            legalai.urllib.request, "urlopen", return_value=portal_response
        ), patch.object(legalai, "load_draft_requests", return_value=[ready_item]) as loader:
            response = self.client.get(
                f"/workspace/matters/{CASE_ID}/drafts/{request_id}/status",
                headers=_auth_headers(),
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "READY")
        self.assertEqual(response.json["answer_url"], f"/workspace/matters/{CASE_ID}/drafts/{request_id}")
        self.assertNotIn("summary", response.get_data(as_text=True).casefold())
        self.assertTrue(loader.call_args.kwargs["force_refresh"])

    def test_exact_ready_status_loads_matching_completed_list_item(self):
        request_id = "draft-6-abcdef123456"
        completed_item = {
            "request_id": request_id,
            "question": "What relief is requested?",
            "requested_by": "allen@example.com",
            "status": "READY",
            "draft": {"summary": "Summary.", "findings": [], "missing_information": []},
        }
        response = MagicMock()
        response.__enter__.return_value.read.return_value = (
            b'{"status":"READY","draft_available":true}'
        )
        with patch.object(
            legalai.urllib.request, "urlopen", return_value=response
        ), patch.object(
            legalai, "load_draft_requests", return_value=[completed_item]
        ) as loader:
            result = legalai.load_exact_draft_request(CASE_ID, request_id)

        self.assertEqual(result, completed_item)
        loader.assert_called_once_with(CASE_ID, force_refresh=True)

    def test_failed_request_is_not_presented_as_processing(self):
        failed_item = {
            "request_id": "draft-7-abcdef123456",
            "question": "An earlier question",
            "requested_by": "allen@example.com",
            "status": "FAILED",
            "failure_code": "corpus",
            "draft": None,
        }
        with patch.object(
            legalai, "load_registered_cases", return_value=[{"case_id": CASE_ID, "stage": "Verified source indexed"}]
        ), patch.object(legalai, "load_draft_requests", return_value=[failed_item]):
            response = self.client.get(
                f"/workspace/matters/{CASE_ID}/draft",
                headers=_auth_headers(),
            )

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertNotIn("Questions processing", body)

    def test_draft_status_endpoint_returns_exact_failure_code(self):
        request_id = "draft-9-abcdef123456"
        failed_item = {
            "request_id": request_id,
            "question": "What relief is requested?",
            "requested_by": "allen@example.com",
            "status": "FAILED",
            "failure_code": "model_output_validation",
            "draft": None,
        }
        with patch.object(legalai, "load_exact_draft_request", return_value=failed_item):
            response = self.client.get(
                f"/workspace/matters/{CASE_ID}/drafts/{request_id}/status",
                headers=_auth_headers(),
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "FAILED")
        self.assertEqual(response.json["failure_code"], "model_output_validation")
        self.assertIsNone(response.json["answer_url"])

    def test_draft_polling_page_handles_failure_code_and_stale_row(self):
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
        self.assertIn(f'data-processing-request="{request_id}"', body)
        self.assertIn("const requestId=", body)
        self.assertIn("This internal draft failed.", body)
        self.assertIn("Failure code: ", body)
        self.assertIn("unspecified_failure", body)
        self.assertIn("No automatic retry was started.", body)
        self.assertIn("panel.classList.remove('success')", body)
        self.assertIn("panel.classList.add('notice')", body)
        self.assertIn("processing?.remove()", body)

    def test_answer_separates_record_and_registry_authority_links(self):
        request_id = "draft-10-abcdef123456"
        ready_item = {
            "request_id": request_id,
            "question": "Does <model> support rescission?",
            "requested_by": "allen@example.com",
            "status": "READY",
            "draft": {
                "summary": "Review <summary>.",
                "findings": [{
                    "section": "Legal standard",
                    "statement": "Finding <script>alert(1)</script>.",
                    "citations": [{
                        "source_sha256": "a" * 64,
                        "filename": "Policy & Application.pdf",
                        "page_number": 7,
                    }],
                    "authority_citations": [
                        "ny-ins-law-3105",
                        "unknown-authority",
                        "https://untrusted.example/authority",
                    ],
                }],
                "missing_information": [],
            },
        }
        with patch.object(legalai, "load_exact_draft_request", return_value=ready_item):
            response = self.client.get(
                f"/workspace/matters/{CASE_ID}/drafts/{request_id}",
                headers=_auth_headers(),
            )

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("<strong>Verified record</strong>", body)
        self.assertIn("<h2>Legal standard</h2>", body)
        self.assertIn("<strong>Legal authority</strong>", body)
        self.assertIn("Representations by the insured — N.Y. Ins. Law § 3105", body)
        self.assertIn(
            'href="https://www.nysenate.gov/legislation/laws/ISC/3105" target="_blank" rel="noopener"',
            body,
        )
        self.assertNotIn("unknown-authority", body)
        self.assertNotIn("untrusted.example", body)
        self.assertNotIn("/pdf/https", body)
        self.assertIn("Finding &lt;script&gt;alert(1)&lt;/script&gt;.", body)
        self.assertIn("Does &lt;model&gt; support rescission?", body)
        self.assertIn("Review &lt;summary&gt;.", body)

    def test_authenticated_reviewer_can_regenerate_another_reviewers_draft(self):
        request_id = "draft-14-abcdef123456"
        ready_item = {
            "request_id": request_id,
            "question": "What is the governing rule?",
            "requested_by": "allenk@example.com",
            "status": "READY",
            "draft": {
                "summary": "Summary.",
                "findings": [],
                "missing_information": [],
            },
        }
        registered = [{"case_id": CASE_ID, "stage": "Verified source indexed"}]
        with patch.object(legalai, "load_registered_cases", return_value=registered), patch.object(
            legalai, "load_draft_requests", return_value=[ready_item]
        ), patch.object(legalai, "load_exact_draft_request", return_value=ready_item), patch.object(
            legalai,
            "create_draft_request",
            return_value={"request_id": "draft-15-bbbbbbbbbbbb", "reused": False},
        ) as create:
            listing = self.client.get(
                f"/workspace/matters/{CASE_ID}/drafts", headers=_auth_headers()
            )
            detail = self.client.get(
                f"/workspace/matters/{CASE_ID}/drafts/{request_id}",
                headers=_auth_headers(),
            )
            submit = self.client.post(
                f"/workspace/matters/{CASE_ID}/draft",
                data={"action": "regenerate", "request_id": request_id},
                headers=_auth_headers(),
            )

        self.assertIn("Regenerate this draft", listing.get_data(as_text=True))
        self.assertIn("Regenerate this completed draft", detail.get_data(as_text=True))
        self.assertEqual(submit.status_code, 303)
        create.assert_called_once_with(
            CASE_ID,
            "What is the governing rule?",
            "allenk@example.com",
            regenerate_from=request_id,
        )

    def test_legacy_answer_keeps_record_link_and_uses_missing_information_list(self):
        request_id = "draft-11-abcdef123456"
        ready_item = {
            "request_id": request_id,
            "question": "What remains missing?",
            "requested_by": "allen@example.com",
            "status": "READY",
            "draft": {
                "summary": "Summary.",
                "findings": [{
                    "statement": "Legacy finding.",
                    "citations": [{
                        "source_sha256": "b" * 64,
                        "filename": "Legacy.pdf",
                        "page_number": 2,
                    }],
                }],
                "missing_information": ["First item", "Second <item>"],
            },
        }
        with patch.object(legalai, "load_exact_draft_request", return_value=ready_item):
            response = self.client.get(
                f"/workspace/matters/{CASE_ID}/drafts/{request_id}",
                headers=_auth_headers(),
            )

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("<strong>Verified record</strong>", body)
        self.assertNotIn("<strong>Legal authority</strong>", body)
        self.assertIn("Open verified source — p. 2 · Legacy.pdf", body)
        self.assertIn(
            "<h2>Missing information</h2><ul><li>First item</li><li>Second &lt;item&gt;</li></ul>",
            body,
        )
        self.assertNotIn("First item; Second", body)

    def test_retrieval_audit_separates_authorities_and_supports_legacy_audits(self):
        request_id = "draft-12-abcdef123456"
        current_audit = {
            "requested_by": "allen@example.com",
            "citations": [{"filename": "Record.pdf", "page_number": 4}],
            "legal_authorities": [{
                "authority_id": "ny-ins-law-3105",
                "citation": "N.Y. Ins. Law § 3105",
                "title": "Representations by the insured",
                "source_url": "https://www.nysenate.gov/legislation/laws/ISC/3105",
                "issuing_body": "New York State Legislature",
                "date": "1984-09-01",
                "sha256": "a" * 64,
            }],
        }
        path = f"/workspace/matters/{CASE_ID}/drafts/{request_id}/audit"
        with patch.object(legalai, "load_draft_input_audit", return_value=current_audit):
            response = self.client.get(path, headers=_auth_headers())

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("<h2>Verified record</h2>", body)
        self.assertIn("Record.pdf — p. 4", body)
        self.assertIn("<h2>Legal authorities</h2>", body)
        self.assertIn("Representations by the insured — N.Y. Ins. Law § 3105", body)
        self.assertNotIn("https://www.nysenate.gov", body)

        legacy_audit = {
            "requested_by": "allen@example.com",
            "citations": [{"filename": "Legacy.pdf", "page_number": 1}],
        }
        with patch.object(legalai, "load_draft_input_audit", return_value=legacy_audit):
            legacy_response = self.client.get(path, headers=_auth_headers())
        self.assertEqual(legacy_response.status_code, 200)
        legacy_body = legacy_response.get_data(as_text=True)
        self.assertIn("Legacy.pdf — p. 1", legacy_body)
        self.assertNotIn("<h2>Legal authorities</h2>", legacy_body)

    def test_retrieval_audit_loader_defaults_missing_authorities_to_empty(self):
        gateway_response = MagicMock()
        gateway_response.__enter__.return_value.read.return_value = (
            b'{"ok":true,"requested_by":"allen@example.com",'
            b'"retrieval_citations":[{"filename":"Legacy.pdf","page_number":1}]}'
        )
        with patch.object(
            legalai.urllib.request, "urlopen", return_value=gateway_response
        ):
            audit = legalai.load_draft_input_audit(
                CASE_ID, "draft-13-abcdef123456"
            )

        self.assertEqual(audit["legal_authorities"], [])
        self.assertEqual(audit["citations"][0]["filename"], "Legacy.pdf")


    def test_authenticated_reviewer_can_open_another_reviewers_retrieval_audit(self):
        request_id = "draft-15-abcdef123456"
        audit = {
            "requested_by": "original@example.com",
            "citations": [{"filename": "Complaint.pdf", "page_number": 1}],
            "legal_authorities": [],
        }
        path = f"/workspace/matters/{CASE_ID}/drafts/{request_id}/audit"
        with patch.object(legalai, "load_draft_input_audit", return_value=audit):
            response = self.client.get(path, headers=_auth_headers())
        self.assertEqual(response.status_code, 200)
        self.assertIn("Complaint.pdf — p. 1", response.get_data(as_text=True))

    def test_retrieval_audit_falls_back_to_completed_draft_citations(self):
        request_id = "draft-16-abcdef123456"
        completed = {
            "requested_by": "original@example.com",
            "status": "READY",
            "draft": {
                "findings": [{
                    "statement": "Supported finding.",
                    "citations": [
                        {"filename": "Complaint.pdf", "page_number": 2},
                        {"filename": "Complaint.pdf", "page_number": 2},
                    ],
                    "authority_citations": [],
                }],
            },
        }
        path = f"/workspace/matters/{CASE_ID}/drafts/{request_id}/audit"
        with patch.object(legalai, "load_draft_input_audit", return_value=None), patch.object(
            legalai, "load_exact_draft_request", return_value=completed
        ):
            response = self.client.get(path, headers=_auth_headers())
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("1 verified page", body)
        self.assertIn("Complaint.pdf — p. 2", body)

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
