import email.message
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import app as legalai


class KuzmickiPdfLinkCheckTest(unittest.TestCase):
    def test_requires_scoped_token(self):
        with patch.dict(os.environ, {"KUZMICKI_PDF_VERIFY_TOKEN": "test-token"}):
            self.assertEqual(legalai.app.test_client().post("/internal/kuzmicki-pdf-link-check").status_code, 401)

    def test_requires_scoped_token_and_checks_all_six_exact_pdf_bytes(self):
        path = "/internal/kuzmicki-pdf-link-check"
        files = list(Path("../downloads").glob("151944_2017_Angela_Kuzmicki_v_Bentley_Yacht_Club_et_al_*.pdf"))
        if len(files) != 6:
            self.skipTest("local six-file source bundle unavailable")
        by_name = {file.name: file.read_bytes() for file in files}
        seen = []
        test_case = self

        class Response:
            status = 200
            headers = email.message.Message()
            headers.add_header("Content-Type", "application/pdf")

            def __init__(self, content): self.content = content
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, amount): return self.content[:amount]

        class Opener:
            def open(self, req, timeout):
                from urllib.parse import unquote, urlsplit
                self_name = unquote(urlsplit(req.full_url).path.rsplit("/", 1)[-1])
                seen.append(self_name)
                test_case.assertEqual(req.get_header("Authorization")[:6], "Basic ")
                return Response(by_name[self_name])

        with patch.dict(os.environ, {"KUZMICKI_PDF_VERIFY_TOKEN": "test-token",
                                      "LEGALAI_REVIEW_ALLEN_USERNAME": "reviewer@example.com",
                                      "LEGALAI_REVIEW_ALLEN_PASSWORD": "test-password"}):
            client = legalai.app.test_client()
            self.assertEqual(client.post(path).status_code, 401)
            with patch("app.urllib.request.build_opener", return_value=Opener()):
                response = client.post(path, headers={"X-Kuzmicki-Verify-Token": "test-token"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(seen), 6)
        self.assertTrue(all(item["verified"] for item in response.json["results"]))


if __name__ == "__main__":
    unittest.main()
