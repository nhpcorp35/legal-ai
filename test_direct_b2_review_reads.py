import io
import json
import unittest
from unittest.mock import patch

import app as legalai


CASE_ID = "NY-Nassau-613561-2026-Desousa-v-Rennick"
REQUEST_ID = "draft-1790275196-5d33f8a041c2"


class _B2:
    def __init__(self, records):
        self.records = records

    def list_objects_v2(self, *, Bucket, Prefix, MaxKeys):
        return {"Contents": [{"Key": key} for key in self.records if key.startswith(Prefix)]}

    def get_object(self, *, Bucket, Key):
        return {"Body": io.BytesIO(json.dumps(self.records[Key]).encode("utf-8"))}


class DirectB2ReviewReadTests(unittest.TestCase):
    def test_review_is_loaded_from_canonical_b2_without_volume_fallback(self):
        key = f"cases/{CASE_ID}/derived/attorney-feedback/{REQUEST_ID}/1-deadbeef.json"
        b2 = _B2({key: {
            "reviewer": "john",
            "case_id": CASE_ID,
            "request_id": REQUEST_ID,
            "decision": "needs_revision",
            "accuracy_rating": 2,
            "usefulness_rating": 2,
        }})
        with patch.object(legalai, "_operator_regeneration_b2_client", return_value=(b2, "bucket")), patch.object(
            legalai, "_volume_load_draft_review_feedbacks"
        ) as volume:
            records = legalai.load_draft_review_feedbacks("john", CASE_ID, (REQUEST_ID,))
        self.assertEqual(records[REQUEST_ID]["decision"], "needs_revision")
        volume.assert_not_called()


if __name__ == "__main__":
    unittest.main()
