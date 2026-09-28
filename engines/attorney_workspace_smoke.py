"""Bounded external HTTPS reads of the production attorney workspace.

This module has no app imports or write paths. It intentionally checks only
fixed URLs on the attorney site's public domain; callers cannot supply a URL.
"""

import base64
import urllib.error
import urllib.request


ORIGIN = "https://www.serverdeath.com"
RENNICK = "NY-Nassau-613561-2026-Desousa-v-Rennick"
CHECKS = (
    ("workspace", "/workspace", ("LegalAI Attorney Workspace", RENNICK)),
    (
        "review_packet",
        f"/workspace/matters/{RENNICK}/review-packet",
        ("Rennick Attorney Review Packet", "draft-1790275196-5d33f8a041c2", "draft-1790200223-c52acd236d81"),
    ),
    (
        "cited_case",
        f"/workspace/matters/{RENNICK}/cited-case/kuzmicki",
        ("Kuzmicki cited-case filings", "NYSCEF 27", "NYSCEF 53"),
    ),
)
MAX_HTML_BYTES = 2_000_000


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def run_check(username, password, *, opener=None, timeout=20):
    """Return statuses and marker names only; never return HTML or credentials."""
    if not username or not password:
        return {"ok": False, "error": "review_account_unavailable", "checks": []}
    opener = opener or urllib.request.build_opener(NoRedirect)
    authorization = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    results = []
    for name, path, markers in CHECKS:
        status = None
        found = []
        failure = None
        request = urllib.request.Request(
            ORIGIN + path,
            headers={"Authorization": "Basic " + authorization},
            method="GET",
        )
        try:
            with opener.open(request, timeout=timeout) as response:
                status = response.status
                mime = response.headers.get_content_type()
                body = response.read(MAX_HTML_BYTES + 1)
            if status != 200:
                failure = "http_status"
            elif mime != "text/html":
                failure = "content_type"
            elif len(body) > MAX_HTML_BYTES:
                failure = "response_too_large"
            else:
                page = body.decode("utf-8", errors="replace")
                found = [marker for marker in markers if marker.casefold() in page.casefold()]
                if len(found) != len(markers):
                    failure = "missing_markers"
        except urllib.error.HTTPError as exc:
            status = exc.code
            failure = "http_status"
        except (urllib.error.URLError, TimeoutError, ValueError):
            failure = "request_error"
        results.append({
            "name": name,
            "http_status": status,
            "verified": failure is None,
            "markers_found": found,
            "failure": failure,
        })
    return {"ok": all(item["verified"] for item in results), "checks": results}
