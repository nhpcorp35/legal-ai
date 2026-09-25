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

    def get_object(self, *, Bucket, Key):
        return {"Body": io.BytesIO(json.dumps(self.objects[Key]).encode("utf-8"))}


class DirectB2DraftAuditTests(unittest.TestCase):
    def test_input_audit_reads_canonical_b2_without_gateway(self):
        prefix = f"cases/{CASE_ID}/derived"
        b2 = _B2({
            f"{prefix}/draft-requests/{REQUEST_ID}.json": {
                "schema_version": "legalai-draft-request.v1",
                "case_id": CASE_ID,
                "external_communication": False,
                "question": "Which motion should I consider?",
                "requested_by": "john",
                "created_at": 1790275196,
            },
            f"{prefix}/internal-drafts/{REQUEST_ID}/status.json": {"status": "READY"},
            f"{prefix}/internal-drafts/{REQUEST_ID}/input_audit.json": {
                "retrieval_citations": [{"filename": "verified.pdf", "page_number": 3}],
                "legal_authorities": [{
                    "authority_id": "ny-cplr-6301",
                    "citation": "CPLR 6301",
                    "title": "Preliminary injunction",
                    "source_url": "https://www.nysenate.gov/legislation/laws/CVP/6301",
                    "issuing_body": "New York Legislature",
                    "date": "current",
                    "sha256": "a" * 64,
                }],
                "coverage": {"verified_pleading_inventory": []},
            },
        })
        with patch.object(legalai, "_operator_regeneration_b2_client", return_value=(b2, "bucket")), \
             patch.object(legalai, "_gateway_load_draft_input_audit") as gateway:
            result = legalai.load_draft_input_audit(CASE_ID, REQUEST_ID)
        self.assertEqual(result["requested_by"], "john")
        self.assertEqual(result["citations"][0]["page_number"], 3)
        self.assertEqual(result["legal_authorities"][0]["authority_id"], "ny-cplr-6301")
        gateway.assert_not_called()


if __name__ == "__main__":
    unittest.main()
