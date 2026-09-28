import io
import urllib.error
import unittest
from unittest.mock import patch

import app as web
from engines.attorney_workspace_smoke import CHECKS, run_check


class FakeResponse:
    status = 200

    def __init__(self, body, mime="text/html"):
        self.body = io.BytesIO(body)
        self.headers = type("Headers", (), {"get_content_type": lambda self: mime})()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, count):
        return self.body.read(count)


class FakeOpener:
    def __init__(self, pages):
        self.pages = pages
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        path = request.full_url.removeprefix("https://www.serverdeath.com")
        page = self.pages[path]
        if isinstance(page, Exception):
            raise page
        return FakeResponse(page)


class AttorneyWorkspaceSmokeTests(unittest.TestCase):
    def test_fixed_read_only_requests_and_bounded_output(self):
        pages = {path: " ".join(markers).encode() for _name, path, markers in CHECKS}
        opener = FakeOpener(pages)
        result = run_check("reviewer@example.com", "secret", opener=opener)
        self.assertTrue(result["ok"])
        self.assertEqual(len(opener.requests), 3)
        for index, (request, timeout) in enumerate(opener.requests):
            self.assertEqual(request.get_method(), "GET")
            self.assertTrue(request.full_url.startswith("https://www.serverdeath.com/workspace"))
            self.assertEqual(timeout, 45 if index == 0 else 20)
        self.assertNotIn("secret", str(result))
        self.assertNotIn("reviewer@example.com", str(result))
        self.assertNotIn("<html", str(result))

    def test_missing_page_marker_and_401_are_failures(self):
        pages = {path: " ".join(markers).encode() for _name, path, markers in CHECKS}
        pages[CHECKS[1][1]] = b"Rennick Attorney Review Packet"
        pages[CHECKS[2][1]] = urllib.error.HTTPError("url", 401, "unauthorized", {}, None)
        result = run_check("reviewer@example.com", "secret", opener=FakeOpener(pages))
        self.assertFalse(result["ok"])
        self.assertEqual(result["checks"][1]["failure"], "missing_markers")
        self.assertEqual(result["checks"][2]["http_status"], 401)

    def test_route_requires_token_and_starts_async_read_only_check(self):
        web._workspace_smoke_state = None
        threads = []

        class DeferredThread:
            def __init__(self, **kwargs):
                threads.append(self)
                self.target = kwargs["target"]
                self.args = kwargs["args"]

            def start(self):
                pass

        with patch.dict(web.os.environ, {
            "LEGALAI_WORKSPACE_SMOKE_TOKEN": "check-token",
            "LEGALAI_REVIEW_ALLEN_USERNAME": "reviewer@example.com",
            "LEGALAI_REVIEW_ALLEN_PASSWORD": "secret",
        }), patch.object(web.threading, "Thread", DeferredThread), patch.object(
            web, "run_attorney_workspace_smoke", return_value={"ok": True, "checks": []}
        ) as checker:
            client = web.app.test_client()
            self.assertEqual(client.post("/internal/attorney-workspace-smoke").status_code, 401)
            response = client.post(
                "/internal/attorney-workspace-smoke",
                headers={"X-Workspace-Smoke-Token": "check-token"},
            )
            self.assertEqual(response.status_code, 202)
            run_id = response.json["run_id"]
            pending = client.get(
                "/internal/attorney-workspace-smoke?run_id=" + run_id,
                headers={"X-Workspace-Smoke-Token": "check-token"},
            )
            self.assertEqual(pending.json["status"], "RUNNING")
            threads[0].target(*threads[0].args)
            finished = client.get(
                "/internal/attorney-workspace-smoke?run_id=" + run_id,
                headers={"X-Workspace-Smoke-Token": "check-token"},
            )
            self.assertEqual(finished.json["status"], "DONE")
            checker.assert_called_once_with(
                "reviewer@example.com", "secret", timeout=20, workspace_timeout=45
            )
            self.assertNotIn("secret", finished.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
