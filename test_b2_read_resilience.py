"""Focused tests for bounded B2 read retry / atomic download helpers."""

from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from unittest.mock import MagicMock

from botocore.exceptions import ClientError, ConnectTimeoutError, ReadTimeoutError


def _load_cli():
    path = Path(__file__).resolve().parent / "scripts" / "rebuild_case00_derived.py"
    spec = importlib.util.spec_from_file_location("rebuild_case00_derived_retry", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    repo_root = Path(__file__).resolve().parent
    if str(repo_root) not in os.sys.path:
        os.sys.path.insert(0, str(repo_root))
    os.sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


CLI = _load_cli()


def _client_error(
    http_status: int,
    code: str | None = None,
    operation: str = "HeadObject",
    retry_after: str | None = None,
):
    error_code = code if code is not None else str(http_status)
    headers = {}
    if retry_after is not None:
        headers["retry-after"] = retry_after
    return ClientError(
        {
            "Error": {"Code": error_code, "Message": f"status {http_status}"},
            "ResponseMetadata": {
                "HTTPStatusCode": http_status,
                "HTTPHeaders": headers,
            },
        },
        operation,
    )


class B2ReadRetryHelperTests(unittest.TestCase):
    def test_default_base_delay_matches_backblaze_guidance(self) -> None:
        self.assertEqual(CLI.DEFAULT_B2_READ_BASE_DELAY_SEC, 1.0)
        self.assertEqual(CLI.DEFAULT_B2_READ_MAX_DELAY_SEC, 2.0)
        self.assertEqual(CLI.DEFAULT_B2_READ_MAX_ATTEMPTS, 5)

    def test_eventual_503_recovery(self) -> None:
        calls = {"n": 0}
        sleeps: list[float] = []

        def operation():
            calls["n"] += 1
            if calls["n"] < 3:
                raise _client_error(503, "503")
            return {"ok": True}

        result = CLI.call_b2_with_read_retry(
            operation,
            max_attempts=5,
            base_delay_sec=0.5,
            max_delay_sec=2.0,
            sleep=sleeps.append,
            rand=lambda: 1.0,
        )
        self.assertEqual(result, {"ok": True})
        self.assertEqual(calls["n"], 3)
        self.assertEqual(len(sleeps), 2)
        self.assertEqual(sleeps[0], 0.5)
        self.assertEqual(sleeps[1], 1.0)

    def test_retry_exhaustion_raises_last_transient_error(self) -> None:
        calls = {"n": 0}
        sleeps: list[float] = []

        def operation():
            calls["n"] += 1
            raise _client_error(503, "ServiceUnavailable")

        with self.assertRaises(ClientError) as ctx:
            CLI.call_b2_with_read_retry(
                operation,
                max_attempts=3,
                base_delay_sec=0.25,
                max_delay_sec=1.0,
                sleep=sleeps.append,
                rand=lambda: 0.0,
            )
        self.assertEqual(CLI._client_error_http_status(ctx.exception), 503)
        self.assertEqual(calls["n"], 3)
        self.assertEqual(len(sleeps), 2)

    def test_nonretryable_401_403_404(self) -> None:
        for status, code in (
            (401, "Unauthorized"),
            (403, "AccessDenied"),
            (404, "404"),
            (404, "NoSuchKey"),
            (404, "NotFound"),
        ):
            calls = {"n": 0}
            sleeps: list[float] = []

            def operation(status=status, code=code):
                calls["n"] += 1
                raise _client_error(status, code)

            with self.assertRaises(ClientError):
                CLI.call_b2_with_read_retry(
                    operation,
                    max_attempts=5,
                    sleep=sleeps.append,
                    rand=lambda: 1.0,
                )
            self.assertEqual(calls["n"], 1, msg=f"status={status} code={code}")
            self.assertEqual(sleeps, [], msg=f"status={status} code={code}")

    def test_timeout_recovery(self) -> None:
        calls = {"n": 0}
        sleeps: list[float] = []

        def operation():
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectTimeoutError(endpoint_url="https://example.invalid")
            if calls["n"] == 2:
                raise ReadTimeoutError(endpoint_url="https://example.invalid")
            return "recovered"

        result = CLI.call_b2_with_read_retry(
            operation,
            max_attempts=4,
            base_delay_sec=0.1,
            max_delay_sec=1.0,
            sleep=sleeps.append,
            rand=lambda: 0.5,
        )
        self.assertEqual(result, "recovered")
        self.assertEqual(calls["n"], 3)
        self.assertEqual(len(sleeps), 2)

    def test_deterministic_attempt_counts_and_backoff_cap(self) -> None:
        calls = {"n": 0}
        sleeps: list[float] = []

        def operation():
            calls["n"] += 1
            raise _client_error(429, "SlowDown")

        with self.assertRaises(ClientError):
            CLI.call_b2_with_read_retry(
                operation,
                max_attempts=4,
                base_delay_sec=1.0,
                max_delay_sec=2.0,
                sleep=sleeps.append,
                rand=lambda: 1.0,
            )
        self.assertEqual(calls["n"], 4)
        # delays: min(1,2)=1, min(2,2)=2, min(4,2)=2  (before jitter; jitter=1.0)
        self.assertEqual(sleeps, [1.0, 2.0, 2.0])

    def test_successful_behavior_unchanged_no_sleep(self) -> None:
        sleeps: list[float] = []
        result = CLI.call_b2_with_read_retry(
            lambda: 42,
            max_attempts=5,
            sleep=sleeps.append,
            rand=lambda: 1.0,
        )
        self.assertEqual(result, 42)
        self.assertEqual(sleeps, [])


class B2RetryAfterPolicyTests(unittest.TestCase):
    def test_retry_after_present_honored_without_jitter(self) -> None:
        calls = {"n": 0}
        sleeps: list[float] = []

        def operation():
            calls["n"] += 1
            if calls["n"] == 1:
                raise _client_error(503, "503", retry_after="2")
            return "ok"

        result = CLI.call_b2_with_read_retry(
            operation,
            max_attempts=3,
            base_delay_sec=1.0,
            max_delay_sec=2.0,
            sleep=sleeps.append,
            # Full jitter would otherwise collapse the delay to 0.
            rand=lambda: 0.0,
        )
        self.assertEqual(result, "ok")
        self.assertEqual(calls["n"], 2)
        self.assertEqual(sleeps, [2.0])

    def test_retry_after_absent_uses_bounded_exponential_jitter(self) -> None:
        calls = {"n": 0}
        sleeps: list[float] = []

        def operation():
            calls["n"] += 1
            if calls["n"] == 1:
                raise _client_error(503, "503")
            return "ok"

        result = CLI.call_b2_with_read_retry(
            operation,
            max_attempts=3,
            base_delay_sec=1.0,
            max_delay_sec=2.0,
            sleep=sleeps.append,
            rand=lambda: 0.5,
        )
        self.assertEqual(result, "ok")
        self.assertEqual(sleeps, [0.5])

    def test_retry_after_zero_sleeps_zero(self) -> None:
        calls = {"n": 0}
        sleeps: list[float] = []

        def operation():
            calls["n"] += 1
            if calls["n"] == 1:
                raise _client_error(429, "SlowDown", retry_after="0")
            return "ok"

        result = CLI.call_b2_with_read_retry(
            operation,
            max_attempts=3,
            base_delay_sec=1.0,
            max_delay_sec=2.0,
            sleep=sleeps.append,
            rand=lambda: 1.0,
        )
        self.assertEqual(result, "ok")
        self.assertEqual(sleeps, [0.0])

    def test_retry_after_malformed_falls_back_to_exponential(self) -> None:
        for bad in ("not-a-delay", "1.5", "", " "):
            calls = {"n": 0}
            sleeps: list[float] = []

            def operation(bad=bad):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise _client_error(503, "503", retry_after=bad)
                return "ok"

            result = CLI.call_b2_with_read_retry(
                operation,
                max_attempts=3,
                base_delay_sec=1.0,
                max_delay_sec=2.0,
                sleep=sleeps.append,
                rand=lambda: 1.0,
            )
            self.assertEqual(result, "ok", msg=bad)
            self.assertEqual(sleeps, [1.0], msg=bad)

    def test_retry_after_negative_falls_back_to_exponential(self) -> None:
        calls = {"n": 0}
        sleeps: list[float] = []

        def operation():
            calls["n"] += 1
            if calls["n"] == 1:
                raise _client_error(500, "500", retry_after="-3")
            return "ok"

        result = CLI.call_b2_with_read_retry(
            operation,
            max_attempts=3,
            base_delay_sec=1.0,
            max_delay_sec=2.0,
            sleep=sleeps.append,
            rand=lambda: 1.0,
        )
        self.assertEqual(result, "ok")
        self.assertEqual(sleeps, [1.0])

    def test_retry_after_over_cap_falls_back_to_bounded_exponential(self) -> None:
        calls = {"n": 0}
        sleeps: list[float] = []

        def operation():
            calls["n"] += 1
            if calls["n"] == 1:
                raise _client_error(503, "503", retry_after="30")
            return "ok"

        result = CLI.call_b2_with_read_retry(
            operation,
            max_attempts=3,
            base_delay_sec=1.0,
            max_delay_sec=2.0,
            sleep=sleeps.append,
            rand=lambda: 1.0,
        )
        self.assertEqual(result, "ok")
        # Over-cap Retry-After must not sleep 30s; use capped exponential instead.
        self.assertEqual(sleeps, [1.0])
        self.assertTrue(all(s <= 2.0 for s in sleeps))

    def test_retry_after_eventual_success_across_statuses(self) -> None:
        statuses = [429, 500, 502, 503, 504]
        calls = {"n": 0}
        sleeps: list[float] = []

        def operation():
            calls["n"] += 1
            if calls["n"] <= len(statuses):
                raise _client_error(
                    statuses[calls["n"] - 1],
                    str(statuses[calls["n"] - 1]),
                    retry_after="1",
                )
            return {"recovered": True}

        result = CLI.call_b2_with_read_retry(
            operation,
            max_attempts=6,
            base_delay_sec=1.0,
            max_delay_sec=2.0,
            sleep=sleeps.append,
            rand=lambda: 0.0,
        )
        self.assertEqual(result, {"recovered": True})
        self.assertEqual(calls["n"], 6)
        self.assertEqual(sleeps, [1.0, 1.0, 1.0, 1.0, 1.0])

    def test_retry_after_exhaustion_preserves_attempt_count(self) -> None:
        calls = {"n": 0}
        sleeps: list[float] = []

        def operation():
            calls["n"] += 1
            raise _client_error(503, "503", retry_after="1")

        with self.assertRaises(ClientError) as ctx:
            CLI.call_b2_with_read_retry(
                operation,
                max_attempts=4,
                base_delay_sec=1.0,
                max_delay_sec=2.0,
                sleep=sleeps.append,
                rand=lambda: 0.0,
            )
        self.assertEqual(CLI._client_error_http_status(ctx.exception), 503)
        self.assertEqual(calls["n"], 4)
        self.assertEqual(sleeps, [1.0, 1.0, 1.0])

    def test_retry_after_http_date_with_injectable_clock(self) -> None:
        # HTTP-date support uses stdlib email.utils.parsedate_to_datetime.
        fixed_now = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        retry_at = datetime(2024, 1, 1, 0, 0, 2, tzinfo=timezone.utc)
        header = format_datetime(retry_at, usegmt=True)
        calls = {"n": 0}
        sleeps: list[float] = []

        def operation():
            calls["n"] += 1
            if calls["n"] == 1:
                raise _client_error(503, "503", retry_after=header)
            return "ok"

        result = CLI.call_b2_with_read_retry(
            operation,
            max_attempts=3,
            base_delay_sec=1.0,
            max_delay_sec=2.0,
            sleep=sleeps.append,
            rand=lambda: 0.0,
            now=lambda: fixed_now.timestamp(),
        )
        self.assertEqual(result, "ok")
        self.assertEqual(sleeps, [2.0])

    def test_retry_after_does_not_apply_to_401_403_404(self) -> None:
        for status, code in (
            (401, "Unauthorized"),
            (403, "AccessDenied"),
            (404, "NoSuchKey"),
        ):
            calls = {"n": 0}
            sleeps: list[float] = []

            def operation(status=status, code=code):
                calls["n"] += 1
                raise _client_error(status, code, retry_after="5")

            with self.assertRaises(ClientError):
                CLI.call_b2_with_read_retry(
                    operation,
                    max_attempts=5,
                    sleep=sleeps.append,
                    rand=lambda: 1.0,
                )
            self.assertEqual(calls["n"], 1, msg=status)
            self.assertEqual(sleeps, [], msg=status)

    def test_parse_retry_after_rejects_malformed_and_parses_delta(self) -> None:
        self.assertEqual(CLI.parse_retry_after_delay_sec("7"), 7.0)
        self.assertEqual(CLI.parse_retry_after_delay_sec("0"), 0.0)
        self.assertEqual(CLI.parse_retry_after_delay_sec("-2"), -2.0)
        self.assertIsNone(CLI.parse_retry_after_delay_sec("nope"))
        self.assertIsNone(CLI.parse_retry_after_delay_sec("1.5"))


class B2AtomicDownloadTests(unittest.TestCase):
    def test_partial_file_cleanup_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "cache" / "artifact.json"
            dest.parent.mkdir(parents=True)
            # Pre-existing valid cache object must remain untouched on failure.
            dest.write_text('{"valid": true}\n', encoding="utf-8")
            before = dest.read_text(encoding="utf-8")

            client = MagicMock()

            def failing_download(bucket, key, filename):
                Path(filename).write_bytes(b'{"partial": true}')
                raise _client_error(503, "503", operation="GetObject")

            client.download_file.side_effect = failing_download
            sleeps: list[float] = []

            with self.assertRaises(ClientError):
                CLI.download_b2_file(
                    client,
                    "legalai-corpus",
                    "prefix/artifact.json",
                    dest,
                    max_attempts=2,
                    base_delay_sec=0.1,
                    max_delay_sec=1.0,
                    sleep=sleeps.append,
                    rand=lambda: 0.0,
                )

            self.assertEqual(dest.read_text(encoding="utf-8"), before)
            leftovers = list(dest.parent.glob(".artifact.json.*.partial"))
            self.assertEqual(leftovers, [])
            self.assertEqual(client.download_file.call_count, 2)

    def test_download_eventual_503_recovery_atomic_replace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "derived" / "case_map.json"
            client = MagicMock()
            attempts = {"n": 0}

            def flaky_download(bucket, key, filename):
                attempts["n"] += 1
                path = Path(filename)
                if attempts["n"] == 1:
                    path.write_bytes(b"PARTIAL")
                    raise _client_error(503, "503", operation="GetObject")
                path.write_bytes(b'{"case_map": {}}\n')

            client.download_file.side_effect = flaky_download
            sleeps: list[float] = []

            result = CLI.download_b2_file(
                client,
                "legalai-corpus",
                "cache/case_map.json",
                dest,
                max_attempts=3,
                sleep=sleeps.append,
                rand=lambda: 0.0,
            )
            self.assertEqual(result, dest)
            self.assertEqual(dest.read_bytes(), b'{"case_map": {}}\n')
            self.assertEqual(attempts["n"], 2)
            self.assertEqual(len(sleeps), 1)
            self.assertEqual(list(dest.parent.glob(".case_map.json.*.partial")), [])

    def test_head_b2_object_retries_transient_then_succeeds(self) -> None:
        client = MagicMock()
        client.head_object.side_effect = [
            _client_error(503, "503"),
            {"ContentLength": 12, "ETag": '"abc"'},
        ]
        sleeps: list[float] = []
        head = CLI.head_b2_object(
            client,
            "legalai-corpus",
            "obj-key",
            max_attempts=3,
            sleep=sleeps.append,
            rand=lambda: 0.0,
        )
        self.assertEqual(head["ContentLength"], 12)
        self.assertEqual(client.head_object.call_count, 2)
        self.assertEqual(len(sleeps), 1)

    def test_materialize_uses_atomic_download_helper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest_dir = Path(tmp) / "pdfs"
            prefix = "Benchmarks/Case-00/original/"
            key = prefix + "doc.pdf"
            payload = b"%PDF-1.4 fixture"
            client = MagicMock()
            client.list_objects_v2.return_value = {
                "Contents": [{"Key": key}],
                "IsTruncated": False,
            }

            def fake_download(bucket, object_key, filename_path):
                Path(filename_path).write_bytes(payload)

            client.download_file.side_effect = fake_download
            config = CLI.B2Config.from_env(
                {
                    "B2_KEY_ID": "key-id-secret-value",
                    "B2_APPLICATION_KEY": "app-key-secret-value",
                    "B2_BUCKET": "legalai-corpus",
                    "B2_ENDPOINT": "https://s3.us-east-005.backblazeb2.com",
                    "B2_REGION": "us-east-005",
                }
            )
            sleeps: list[float] = []
            CLI.materialize_b2_prefix(
                prefix,
                dest_dir,
                client=client,
                config=config,
                sleep=sleeps.append,
                rand=lambda: 1.0,
            )
            local = dest_dir / "doc.pdf"
            self.assertTrue(local.is_file())
            self.assertEqual(local.read_bytes(), payload)
            self.assertEqual(sleeps, [])
            client.download_file.assert_called_once()
            # Final destination must not be the direct download target (partial path).
            downloaded_to = Path(client.download_file.call_args.args[2])
            self.assertNotEqual(downloaded_to, local)
            self.assertTrue(str(downloaded_to).endswith(".partial"))


class B2TransientClassifierTests(unittest.TestCase):
    def test_classifier_matches_mission_retry_rules(self) -> None:
        for status in (429, 500, 502, 503, 504):
            self.assertTrue(
                CLI.is_transient_b2_read_error(_client_error(status)),
                msg=status,
            )
        for status in (400, 401, 403, 404, 409, 412):
            self.assertFalse(
                CLI.is_transient_b2_read_error(_client_error(status)),
                msg=status,
            )
        self.assertTrue(
            CLI.is_transient_b2_read_error(
                ConnectTimeoutError(endpoint_url="https://example.invalid")
            )
        )
        self.assertTrue(
            CLI.is_transient_b2_read_error(
                ReadTimeoutError(endpoint_url="https://example.invalid")
            )
        )
        self.assertFalse(CLI.is_transient_b2_read_error(ValueError("permanent")))


if __name__ == "__main__":
    unittest.main()
