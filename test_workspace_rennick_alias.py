import json
import os
import unittest
from unittest.mock import patch

import app as legalai


CANONICAL_ID = "NY-Nassau-613561-2026-Desousa-v-Rennick"
LEGACY_ID = "NY-Nassau-613561-2026-Rennick"


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class WorkspaceRennickAliasTests(unittest.TestCase):
    def test_review_packet_uses_corrected_motion_recommendation(self):
        self.assertEqual(
            legalai.RENNICK_ATTORNEY_REVIEW_PACKET_DRAFT_IDS,
            (
                "draft-1790275196-5d33f8a041c2",
                "draft-1790200223-c52acd236d81",
            ),
        )

    def test_legacy_placeholder_becomes_one_canonical_indexed_matter(self):
        payload = {
            "cases": [
                {"case_id": LEGACY_ID, "stage": "Intake stored"},
                {"case_id": CANONICAL_ID, "stage": "Verified source indexed"},
            ]
        }
        with patch.dict(
            os.environ,
            {"LEGALAI_REVIEW_GATEWAY_URL": "https://gateway.example", "LEGALAI_REVIEW_GATEWAY_SECRET": "secret"},
            clear=False,
        ), patch.object(legalai.urllib.request, "urlopen", return_value=_Response(payload)):
            self.assertEqual(
                legalai.load_registered_cases(),
                [{"case_id": CANONICAL_ID, "stage": "Verified source indexed"}],
            )


    def test_packet_links_each_analysis_to_its_structured_review_form(self):
        ready_items = {
            request_id: {
                "request_id": request_id,
                "status": "READY",
                "question": "Test motion question",
                "draft": {
                    "summary": "Test summary",
                    "findings": [],
                    "missing_information": [],
                },
            }
            for request_id in legalai.RENNICK_ATTORNEY_REVIEW_PACKET_DRAFT_IDS
        }
        with patch.object(legalai, "basic_review_user", return_value="john"), patch.object(
            legalai,
            "load_exact_draft_request",
            side_effect=lambda _case_id, request_id: ready_items[request_id],
        ):
            response = legalai.app.test_client().get(
                f"/workspace/matters/{CANONICAL_ID}/review-packet"
            )
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        for request_id in legalai.RENNICK_ATTORNEY_REVIEW_PACKET_DRAFT_IDS:
            self.assertIn(
                f"/workspace/matters/{CANONICAL_ID}/drafts/{request_id}#attorney-review",
                page,
            )
        self.assertIn("Save attorney review", page)

    def test_archived_response_shows_signed_tro_correction_and_verified_pdf_link(self):
        recommendation_id, response_id = legalai.RENNICK_ATTORNEY_REVIEW_PACKET_DRAFT_IDS
        ready_items = {
            request_id: {
                "request_id": request_id,
                "status": "READY",
                "question": "Test motion question",
                "draft": {
                    "summary": "Original archived summary",
                    "findings": [],
                    "missing_information": ["The exact signed TRO terms remain unresolved."],
                },
            }
            for request_id in (recommendation_id, response_id)
        }
        with patch.object(legalai, "basic_review_user", return_value="john"), patch.object(
            legalai, "load_exact_draft_request",
            side_effect=lambda _case_id, request_id: ready_items[request_id],
        ):
            client = legalai.app.test_client()
            packet = client.get(f"/workspace/matters/{CANONICAL_ID}/review-packet")
            response = client.get(f"/workspace/matters/{CANONICAL_ID}/drafts/{response_id}")
            recommendation = client.get(f"/workspace/matters/{CANONICAL_ID}/drafts/{recommendation_id}")

        self.assertEqual((packet.status_code, response.status_code, recommendation.status_code), (200, 200, 200))
        for page in (packet.get_data(as_text=True), response.get_data(as_text=True)):
            self.assertEqual(page.count("Verified record correction to this archived draft."), 1)
            self.assertIn("ORDER_TO_SHOW_CAUSE_32.pdf", page)
            self.assertIn(legalai.RENNICK_RESPONSE_TRO_CORRECTION["source_sha256"], page)
            self.assertIn("#page=2", page)
            self.assertIn("The exact signed TRO terms remain unresolved.", page)
        self.assertNotIn("Verified record correction", recommendation.get_data(as_text=True))
        self.assertEqual(ready_items[response_id]["draft"]["summary"], "Original archived summary")


    def test_packet_saves_review_against_the_selected_exact_draft(self):
        ready_items = {
            request_id: {
                "request_id": request_id,
                "status": "READY",
                "question": "Test motion question",
                "draft": {
                    "summary": "Test summary",
                    "findings": [],
                    "missing_information": [],
                },
            }
            for request_id in legalai.RENNICK_ATTORNEY_REVIEW_PACKET_DRAFT_IDS
        }
        request_id = legalai.RENNICK_ATTORNEY_REVIEW_PACKET_DRAFT_IDS[0]
        with patch.object(legalai, "basic_review_user", return_value="john"), patch.object(
            legalai,
            "load_exact_draft_request",
            side_effect=lambda _case_id, selected_id: ready_items[selected_id],
        ), patch.object(
            legalai, "draft_review_feedback_csrf_token", return_value="packet-token"
        ), patch.object(
            legalai, "archive_draft_review_feedback", return_value={"saved": True}
        ) as archive, patch.object(
            legalai, "notify_draft_review_feedback"
        ) as notify:
            response = legalai.app.test_client().post(
                f"/workspace/matters/{CANONICAL_ID}/review-packet",
                data={
                    "request_id": request_id,
                    "feedback_csrf_token": "packet-token",
                    "decision": "needs_revision",
                    "accuracy_rating": "2",
                    "usefulness_rating": "3",
                    "procedural_posture_rating": "2",
                    "record_use_rating": "3",
                    "law_and_evidence_rating": "4",
                    "counterarguments_rating": "2",
                    "next_steps_rating": "3",
                    "missing_or_overstated": "Explain the permit conflict.",
                    "citation_problems": "",
                    "comments": "Address the counterargument.",
                },
            )
        self.assertEqual(response.status_code, 303)
        self.assertIn(f"review={request_id}", response.headers["Location"])
        archive.assert_called_once_with(
            "john",
            CANONICAL_ID,
            request_id,
            "needs_revision",
            2,
            3,
            "Explain the permit conflict.",
            "",
            "Address the counterargument.",
            {
                "procedural_posture": 2,
                "record_use": 3,
                "law_and_evidence": 4,
                "counterarguments": 2,
                "next_steps": 3,
            },
        )
        notify.assert_called_once_with({"saved": True})
