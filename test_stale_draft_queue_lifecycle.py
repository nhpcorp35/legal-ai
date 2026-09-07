"""Focused lifecycle bounds for stale attorney internal-draft QUEUED rows."""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import Mock, patch

import app as legalai


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _draft(
    *,
    request_id="draft-1000-aaaaaaaaaaaa",
    status="QUEUED",
    created_at=1_000,
    failure_code=None,
    question="What relief is requested?",
):
    return {
        "request_id": request_id,
        "question": question,
        "requested_by": "allen@example.com",
        "status": status,
        "created_at": created_at,
        "draft": None,
        "failure_code": failure_code,
    }


class StaleQueuedLifecycleHelpersTests(unittest.TestCase):
    def test_stale_queued_maps_to_retryable_failed(self):
        now = 1_000 + legalai.DEFAULT_STALE_QUEUED_AFTER_SECONDS
        stale = _draft(created_at=1_000)
        reconciled = legalai.reconcile_draft_request_lifecycle(stale, now=now)
        self.assertIsNot(reconciled, stale)
        self.assertEqual(reconciled["status"], "FAILED")
        self.assertEqual(reconciled["failure_code"], legalai.STALE_QUEUED_FAILURE_CODE)
        self.assertEqual(stale["status"], "QUEUED")

    def test_fresh_queued_running_and_ready_are_unchanged(self):
        now = 1_050
        for status in ("QUEUED", "RUNNING", "READY"):
            item = _draft(status=status, created_at=1_000)
            self.assertIs(legalai.reconcile_draft_request_lifecycle(item, now=now), item)
            self.assertEqual(item["status"], status)
            self.assertIsNone(item["failure_code"])

    def test_existing_failed_is_not_rewritten(self):
        item = _draft(status="FAILED", failure_code="valueerror", created_at=1)
        now = 1 + legalai.DEFAULT_STALE_QUEUED_AFTER_SECONDS * 2
        self.assertIs(legalai.reconcile_draft_request_lifecycle(item, now=now), item)
        self.assertEqual(item["failure_code"], "valueerror")


class StaleQueuedLoadAndMonitorTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {
                "LEGALAI_REVIEW_GATEWAY_URL": "https://gateway.example",
                "LEGALAI_REVIEW_GATEWAY_SECRET": "secret",
                "LEGALAI_STALE_QUEUED_AFTER_SECONDS": "600",
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        legalai._draft_alerted.clear()
        self.addCleanup(legalai._draft_alerted.clear)

    def test_load_draft_requests_reconciles_stale_queued_only(self):
        now = 10_000
        payload = {
            "requests": [
                _draft(
                    request_id="draft-1-aaaaaaaaaaaa",
                    status="QUEUED",
                    created_at=now - 601,
                    question="corpus",
                ),
                _draft(
                    request_id="draft-2-bbbbbbbbbbbb",
                    status="QUEUED",
                    created_at=now - 30,
                    question="fresh question",
                ),
                _draft(
                    request_id="draft-3-cccccccccccc",
                    status="RUNNING",
                    created_at=now - 900,
                    question="running question",
                ),
                _draft(
                    request_id="draft-4-dddddddddddd",
                    status="READY",
                    created_at=now - 900,
                    question="ready question",
                ),
            ]
        }
        with patch.object(
            legalai.urllib.request,
            "urlopen",
            return_value=_Response(payload),
        ), patch.object(legalai.time, "time", return_value=now):
            loaded = legalai.load_draft_requests(
                "NY-Nassau-608412-2024-Szymczyk-v-Szymczyk"
            )

        by_id = {item["request_id"]: item for item in loaded}
        self.assertEqual(by_id["draft-1-aaaaaaaaaaaa"]["status"], "FAILED")
        self.assertEqual(
            by_id["draft-1-aaaaaaaaaaaa"]["failure_code"],
            legalai.STALE_QUEUED_FAILURE_CODE,
        )
        self.assertEqual(by_id["draft-2-bbbbbbbbbbbb"]["status"], "QUEUED")
        self.assertIsNone(by_id["draft-2-bbbbbbbbbbbb"]["failure_code"])
        self.assertEqual(by_id["draft-3-cccccccccccc"]["status"], "RUNNING")
        self.assertEqual(by_id["draft-4-dddddddddddd"]["status"], "READY")

    def test_monitor_alerts_reconciled_stale_queued_without_redispatch(self):
        case_id = "NY-Nassau-608412-2024-Szymczyk-v-Szymczyk"
        stale = _draft(
            request_id="draft-1-aaaaaaaaaaaa",
            status="FAILED",
            failure_code=legalai.STALE_QUEUED_FAILURE_CODE,
            question="corpus",
        )
        alerts = []

        def _fake_timer(_delay, _fn):
            return Mock(start=lambda: None)

        with patch.object(
            legalai,
            "load_registered_cases",
            return_value=[{"case_id": case_id, "stage": "Verified source indexed"}],
        ), patch.object(
            legalai,
            "load_draft_requests",
            return_value=[stale],
        ), patch.object(
            legalai,
            "notify_operator_attention",
            side_effect=lambda kind, message: alerts.append((kind, message)) or True,
        ), patch.object(legalai.threading, "Timer", side_effect=_fake_timer):
            legalai._monitor_verified_draft_statuses()

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0][0], "decision")
        self.assertIn("failed", alerts[0][1])
        self.assertIn(legalai.STALE_QUEUED_FAILURE_CODE, alerts[0][1])
        self.assertIn(case_id, alerts[0][1])
        self.assertIn("draft-1-aaaaaaaaaaaa", alerts[0][1])


if __name__ == "__main__":
    unittest.main()
