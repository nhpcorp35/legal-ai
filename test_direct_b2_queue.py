import io
import json
import unittest
from unittest.mock import patch

import app as legalai


CASE_ID = "NY-Nassau-613561-2026-Desousa-v-Rennick"


class _B2:
    def __init__(self):
        self.objects = {}

    def list_objects_v2(self, *, Bucket, Prefix, MaxKeys):
        return {"Contents": [{"Key": key} for key in self.objects if key.startswith(Prefix)]}

    def get_object(self, *, Bucket, Key):
        return {"Body": io.BytesIO(json.dumps(self.objects[Key]).encode("utf-8"))}

    def put_object(self, *, Bucket, Key, Body, ContentType, Metadata):
        self.objects[Key] = json.loads(Body.decode("utf-8"))


class DirectB2QueueTests(unittest.TestCase):
    def test_standard_request_is_queued_in_b2_without_gateway(self):
        b2 = _B2()
        with patch.object(legalai, "_operator_regeneration_b2_client", return_value=(b2, "bucket")), patch.object(
            legalai, "_gateway_create_draft_request"
        ) as gateway:
            created = legalai.create_draft_request(
                CASE_ID, "What motion should I consider?", "john"
            )
        self.assertTrue(created["ok"])
        self.assertFalse(created["reused"])
        gateway.assert_not_called()
        request_id = created["request_id"]
        request = b2.objects[f"cases/{CASE_ID}/derived/draft-requests/{request_id}.json"]
        status = b2.objects[f"cases/{CASE_ID}/derived/internal-drafts/{request_id}/status.json"]
        self.assertFalse(request["external_communication"])
        self.assertEqual(status["status"], "QUEUED")

    def test_temporary_test_is_cancelled_in_b2_without_gateway(self):
        b2 = _B2()
        request_id = "draft-1790275196-5d33f8a041c2"
        b2.objects.update({
            f"cases/{CASE_ID}/derived/draft-requests/{request_id}.json": {
                "schema_version": "legalai-draft-request.v1",
                "case_id": CASE_ID,
                "request_id": request_id,
                "question": "Is this a test?",
                "requested_by": "john",
                "created_at": 1790275196,
                "external_communication": False,
            },
            f"cases/{CASE_ID}/derived/internal-drafts/{request_id}/status.json": {
                "status": "QUEUED",
            },
        })
        with patch.object(legalai, "_operator_regeneration_b2_client", return_value=(b2, "bucket")), patch.object(
            legalai, "_gateway_discard_temporary_draft_request"
        ) as gateway:
            self.assertTrue(legalai.discard_temporary_draft_request(CASE_ID, request_id))
        self.assertEqual(
            b2.objects[f"cases/{CASE_ID}/derived/internal-drafts/{request_id}/status.json"]["status"],
            "CANCELLED",
        )
        gateway.assert_not_called()


if __name__ == "__main__":
    unittest.main()
