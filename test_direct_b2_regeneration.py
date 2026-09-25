import io
import json
import unittest
from unittest.mock import patch

import app as legalai


CASE_ID = "NY-Nassau-613561-2026-Desousa-v-Rennick"
ORIGINAL_ID = "draft-1790275196-5d33f8a041c2"
REPLACEMENT_ID = "draft-1790292600-aabbccddeeff"


class _B2:
    def __init__(self):
        self.objects = {}

    def list_objects_v2(self, *, Bucket, Prefix, MaxKeys):
        return {"Contents": [{"Key": key} for key in self.objects if key.startswith(Prefix)]}

    def get_object(self, *, Bucket, Key):
        return {"Body": io.BytesIO(json.dumps(self.objects[Key]).encode("utf-8"))}

    def put_object(self, *, Bucket, Key, Body, ContentType, Metadata):
        self.objects[Key] = json.loads(Body.decode("utf-8"))


def _seed_ready_original(b2):
    b2.objects.update({
        f"cases/{CASE_ID}/derived/draft-requests/{ORIGINAL_ID}.json": {
            "schema_version": "legalai-draft-request.v1",
            "case_id": CASE_ID,
            "request_id": ORIGINAL_ID,
            "question": "Which motion should I consider?",
            "requested_by": "john",
            "created_at": 1790275196,
            "external_communication": False,
        },
        f"cases/{CASE_ID}/derived/internal-drafts/{ORIGINAL_ID}/status.json": {
            "status": "READY",
        },
        f"cases/{CASE_ID}/derived/internal-drafts/{ORIGINAL_ID}/draft.json": {
            "question": "Which motion should I consider?",
            "findings": [],
        },
    })


class DirectB2RegenerationTests(unittest.TestCase):
    def test_same_reviewer_gets_one_immutable_b2_replacement_without_gateway(self):
        b2 = _B2()
        _seed_ready_original(b2)
        with patch.object(legalai, "_operator_regeneration_b2_client", return_value=(b2, "bucket")), \
             patch.object(legalai, "_gateway_create_draft_request") as gateway, \
             patch.object(legalai.time, "time", return_value=1790292600), \
             patch.object(legalai.secrets, "token_hex", return_value="aabbccddeeff"):
            created = legalai.create_draft_request(
                CASE_ID, "untrusted replacement text", "john", regenerate_from=ORIGINAL_ID
            )
            repeated = legalai.create_draft_request(
                CASE_ID, "untrusted replacement text", "john", regenerate_from=ORIGINAL_ID
            )

        self.assertEqual(created, {"ok": True, "request_id": REPLACEMENT_ID, "reused": False})
        self.assertEqual(repeated, {"ok": True, "request_id": REPLACEMENT_ID, "reused": True})
        request = b2.objects[f"cases/{CASE_ID}/derived/draft-requests/{REPLACEMENT_ID}.json"]
        self.assertEqual(request["question"], "Which motion should I consider?")
        self.assertEqual(request["requested_by"], "john")
        self.assertEqual(request["regenerate_from_request_id"], ORIGINAL_ID)
        self.assertEqual(
            b2.objects[f"cases/{CASE_ID}/derived/internal-drafts/{REPLACEMENT_ID}/status.json"]["status"],
            "QUEUED",
        )
        gateway.assert_not_called()

    def test_cross_reviewer_cannot_fall_through_to_gateway(self):
        b2 = _B2()
        _seed_ready_original(b2)
        with patch.object(legalai, "_operator_regeneration_b2_client", return_value=(b2, "bucket")), \
             patch.object(legalai, "_gateway_create_draft_request") as gateway:
            blocked = legalai.create_draft_request(
                CASE_ID, "Which motion should I consider?", "someone-else",
                regenerate_from=ORIGINAL_ID,
            )
        self.assertIsNone(blocked)
        self.assertNotIn(
            f"cases/{CASE_ID}/derived/draft-requests/{REPLACEMENT_ID}.json", b2.objects
        )
        gateway.assert_not_called()

    def test_workspace_requires_explicit_paid_regeneration_confirmation(self):
        source = open(legalai.__file__, encoding="utf-8").read()
        self.assertIn("paid_regeneration_confirmation", source)
        self.assertIn("approve_paid_internal_replacement", source)


if __name__ == "__main__":
    unittest.main()
