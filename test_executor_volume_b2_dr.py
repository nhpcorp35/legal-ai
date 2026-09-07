"""Focused tests for legal-ai-executor volume B2 disaster-recovery backups."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest import mock

import executor_volume_b2_dr as dr


def _b2_env() -> dict[str, str]:
    return {
        "B2_KEY_ID": "key-id-secret-value",
        "B2_APPLICATION_KEY": "app-key-secret-value",
        "B2_BUCKET": "legalai-corpus",
        "B2_ENDPOINT": "https://s3.us-east-005.backblazeb2.com",
        "B2_REGION": "us-east-005",
    }


class FakeS3:
    def __init__(
        self,
        *,
        corrupt_download: bool = False,
        corrupt_metadata_sha: bool = False,
    ) -> None:
        self.objects: dict[tuple[str, str], tuple[bytes, dict[str, str]]] = {}
        self.corrupt_download = corrupt_download
        self.corrupt_metadata_sha = corrupt_metadata_sha
        self.put_calls = 0

    def put_object(self, *, Bucket, Key, Body, ContentType, Metadata, IfNoneMatch=None):
        if IfNoneMatch != "*":
            raise AssertionError("immutable uploads must set IfNoneMatch='*'")
        if (Bucket, Key) in self.objects:
            raise RuntimeError("precondition failed: object exists")
        data = Body.read() if hasattr(Body, "read") else bytes(Body)
        metadata = dict(Metadata)
        if self.corrupt_metadata_sha and metadata.get("kind") != "manifest":
            metadata["sha256"] = "0" * 64
        self.objects[(Bucket, Key)] = (data, metadata)
        self.put_calls += 1
        return {}

    def head_object(self, *, Bucket, Key):
        try:
            data, metadata = self.objects[(Bucket, Key)]
        except KeyError as exc:
            err = Exception("Not Found")
            err.response = {  # type: ignore[attr-defined]
                "ResponseMetadata": {"HTTPStatusCode": 404},
                "Error": {"Code": "404", "Message": "Not Found"},
            }
            raise err from exc
        return {"ContentLength": len(data), "Metadata": metadata}

    def get_object(self, *, Bucket, Key):
        data, _ = self.objects[(Bucket, Key)]
        if self.corrupt_download and not Key.endswith("/manifest.json"):
            data = data + b"corrupt"
        return {"Body": io.BytesIO(data)}


class ManifestAndImmutableTests(unittest.TestCase):
    def test_manifest_lists_relative_paths_size_and_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root / "notes").mkdir()
            payload = b"hello volume backup"
            target = root / "notes" / "readme.txt"
            target.write_bytes(payload)
            (root / "notes" / "scratch.tmp").write_text("skip", encoding="utf-8")
            (root / "notes" / "db.sqlite-wal").write_bytes(b"wal")

            config = dr.B2Config.from_env(_b2_env())
            s3 = FakeS3()
            manifest = dr.backup_volume_to_b2(
                source_root=root,
                prefix="disaster-recovery/legal-ai-executor",
                client=s3,
                config=config,
                environ=_b2_env(),
                now=datetime(2026, 9, 7, 22, 30, tzinfo=timezone.utc),
            )

            self.assertEqual(manifest["schema"], "legalai.executor.volume_b2_dr.v1")
            self.assertEqual(manifest["recovery_point_id"], "rp-20260907T223000Z")
            self.assertEqual(manifest["labels"], ["daily"])
            self.assertTrue(manifest["verified"])
            self.assertEqual(manifest["artifact_count"], 1)
            artifact = manifest["artifacts"][0]
            self.assertEqual(artifact["relative_path"], "notes/readme.txt")
            self.assertEqual(artifact["size_bytes"], len(payload))
            self.assertEqual(
                artifact["sha256"], hashlib.sha256(payload).hexdigest()
            )
            self.assertEqual(artifact["kind"], "file")
            self.assertTrue(
                artifact["object_key"].startswith(
                    "disaster-recovery/legal-ai-executor/2026/09/07/"
                    "rp-20260907T223000Z/artifacts/"
                )
            )
            self.assertIn("manifest.json", manifest["manifest_object_key"])
            # Manifest uploaded after the single artifact (+ itself).
            self.assertGreaterEqual(s3.put_calls, 2)

    def test_refuses_overwrite_of_existing_object(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root / "a.txt").write_text("one", encoding="utf-8")
            config = dr.B2Config.from_env(_b2_env())
            s3 = FakeS3()
            first = dr.backup_volume_to_b2(
                source_root=root,
                client=s3,
                config=config,
                environ=_b2_env(),
                now=datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc),
            )
            # Force a second backup into the same recovery-point key space.
            with self.assertRaisesRegex(dr.VolumeBackupError, "refusing overwrite"):
                dr.backup_volume_to_b2(
                    source_root=root,
                    client=s3,
                    config=config,
                    environ=_b2_env(),
                    now=datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc),
                )
            self.assertTrue(first["verified"])


class SqliteSnapshotTests(unittest.TestCase):
    def test_sqlite_uses_consistent_snapshot_not_live_wal_file(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            db_path = root / "state.db"
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE records (value TEXT NOT NULL)")
            conn.execute("INSERT INTO records VALUES ('committed')")
            conn.commit()
            self.assertTrue(Path(str(db_path) + "-wal").exists())

            config = dr.B2Config.from_env(_b2_env())
            s3 = FakeS3()
            manifest = dr.backup_volume_to_b2(
                source_root=root,
                client=s3,
                config=config,
                environ=_b2_env(),
                now=datetime(2026, 9, 6, 23, 30, tzinfo=timezone.utc),
            )
            kinds = {item["kind"] for item in manifest["artifacts"]}
            relatives = {item["relative_path"] for item in manifest["artifacts"]}
            self.assertEqual(kinds, {"sqlite_snapshot"})
            self.assertEqual(relatives, {"state.db"})
            self.assertNotIn("state.db-wal", relatives)

            artifact = manifest["artifacts"][0]
            payload, _ = s3.objects[(config.bucket, artifact["object_key"])]
            copied = Path(tempdir) / "restored.db"
            copied.write_bytes(payload)
            verify = sqlite3.connect(copied)
            try:
                self.assertEqual(
                    verify.execute("SELECT value FROM records").fetchone()[0],
                    "committed",
                )
                self.assertEqual(
                    verify.execute("PRAGMA integrity_check").fetchone()[0],
                    "ok",
                )
            finally:
                verify.close()
            conn.close()


class HashMismatchAndVerifyTests(unittest.TestCase):
    def test_hash_mismatch_fails_closed_before_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root / "a.txt").write_text("payload", encoding="utf-8")
            config = dr.B2Config.from_env(_b2_env())
            s3 = FakeS3(corrupt_metadata_sha=True)
            with self.assertRaisesRegex(
                dr.VolumeBackupError, "metadata SHA-256 mismatch"
            ):
                dr.backup_volume_to_b2(
                    source_root=root,
                    client=s3,
                    config=config,
                    environ=_b2_env(),
                    now=datetime(2026, 9, 7, 1, 0, tzinfo=timezone.utc),
                )
            manifest_keys = [
                key for (_, key) in s3.objects if key.endswith("/manifest.json")
            ]
            self.assertEqual(manifest_keys, [])

    def test_verify_mode_checks_metadata_without_restoring(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root / "a.txt").write_text("verify-me", encoding="utf-8")
            config = dr.B2Config.from_env(_b2_env())
            s3 = FakeS3()
            manifest = dr.backup_volume_to_b2(
                source_root=root,
                client=s3,
                config=config,
                environ=_b2_env(),
                now=datetime(2026, 9, 7, 8, 0, tzinfo=timezone.utc),
            )
            result = dr.verify_recovery_point(
                manifest_key=manifest["manifest_object_key"],
                client=s3,
                config=config,
                environ=_b2_env(),
            )
            self.assertTrue(result["ok"])
            self.assertFalse(result["restored"])
            self.assertEqual(result["checked_count"], 1)
            # Source tree untouched.
            self.assertEqual((root / "a.txt").read_text(encoding="utf-8"), "verify-me")


class StartupGatingTests(unittest.TestCase):
    def test_daemon_start_gated_by_env_flag(self) -> None:
        dr._daemon_thread = None
        env = _b2_env()
        self.assertIsNone(dr.maybe_start_daemon_thread(environ=env))

        started = threading.Event()
        stop = threading.Event()

        def fake_daemon(**kwargs):
            started.set()
            stop.wait(0.2)
            return 0

        env[dr.ENABLED_ENV] = "true"
        thread = dr.maybe_start_daemon_thread(environ=env, target=fake_daemon)
        self.assertIsNotNone(thread)
        self.assertTrue(started.wait(1.0))
        stop.set()
        assert thread is not None
        thread.join(timeout=1.0)
        dr._daemon_thread = None

    def test_app_startup_wiring_calls_volume_dr_helper(self) -> None:
        source = Path("app.py").read_text(encoding="utf-8")
        self.assertIn("def _ensure_volume_b2_dr_started", source)
        self.assertIn("_ensure_volume_b2_dr_started()", source)
        self.assertIn("LEGALAI_EXECUTOR_VOLUME_B2_DR_ENABLED", source)

    def test_ensure_volume_b2_dr_started_is_gated_and_idempotent(self) -> None:
        import app as app_module

        app_module._volume_b2_dr_started = False
        with mock.patch.dict("os.environ", {dr.ENABLED_ENV: ""}, clear=False):
            with mock.patch(
                "executor_volume_b2_dr.maybe_start_daemon_thread"
            ) as start:
                app_module._ensure_volume_b2_dr_started()
                app_module._ensure_volume_b2_dr_started()
                start.assert_called_once()
        app_module._volume_b2_dr_started = False


class LabelTests(unittest.TestCase):
    def test_weekly_and_monthly_labels(self) -> None:
        sunday = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)  # Sunday
        self.assertEqual(dr.recovery_point_labels(sunday), ["daily", "weekly"])
        first = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)  # Tuesday
        self.assertEqual(dr.recovery_point_labels(first), ["daily", "monthly"])


class ConfigSafetyTests(unittest.TestCase):
    def test_b2_config_repr_hides_secrets(self) -> None:
        config = dr.B2Config.from_env(_b2_env())
        text = repr(config)
        self.assertNotIn("key-id-secret-value", text)
        self.assertNotIn("app-key-secret-value", text)
        self.assertIn("***", text)


if __name__ == "__main__":
    unittest.main()
