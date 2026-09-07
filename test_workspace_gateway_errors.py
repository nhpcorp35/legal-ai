"""Gateway unavailable handling for registered cases and packet loads."""

from __future__ import annotations

import base64
import json
import os
import unittest
import urllib.error
from unittest.mock import patch

import app as legalai


CASE_ID = "NY-Nassau-613561-2026-Desousa-v-Rennick"


class _Response:
    def __init__(self, payload, *, raw=None):
        self.payload = payload
        self.raw = raw

    def read(self):
        if self.raw is not None:
            return self.raw
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _auth_headers():
    token = base64.b64encode(b"allen@example.com:secret").decode("ascii")
    return {"Authorization": f"Basic {token}"}


class GatewayRegisteredCasesTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {
                "LEGALAI_REVIEW_GATEWAY_URL": "https://gateway.example",
                "LEGALAI_REVIEW_GATEWAY_SECRET": "secret",
                "LEGALAI_REVIEW_USERS_JSON": '{"allen@example.com":"secret"}',
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_legitimate_empty_case_list_is_success(self):
        with patch.object(
            legalai.urllib.request,
            "urlopen",
            return_value=_Response({"cases": []}),
        ):
            self.assertEqual(legalai.load_registered_cases(), [])

    def test_gateway_transport_failure_is_explicit_unavailable(self):
        with patch.object(
            legalai.urllib.request,
            "urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            with self.assertRaises(legalai.GatewayUnavailableError) as ctx:
                legalai.load_registered_cases()
        message = str(ctx.exception)
        self.assertEqual(message, legalai.GatewayUnavailableError.DEFAULT_MESSAGE)
        self.assertNotIn("secret", message.casefold())
        self.assertNotIn("connection refused", message)

    def test_partial_gateway_config_is_explicit_error(self):
        with patch.dict(
            os.environ,
            {"LEGALAI_REVIEW_GATEWAY_URL": "https://gateway.example", "LEGALAI_REVIEW_GATEWAY_SECRET": ""},
            clear=False,
        ):
            with self.assertRaises(legalai.GatewayUnavailableError) as ctx:
                legalai.load_registered_cases()
        self.assertEqual(str(ctx.exception), legalai.GatewayUnavailableError.CONFIG_MESSAGE)

    def test_invalid_cases_payload_is_unavailable_not_empty_success(self):
        with patch.object(
            legalai.urllib.request,
            "urlopen",
            return_value=_Response({"cases": "not-a-list"}),
        ):
            with self.assertRaises(legalai.GatewayUnavailableError):
                legalai.load_registered_cases()

    def test_workspace_surfaces_gateway_error_not_empty_success(self):
        with patch.object(
            legalai,
            "load_registered_cases",
            side_effect=legalai.GatewayUnavailableError(),
        ), patch.object(
            legalai,
            "available_case00_review_questions",
            return_value=[],
        ), patch.object(
            legalai,
            "load_szymczyk_review_packet",
            return_value=None,
        ):
            response = legalai.app.test_client().get("/workspace", headers=_auth_headers())
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Review gateway unavailable", body)
        self.assertIn(legalai.GatewayUnavailableError.DEFAULT_MESSAGE, body)
        self.assertNotIn("No prepared matters are available", body)
        self.assertNotIn("secret", body.casefold())


class GatewayPacketLoadTests(unittest.TestCase):
    def setUp(self):
        legalai.load_case00_review_packet.cache_clear()
        self.env = patch.dict(
            os.environ,
            {
                "LEGALAI_REVIEW_GATEWAY_URL": "https://gateway.example",
                "LEGALAI_REVIEW_GATEWAY_SECRET": "secret",
                "LEGALAI_CASE00_Q1_PACKET_B64": "",
                "LEGALAI_CASE00_Q1_PACKET_SHA256": "",
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(legalai.load_case00_review_packet.cache_clear)

    def test_packet_missing_after_successful_gateway_lookup(self):
        with patch.object(
            legalai.urllib.request,
            "urlopen",
            return_value=_Response({"ok": True}),
        ):
            self.assertIsNone(legalai.load_case00_review_packet("Q1"))

    def test_packet_gateway_failure_is_explicit_unavailable(self):
        with patch.object(
            legalai.urllib.request,
            "urlopen",
            side_effect=urllib.error.HTTPError(
                "https://gateway.example/portal/case-00/q1/packet",
                503,
                "Service Unavailable",
                hdrs=None,
                fp=None,
            ),
        ):
            with self.assertRaises(legalai.GatewayUnavailableError) as ctx:
                legalai.load_case00_review_packet("Q1")
        message = str(ctx.exception)
        self.assertEqual(message, legalai.GatewayUnavailableError.DEFAULT_MESSAGE)
        self.assertNotIn("secret", message.casefold())

    def test_unconfigured_gateway_without_legacy_packet_is_missing(self):
        with patch.dict(
            os.environ,
            {
                "LEGALAI_REVIEW_GATEWAY_URL": "",
                "LEGALAI_REVIEW_GATEWAY_SECRET": "",
                "LEGALAI_CASE00_Q1_PACKET_B64": "",
                "LEGALAI_CASE00_Q1_PACKET_SHA256": "",
            },
            clear=False,
        ):
            self.assertIsNone(legalai.load_case00_review_packet("Q1"))


if __name__ == "__main__":
    unittest.main()
