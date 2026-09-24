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
        self.assertIn("Open analysis and submit review", page)
