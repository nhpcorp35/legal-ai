import base64
import os
import unittest
from unittest.mock import patch

import app as legalai


CASE_ID = "NY-Nassau-613561-2026-Desousa-v-Rennick"
SOURCE_SHA256 = "a" * 64


def _auth_headers():
    token = base64.b64encode(b"allen@example.com:secret").decode("ascii")
    return {"Authorization": f"Basic {token}"}


class WorkspaceSourceCitationTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(
            os.environ, {"LEGALAI_REVIEW_USERS_JSON": '{"allen@example.com":"secret"}'}, clear=False
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_verified_source_map_preserves_source_identity(self):
        with patch.object(legalai, "load_registered_cases", return_value=[{"case_id": CASE_ID, "stage": "Verified source indexed"}]), patch.object(
            legalai, "load_case_source_map", return_value=[{"source_sha256": SOURCE_SHA256, "filename": "Record.pdf", "pages": 2}]
        ):
            response = legalai.app.test_client().get(
                f"/workspace/matters/{CASE_ID}/sources", headers=_auth_headers()
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn(f"source_sha256={SOURCE_SHA256}", response.get_data(as_text=True))

    def test_verified_pdf_requires_and_forwards_the_cited_source(self):
        seen = {}

        def fake_open(case_id, source_sha256, filename):
            seen.update(case_id=case_id, source_sha256=source_sha256, filename=filename)
            return b"%PDF-1.4\n"

        with patch.object(legalai, "load_registered_cases", return_value=[{"case_id": CASE_ID, "stage": "Verified source indexed"}]), patch.object(
            legalai, "open_indexed_case_pdf", side_effect=fake_open
        ):
            client = legalai.app.test_client()
            response = client.get(
                f"/workspace/matters/{CASE_ID}/pdf/Record.pdf?source_sha256={SOURCE_SHA256}",
                headers=_auth_headers(),
            )
            missing = client.get(
                f"/workspace/matters/{CASE_ID}/pdf/Record.pdf", headers=_auth_headers()
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(seen, {"case_id": CASE_ID, "source_sha256": SOURCE_SHA256, "filename": "Record.pdf"})
        self.assertEqual(missing.status_code, 404)
