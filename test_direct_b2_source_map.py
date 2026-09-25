import io
import json
import unittest
from unittest.mock import patch

import app as legalai


CASE_ID = "NY-Nassau-613561-2026-Desousa-v-Rennick"
SOURCE_SHA256 = "a" * 64


class _B2:
    def __init__(self, objects):
        self.objects = objects

    def get_object(self, *, Bucket, Key):
        value = self.objects[Key]
        raw = value if isinstance(value, bytes) else json.dumps(value).encode("utf-8")
        return {"Body": io.BytesIO(raw)}


class DirectB2SourceMapTests(unittest.TestCase):
    def test_source_map_reads_verified_page_index_without_gateway(self):
        prefix = f"cases/{CASE_ID}/intake"
        b2 = _B2({
            f"{prefix}/case_identity.json": {"source_sha256": SOURCE_SHA256},
            f"{prefix}/source_set.json": {
                "case_id": CASE_ID,
                "sources": [{"source_sha256": SOURCE_SHA256}],
            },
            f"{prefix}/source/{SOURCE_SHA256}/page_records.jsonl": (
                b'{"filename":"verified_filing.pdf","page_number":1,"text":"First verified page"}\n'
                b'{"filename":"verified_filing.pdf","page_number":2,"text":"Second verified page"}\n'
            ),
        })
        with patch.object(legalai, "_operator_regeneration_b2_client", return_value=(b2, "bucket")), \
             patch.object(legalai, "_gateway_load_case_source_map") as gateway:
            result = legalai.load_case_source_map(CASE_ID)
        self.assertEqual(result, [{
            "source_sha256": SOURCE_SHA256,
            "filename": "verified_filing.pdf",
            "pages": 2,
        }])
        gateway.assert_not_called()


if __name__ == "__main__":
    unittest.main()
