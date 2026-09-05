import importlib.util
import io
import json
import os
import pathlib
import sys
import types
import unittest


sys.modules.setdefault("boto3", types.SimpleNamespace(client=None))
os.environ.setdefault("B2_BUCKET", "test-bucket")
MODULE_PATH = pathlib.Path(__file__).with_name("scripts") / "run_verified_case_draft.py"
SPEC = importlib.util.spec_from_file_location("verified_case_draft", MODULE_PATH)
WORKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WORKER)


class FakeS3:
    source = "a" * 64

    def get_object(self, **kwargs):
        if kwargs["Key"].endswith("case_identity.json"):
            return {"Body": io.BytesIO(json.dumps({"source_sha256": self.source}).encode())}
        if kwargs["Key"].endswith("source_set.json"):
            raise RuntimeError("legacy original-only source set")
        pages = [
            {"filename": "B Filing.pdf", "page_number": 2, "text": "Unusual record language without the request terms."},
            {"filename": "A Filing.pdf", "page_number": 1, "text": "Another verified page with OCR variation."},
        ]
        return {"Body": io.BytesIO(("\n".join(json.dumps(page) for page in pages)).encode())}


class EvidenceFallbackTests(unittest.TestCase):
    def test_uses_bounded_verified_fallback_when_no_terms_match(self):
        pages = WORKER.evidence(FakeS3(), "NY-Suffolk-600371-2021-DeSousa-v-Calvagno-II-Karcher", "What are the claims and defenses?")
        self.assertEqual([page["filename"] for page in pages], ["A Filing.pdf", "B Filing.pdf"])
        self.assertTrue(all(page["source_sha256"] == "a" * 64 for page in pages))


if __name__ == "__main__":
    unittest.main()
