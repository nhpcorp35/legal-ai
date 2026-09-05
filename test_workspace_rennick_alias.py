import json
import os
import unittest
from unittest.mock import patch

import app as legalai


CANONICAL_ID = "NY-Nassau-613561-2026-Desousa-v-Rennick"
LEGACY_ID = "NY-Nassau-613561-2026-Rennick"


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class WorkspaceRennickAliasTests(unittest.TestCase):
    def test_legacy_placeholder_becomes_one_canonical_indexed_matter(self):
        payload = {
            "cases": [
                {"case_id": LEGACY_ID, "stage": "Intake stored"},
                {"case_id": CANONICAL_ID, "stage": "Verified source indexed"},
            ]
        }
        with patch.dict(
            os.environ,
            {"LEGALAI_REVIEW_GATEWAY_URL": "https://gateway.example", "LEGALAI_REVIEW_GATEWAY_SECRET": "secret"},
            clear=False,
        ), patch.object(legalai.urllib.request, "urlopen", return_value=_Response(payload)):
            self.assertEqual(
                legalai.load_registered_cases(),
                [{"case_id": CANONICAL_ID, "stage": "Verified source indexed"}],
            )

