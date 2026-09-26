import hashlib
import io
import json
import unittest
from unittest.mock import patch

from production_pdf_probe import run_probe


PDF = b"%PDF-1.4\nverified test PDF\n"
CASE = "NY-Nassau-613561-2026-Desousa-v-Rennick"
SOURCE = "a" * 64
NAME = "ORDER_TO_SHOW_CAUSE_32.pdf"
CONFIG = {"case_id": CASE, "source_sha256": SOURCE, "filename": NAME}
ENV = {
    "LEGALAI_REVIEW_ALLEN_USERNAME": "reviewer@example.com",
    "LEGALAI_REVIEW_ALLEN_PASSWORD": "test-password",
    "B2_ENDPOINT": "https://example.invalid",
    "B2_REGION": "us-west-1",
    "B2_KEY_ID": "test-id",
    "B2_APPLICATION_KEY": "test-key",
    "B2_BUCKET": "test-bucket",
}


class Response:
    status_code = 200
    mimetype = "application/pdf"

    def get_data(self):
        return PDF


class ProbeTests(unittest.TestCase):
    def test_authenticated_live_response_matches_canonical_manifest(self):
        manifest = {"files": [{"filename": "docket/" + NAME, "sha256": hashlib.sha256(PDF).hexdigest()}]}
        b2 = unittest.mock.Mock()
        b2.get_object.return_value = {"Body": io.BytesIO(json.dumps(manifest).encode())}
        app = unittest.mock.Mock()
        app.test_client.return_value.get.return_value = Response()
        with patch(
            "production_pdf_probe.boto3.client", return_value=b2
        ):
            result = run_probe(CONFIG, app, ENV)
        self.assertTrue(result["manifest_match"])
        self.assertEqual(result["http_status"], 200)
        self.assertNotIn(ENV["LEGALAI_REVIEW_ALLEN_PASSWORD"], json.dumps(result))
        self.assertTrue(app.test_client.return_value.get.call_args.kwargs["headers"]["Authorization"].startswith("Basic "))

    def test_mismatched_pdf_fails_closed(self):
        manifest = {"files": [{"filename": NAME, "sha256": "0" * 64}]}
        b2 = unittest.mock.Mock()
        b2.get_object.return_value = {"Body": io.BytesIO(json.dumps(manifest).encode())}
        app = unittest.mock.Mock()
        app.test_client.return_value.get.return_value = Response()
        with patch(
            "production_pdf_probe.boto3.client", return_value=b2
        ):
            with self.assertRaisesRegex(ValueError, "did not match"):
                run_probe(CONFIG, app, ENV)


if __name__ == "__main__":
    unittest.main()
