import io
import json
import unittest
from unittest.mock import patch

import app as legalai


CASE_ID = "NY-Nassau-613561-2026-Desousa-v-Rennick"
REQUEST_ID = "draft-1790275196-5d33f8a041c2"


class _B2:
    def __init__(self, objects):
        self.objects = objects
        self.calls = []

    def get_object(self, *, Bucket, Key):
        self.calls.append(("get", Bucket, Key))
        return {"Body": io.BytesIO(json.dumps(self.objects[Key]).encode("utf-8"))}

    def list_objects_v2(self, *, Bucket, Prefix, MaxKeys):
        self.calls.append(("list", Bucket, Prefix))
        return {"Contents": [{"Key": key} for key in self.objects if key.startswith(Prefix) and key.endswith(".json") and "/draft-requests/" in key]}


class DirectB2DraftReadTests(unittest.TestCase):
    def setUp(self):
        prefix = f"cases/{CASE_ID}/derived"
        self.objects = {
            f"{prefix}/draft-requests/{REQUEST_ID}.json": {
                "schema_version": "legalai-draft-request.v1",
                "case_id": CASE_ID,
                "external_communication": False,
                "question": "I need to make a motion. Which motions should I consider?",
                "requested_by": "john",
                "created_at": 1790275196,
            },
            f"{prefix}/internal-drafts/{REQUEST_ID}/status.json": {
                "status": "READY",
            },
            f"{prefix}/internal-drafts/{REQUEST_ID}/draft.json": {
                "summary": "A verified internal draft.",
                "findings": [],
            },
        }

    def test_exact_read_uses_canonical_b2_before_gateway(self):
        b2 = _B2(self.objects)
        with patch.object(legalai, "_operator_regeneration_b2_client", return_value=(b2, "bucket")), patch.object(
            legalai, "_gateway_load_exact_draft_request"
        ) as gateway:
            result = legalai.load_exact_draft_request(CASE_ID, REQUEST_ID)
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["draft"]["summary"], "A verified internal draft.")
        gateway.assert_not_called()

    def test_list_read_uses_canonical_b2_before_gateway(self):
        b2 = _B2(self.objects)
        legalai.invalidate_draft_request_cache(CASE_ID)
        with patch.object(legalai, "_operator_regeneration_b2_client", return_value=(b2, "bucket")), patch.object(
            legalai, "_gateway_load_draft_requests"
        ) as gateway:
            result = legalai.load_draft_requests(CASE_ID, force_refresh=True)
        self.assertEqual([item["request_id"] for item in result], [REQUEST_ID])
        gateway.assert_not_called()


if __name__ == "__main__":
    unittest.main()
