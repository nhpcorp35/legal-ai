import io
import json
import unittest
from unittest.mock import patch

import app as legalai


CASE_ID = "NY-Nassau-613561-2026-Desousa-v-Rennick"
SOURCE_SHA256 = "b" * 64


class _B2:
    def __init__(self, objects):
        self.objects = objects

    def get_object(self, *, Bucket, Key):
        value = self.objects[Key]
        raw = value if isinstance(value, bytes) else json.dumps(value).encode("utf-8")
        return {"Body": io.BytesIO(raw)}


class DirectB2VerifiedSearchTests(unittest.TestCase):
    def test_verified_search_reads_page_index_without_gateway(self):
        prefix = f"cases/{CASE_ID}/intake"
        b2 = _B2({
            f"{prefix}/case_identity.json": {"source_sha256": SOURCE_SHA256},
            f"{prefix}/source/{SOURCE_SHA256}/page_records.jsonl": (
                b'{"filename":"verified_filing.pdf","page_number":1,"text":"The request concerns a preliminary injunction."}\n'
                b'{"filename":"verified_filing.pdf","page_number":2,"text":"Unrelated verified record text."}\n'
            ),
        })
        with patch.object(legalai, "_operator_regeneration_b2_client", return_value=(b2, "bucket")), \
             patch.object(legalai, "_gateway_search_indexed_case") as gateway:
            result = legalai.search_indexed_case(CASE_ID, "preliminary injunction")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["filename"], "verified_filing.pdf")
        self.assertEqual(result[0]["page_number"], 1)
        self.assertIn("preliminary injunction", result[0]["snippet"].lower())
        gateway.assert_not_called()


if __name__ == "__main__":
    unittest.main()
