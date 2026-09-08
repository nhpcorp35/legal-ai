#!/usr/bin/env python3
"""Production-safe B2 disaster-recovery backups for the legal-ai-executor volume.

Backs up regular files under the Railway volume mount (default ``/app/data``)
to immutable recovery-point keys under ``disaster-recovery/legal-ai-executor/``.
Live SQLite databases are copied with SQLite's online backup API. Uploads are
fail-closed: each artifact is independently verified before ``manifest.json``
is written. Credentials use the established LegalAI B2 env contract and are
never logged or printed.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
from typing import Any, BinaryIO, Callable, Iterable, Mapping, Optional, Tuple
from urllib.parse import quote

logger = logging.getLogger(__name__)

B2_ENV_NAMES = (
    "B2_KEY_ID",
    "B2_APPLICATION_KEY",
    "B2_BUCKET",
    "B2_ENDPOINT",
    "B2_REGION",
)

DEFAULT_SOURCE_ROOT = "/app/data"
DEFAULT_PREFIX = "disaster-recovery/legal-ai-executor"
DEFAULT_INTERVAL_SECONDS = 24 * 60 * 60
DEFAULT_INITIAL_DELAY_SECONDS = 30
# Initial attempt + len(backoffs) retries; short bounded waits between attempts.
TRANSIENT_RETRY_BACKOFF_SECONDS: Tuple[float, ...] = (5.0, 15.0)
MAX_TRANSIENT_ATTEMPTS = 1 + len(TRANSIENT_RETRY_BACKOFF_SECONDS)
ENABLED_ENV = "LEGALAI_EXECUTOR_VOLUME_B2_DR_ENABLED"
INTERVAL_ENV = "LEGALAI_EXECUTOR_VOLUME_B2_DR_INTERVAL_SECONDS"
INITIAL_DELAY_ENV = "LEGALAI_EXECUTOR_VOLUME_B2_DR_INITIAL_DELAY_SECONDS"
PREFIX_ENV = "LEGALAI_EXECUTOR_VOLUME_B2_DR_PREFIX"
SOURCE_ENV = "RAILWAY_VOLUME_MOUNT_PATH"

_TRANSIENT_ERROR_TYPE_NAMES = frozenset(
    {
        "EndpointConnectionError",
        "ConnectTimeoutError",
        "ReadTimeoutError",
        "ConnectionClosedError",
        "IncompleteReadError",
        "ProtocolError",
        "SSLError",
        "ProxyConnectionError",
        "ConnectionResetError",
        "BrokenPipeError",
    }
)

_EXCLUDE_SUFFIXES = (
    ".lock",
    ".pid",
    ".sock",
    ".socket",
    ".tmp",
    ".temp",
    ".swp",
    ".swo",
    "~",
)
_EXCLUDE_NAME_SUFFIXES = ("-wal", "-shm", "-journal")
_SQLITE_SUFFIXES = (".db", ".sqlite", ".sqlite3")

_daemon_thread: Optional[threading.Thread] = None
_daemon_lock = threading.Lock()


class VolumeBackupError(Exception):
    """Fail-closed volume backup / verification error (no secrets)."""

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


def configure_cli_logging() -> None:
    """Enable INFO logging for standalone CLI/daemon runs only.

    No-op when handlers already exist so importing this module under
    Flask/Gunicorn does not rewrite application logging configuration.
    """
    root = logging.getLogger()
    if root.handlers:
        return
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _is_recognized_transient_error(exc: BaseException) -> bool:
    """True when *exc* itself is a known transport/network failure type."""
    if isinstance(exc, VolumeBackupError):
        return False
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    return type(exc).__name__ in _TRANSIENT_ERROR_TYPE_NAMES


def _iter_exception_cause_context_chain(
    exc: BaseException, *, max_depth: int = 8
) -> Iterable[BaseException]:
    """Yield *exc* then a bounded ``__cause__`` / ``__context__`` chain.

    Cycle-safe: each object is visited at most once. Depth is capped so a
    pathological chain cannot loop or grow without bound.
    """
    seen: set[int] = set()
    stack: list[BaseException] = [exc]
    depth = 0
    while stack and depth < max_depth:
        current = stack.pop()
        cid = id(current)
        if cid in seen:
            continue
        seen.add(cid)
        depth += 1
        yield current
        # Prefer explicit ``raise ... from`` linkage, then implicit context.
        if current.__cause__ is not None:
            stack.append(current.__cause__)
        if current.__context__ is not None:
            stack.append(current.__context__)


def is_transient_daemon_error(exc: BaseException) -> bool:
    """Return True for transport/network failures eligible for in-cycle retry.

    Deterministic ``VolumeBackupError`` cases (config, integrity, overwrite,
    hash/size mismatches) must not retry. A ``VolumeBackupError`` is transient
    only when its bounded cause/context chain contains a recognized
    transport/network error (``ConnectionClosedError``, ``ProtocolError``,
    timeouts, connection errors, or the transient type-name allowlist).
    """
    if isinstance(exc, VolumeBackupError):
        for link in _iter_exception_cause_context_chain(exc):
            if link is exc:
                continue
            if _is_recognized_transient_error(link):
                return True
        return False
    return _is_recognized_transient_error(exc)


@dataclass(frozen=True)
class B2Config:
    """B2 connection settings; secrets never appear in ``repr``."""

    key_id: str
    application_key: str
    bucket: str
    endpoint: str
    region: str

    def __repr__(self) -> str:
        return (
            "B2Config("
            "key_id='***', "
            "application_key='***', "
            f"bucket={self.bucket!r}, "
            f"endpoint={self.endpoint!r}, "
            f"region={self.region!r})"
        )

    @classmethod
    def from_env(cls, environ: Optional[Mapping[str, str]] = None) -> "B2Config":
        env = os.environ if environ is None else environ
        missing = [
            name for name in B2_ENV_NAMES if not str(env.get(name, "")).strip()
        ]
        if missing:
            raise VolumeBackupError(
                "Missing required B2 environment variables: " + ", ".join(missing),
                missing=missing,
            )
        return cls(
            key_id=str(env["B2_KEY_ID"]).strip(),
            application_key=str(env["B2_APPLICATION_KEY"]).strip(),
            bucket=str(env["B2_BUCKET"]).strip(),
            endpoint=str(env["B2_ENDPOINT"]).strip(),
            region=str(env["B2_REGION"]).strip(),
        )


def create_b2_client(config: B2Config):
    """Build a boto3 S3 client for the B2 S3-compatible endpoint."""
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=config.endpoint,
        aws_access_key_id=config.key_id,
        aws_secret_access_key=config.application_key,
        region_name=config.region,
    )


def backups_enabled(environ: Optional[Mapping[str, str]] = None) -> bool:
    env = os.environ if environ is None else environ
    return str(env.get(ENABLED_ENV, "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def resolve_source_root(
    source_root: Optional[Path] = None,
    *,
    environ: Optional[Mapping[str, str]] = None,
) -> Path:
    if source_root is not None:
        return Path(source_root)
    env = os.environ if environ is None else environ
    raw = str(env.get(SOURCE_ENV, "")).strip() or DEFAULT_SOURCE_ROOT
    return Path(raw)


def resolve_prefix(
    prefix: Optional[str] = None,
    *,
    environ: Optional[Mapping[str, str]] = None,
) -> str:
    if prefix is not None and str(prefix).strip():
        return str(prefix).strip().strip("/")
    env = os.environ if environ is None else environ
    raw = str(env.get(PREFIX_ENV, "")).strip() or DEFAULT_PREFIX
    return raw.strip().strip("/")


def recovery_point_labels(created_at: datetime) -> list[str]:
    """Return retention labels without deleting or enabling lifecycle rules."""
    created = created_at.astimezone(timezone.utc)
    labels = ["daily"]
    if created.weekday() == 6:  # Sunday
        labels.append("weekly")
    if created.day == 1:
        labels.append("monthly")
    return labels


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_stream(body: BinaryIO) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: body.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def is_excluded_path(path: Path) -> bool:
    name = path.name
    lower = name.lower()
    if name.startswith(".#"):
        return True
    if any(lower.endswith(suffix) for suffix in _EXCLUDE_SUFFIXES):
        return True
    if any(lower.endswith(suffix) for suffix in _EXCLUDE_NAME_SUFFIXES):
        return True
    return False


def is_sqlite_db_path(path: Path) -> bool:
    lower = path.name.lower()
    return any(lower.endswith(suffix) for suffix in _SQLITE_SUFFIXES)


def create_consistent_sqlite_backup(source_path: Path, destination_path: Path) -> None:
    """Create and integrity-check a transactionally consistent SQLite copy."""
    if not source_path.is_file():
        raise VolumeBackupError(
            "SQLite source not found",
            path=str(source_path),
        )
    uri = f"file:{quote(str(source_path.resolve()), safe='/')}?mode=ro"
    source = sqlite3.connect(uri, uri=True, timeout=30.0)
    destination = sqlite3.connect(str(destination_path), timeout=30.0)
    try:
        source.backup(destination)
        row = destination.execute("PRAGMA integrity_check").fetchone()
        if row is None or str(row[0]).lower() != "ok":
            raise VolumeBackupError("SQLite backup integrity_check failed")
    finally:
        destination.close()
        source.close()


def iter_backup_candidates(source_root: Path) -> list[Path]:
    """List regular files under ``source_root`` eligible for backup."""
    root = Path(source_root)
    if not root.is_dir():
        raise VolumeBackupError(
            "volume source root is not a directory",
            path=str(root),
        )
    candidates: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if is_excluded_path(path):
            continue
        candidates.append(path)
    return candidates


def _build_recovery_point_id(created_at: datetime) -> str:
    stamp = created_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"rp-{stamp}"


def _recovery_point_prefix(base_prefix: str, created_at: datetime) -> str:
    created = created_at.astimezone(timezone.utc)
    date_path = created.strftime("%Y/%m/%d")
    rp_id = _build_recovery_point_id(created)
    return f"{base_prefix.strip('/')}/{date_path}/{rp_id}"


def _artifact_object_key(rp_prefix: str, relative_path: str) -> str:
    rel = relative_path.replace("\\", "/").lstrip("/")
    return f"{rp_prefix}/artifacts/{rel}"


def _manifest_object_key(rp_prefix: str) -> str:
    return f"{rp_prefix}/manifest.json"


def _http_status_from_exc(exc: BaseException) -> Optional[int]:
    response = getattr(exc, "response", None)
    if not isinstance(response, Mapping):
        return None
    meta = response.get("ResponseMetadata")
    if isinstance(meta, Mapping):
        status = meta.get("HTTPStatusCode")
        if isinstance(status, int):
            return status
        if isinstance(status, str) and status.strip().isdigit():
            return int(status.strip())
    error = response.get("Error")
    if isinstance(error, Mapping):
        code = error.get("Code")
        if isinstance(code, int):
            return code
        if isinstance(code, str) and code.strip().isdigit():
            return int(code.strip())
    return None


def _object_exists(client: Any, bucket: str, key: str) -> bool:
    try:
        client.head_object(Bucket=bucket, Key=key)
    except Exception as exc:  # noqa: BLE001 — treat missing as absent
        status = _http_status_from_exc(exc)
        message = str(exc)
        error = getattr(exc, "response", None)
        error_code = ""
        if isinstance(error, Mapping):
            payload = error.get("Error")
            if isinstance(payload, Mapping):
                error_code = str(payload.get("Code") or "")
        missing = (
            status == 404
            or error_code in {"404", "NoSuchKey", "NotFound"}
            or "NoSuchKey" in message
            or "Not Found" in message
        )
        if missing:
            return False
        raise VolumeBackupError(
            "B2 head_object failed while checking immutability",
            object_key=key,
            error_type=type(exc).__name__,
        ) from exc
    return True


def _put_immutable_bytes(
    client: Any,
    *,
    bucket: str,
    key: str,
    body: bytes,
    content_type: str,
    metadata: Mapping[str, str],
) -> None:
    if _object_exists(client, bucket, key):
        raise VolumeBackupError(
            "refusing overwrite of existing B2 object",
            object_key=key,
        )
    try:
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
            Metadata=dict(metadata),
            IfNoneMatch="*",
        )
    except Exception as exc:  # noqa: BLE001
        raise VolumeBackupError(
            "B2 put_object failed",
            object_key=key,
            error_type=type(exc).__name__,
        ) from exc


def _verify_remote_artifact(
    client: Any,
    *,
    bucket: str,
    key: str,
    expected_size: int,
    expected_sha256: str,
    download_body: bool = True,
) -> None:
    try:
        head = client.head_object(Bucket=bucket, Key=key)
    except Exception as exc:  # noqa: BLE001
        raise VolumeBackupError(
            "B2 head_object verification failed",
            object_key=key,
            error_type=type(exc).__name__,
        ) from exc
    remote_size = head.get("ContentLength")
    if int(remote_size) != int(expected_size):
        raise VolumeBackupError(
            "B2 object size mismatch",
            object_key=key,
            expected_size=expected_size,
            remote_size=remote_size,
        )
    metadata = {
        str(k).lower(): str(v) for k, v in (head.get("Metadata") or {}).items()
    }
    remote_sha = metadata.get("sha256", "")
    if remote_sha != expected_sha256:
        raise VolumeBackupError(
            "B2 object metadata SHA-256 mismatch",
            object_key=key,
            expected_sha256=expected_sha256,
            remote_sha256=remote_sha,
        )
    if not download_body:
        return
    try:
        response = client.get_object(Bucket=bucket, Key=key)
        body = response["Body"]
        downloaded = _sha256_stream(body)
    except Exception as exc:  # noqa: BLE001
        raise VolumeBackupError(
            "B2 get_object verification failed",
            object_key=key,
            error_type=type(exc).__name__,
        ) from exc
    if downloaded != expected_sha256:
        raise VolumeBackupError(
            "B2 downloaded SHA-256 mismatch",
            object_key=key,
            expected_sha256=expected_sha256,
            remote_sha256=downloaded,
        )


def _stage_file_bytes(path: Path) -> tuple[bytes, str, str]:
    """Return ``(payload, sha256, kind)`` without mutating the source file."""
    if is_sqlite_db_path(path):
        fd, temp_name = tempfile.mkstemp(
            prefix="legalai-executor-sqlite-",
            suffix=".db",
            dir="/tmp",
        )
        os.close(fd)
        temp_path = Path(temp_name)
        try:
            create_consistent_sqlite_backup(path, temp_path)
            payload = temp_path.read_bytes()
            digest = hashlib.sha256(payload).hexdigest()
            return payload, digest, "sqlite_snapshot"
        finally:
            temp_path.unlink(missing_ok=True)
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    return payload, digest, "file"


def build_manifest(
    *,
    created_at: datetime,
    source_root: Path,
    rp_prefix: str,
    labels: list[str],
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema": "legalai.executor.volume_b2_dr.v1",
        "created_at": created_at.astimezone(timezone.utc).isoformat(),
        "source_root": str(source_root),
        "recovery_point_id": _build_recovery_point_id(created_at),
        "recovery_point_prefix": rp_prefix,
        "labels": list(labels),
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "retention_note": (
            "labels are advisory for daily/weekly/monthly retention; "
            "this backup never deletes objects or enables lifecycle deletion"
        ),
    }


def backup_volume_to_b2(
    *,
    source_root: Optional[Path] = None,
    prefix: Optional[str] = None,
    client: Any = None,
    config: Optional[B2Config] = None,
    environ: Optional[Mapping[str, str]] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Back up volume contents to an immutable recovery point; return manifest."""
    env = os.environ if environ is None else environ
    root = resolve_source_root(source_root, environ=env)
    base_prefix = resolve_prefix(prefix, environ=env)
    created = now or datetime.now(timezone.utc)
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    created = created.astimezone(timezone.utc)
    labels = recovery_point_labels(created)
    rp_prefix = _recovery_point_prefix(base_prefix, created)

    b2_config = config if config is not None else B2Config.from_env(env)
    s3 = client if client is not None else create_b2_client(b2_config)

    candidates = iter_backup_candidates(root)
    artifacts: list[dict[str, Any]] = []

    for path in candidates:
        relative = path.relative_to(root).as_posix()
        object_key = _artifact_object_key(rp_prefix, relative)
        payload, digest, kind = _stage_file_bytes(path)
        size_bytes = len(payload)
        _put_immutable_bytes(
            s3,
            bucket=b2_config.bucket,
            key=object_key,
            body=payload,
            content_type="application/octet-stream",
            metadata={
                "sha256": digest,
                "source": "legal-ai-executor",
                "relative-path": relative,
                "kind": kind,
            },
        )
        _verify_remote_artifact(
            s3,
            bucket=b2_config.bucket,
            key=object_key,
            expected_size=size_bytes,
            expected_sha256=digest,
            download_body=True,
        )
        artifacts.append(
            {
                "relative_path": relative,
                "object_key": object_key,
                "size_bytes": size_bytes,
                "sha256": digest,
                "kind": kind,
            }
        )

    manifest = build_manifest(
        created_at=created,
        source_root=root,
        rp_prefix=rp_prefix,
        labels=labels,
        artifacts=artifacts,
    )
    manifest_key = _manifest_object_key(rp_prefix)
    manifest_bytes = (
        json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
    _put_immutable_bytes(
        s3,
        bucket=b2_config.bucket,
        key=manifest_key,
        body=manifest_bytes,
        content_type="application/json; charset=utf-8",
        metadata={
            "sha256": manifest_digest,
            "source": "legal-ai-executor",
            "kind": "manifest",
        },
    )
    _verify_remote_artifact(
        s3,
        bucket=b2_config.bucket,
        key=manifest_key,
        expected_size=len(manifest_bytes),
        expected_sha256=manifest_digest,
        download_body=True,
    )
    manifest["manifest_object_key"] = manifest_key
    manifest["manifest_sha256"] = manifest_digest
    manifest["manifest_size_bytes"] = len(manifest_bytes)
    manifest["bucket"] = b2_config.bucket
    manifest["verified"] = True
    return manifest


def verify_recovery_point(
    *,
    manifest_key: Optional[str] = None,
    recovery_point_prefix: Optional[str] = None,
    client: Any = None,
    config: Optional[B2Config] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> dict[str, Any]:
    """Non-destructive verify: check remote size/hash metadata; do not restore."""
    env = os.environ if environ is None else environ
    b2_config = config if config is not None else B2Config.from_env(env)
    s3 = client if client is not None else create_b2_client(b2_config)

    key = (manifest_key or "").strip()
    if not key:
        rp = (recovery_point_prefix or "").strip().strip("/")
        if not rp:
            raise VolumeBackupError(
                "manifest_key or recovery_point_prefix is required for verify"
            )
        key = _manifest_object_key(rp)

    try:
        response = s3.get_object(Bucket=b2_config.bucket, Key=key)
        body = response["Body"].read()
    except Exception as exc:  # noqa: BLE001
        raise VolumeBackupError(
            "failed to load remote manifest for verify",
            object_key=key,
            error_type=type(exc).__name__,
        ) from exc
    if isinstance(body, str):
        body = body.encode("utf-8")
    manifest = json.loads(bytes(body).decode("utf-8"))
    if not isinstance(manifest, dict):
        raise VolumeBackupError("remote manifest must be a JSON object")

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise VolumeBackupError("remote manifest missing artifacts list")

    checked: list[dict[str, Any]] = []
    for entry in artifacts:
        if not isinstance(entry, Mapping):
            raise VolumeBackupError("manifest artifact entry must be an object")
        object_key = str(entry.get("object_key") or "").strip()
        expected_size = int(entry["size_bytes"])
        expected_sha = str(entry.get("sha256") or "").strip().lower()
        if not object_key or not expected_sha:
            raise VolumeBackupError(
                "manifest artifact missing object_key or sha256",
                relative_path=entry.get("relative_path"),
            )
        _verify_remote_artifact(
            s3,
            bucket=b2_config.bucket,
            key=object_key,
            expected_size=expected_size,
            expected_sha256=expected_sha,
            download_body=False,
        )
        checked.append(
            {
                "object_key": object_key,
                "size_bytes": expected_size,
                "sha256": expected_sha,
                "verified": True,
            }
        )

    return {
        "ok": True,
        "manifest_object_key": key,
        "recovery_point_id": manifest.get("recovery_point_id"),
        "labels": list(manifest.get("labels") or []),
        "checked_count": len(checked),
        "artifacts": checked,
        "restored": False,
    }


def run_backup_cycle_with_retries(
    *,
    backup_fn: Callable[..., dict[str, Any]],
    environ: Mapping[str, str],
    stop_event: threading.Event,
    transient_retry_backoffs: Tuple[float, ...] = TRANSIENT_RETRY_BACKOFF_SECONDS,
) -> None:
    """Run one scheduled backup with bounded transient retries (no secrets logged).

    Performs an initial attempt plus at most ``len(transient_retry_backoffs)``
    retries (default 2) for transport/network failures only. Deterministic
    ``VolumeBackupError`` failures are not retried. After success or exhaustion
    the caller waits the normal schedule interval.
    """
    max_attempts = 1 + len(transient_retry_backoffs)
    for attempt in range(1, max_attempts + 1):
        if stop_event.is_set():
            return
        try:
            result = backup_fn(environ=environ)
            logger.info(
                "legal-ai-executor volume B2 DR verified rp=%s artifacts=%s",
                result.get("recovery_point_id"),
                result.get("artifact_count"),
            )
            return
        except Exception as exc:  # noqa: BLE001 — classify then decide retry
            error_type = type(exc).__name__
            if not is_transient_daemon_error(exc):
                logger.exception(
                    "legal-ai-executor volume B2 DR failed error_type=%s",
                    error_type,
                )
                return
            if attempt >= max_attempts:
                logger.exception(
                    "legal-ai-executor volume B2 DR failed after %s attempts "
                    "error_type=%s",
                    attempt,
                    error_type,
                )
                return
            delay = float(transient_retry_backoffs[attempt - 1])
            logger.warning(
                "legal-ai-executor volume B2 DR transient failure "
                "attempt=%s/%s error_type=%s retry_in_sec=%s",
                attempt,
                max_attempts,
                error_type,
                delay,
            )
            if stop_event.wait(delay):
                return


def run_daemon(
    *,
    interval_seconds: Optional[float] = None,
    initial_delay_seconds: Optional[float] = None,
    stop_event: Optional[threading.Event] = None,
    environ: Optional[Mapping[str, str]] = None,
    backup_fn: Callable[..., dict[str, Any]] = backup_volume_to_b2,
    transient_retry_backoffs: Tuple[float, ...] = TRANSIENT_RETRY_BACKOFF_SECONDS,
) -> int:
    """Run recurring verified volume backups until stopped."""
    env = os.environ if environ is None else environ
    interval = interval_seconds
    if interval is None:
        interval = float(env.get(INTERVAL_ENV, DEFAULT_INTERVAL_SECONDS))
    initial_delay = initial_delay_seconds
    if initial_delay is None:
        initial_delay = float(env.get(INITIAL_DELAY_ENV, DEFAULT_INITIAL_DELAY_SECONDS))
    if float(interval) < 300:
        raise VolumeBackupError(
            "LEGALAI executor volume B2 DR interval must be at least 300 seconds",
            interval_seconds=interval,
        )

    stopper = stop_event or threading.Event()
    if initial_delay > 0 and stopper.wait(float(initial_delay)):
        return 0

    while not stopper.is_set():
        run_backup_cycle_with_retries(
            backup_fn=backup_fn,
            environ=env,
            stop_event=stopper,
            transient_retry_backoffs=transient_retry_backoffs,
        )
        if stopper.wait(float(interval)):
            break
    return 0


def maybe_start_daemon_thread(
    *,
    environ: Optional[Mapping[str, str]] = None,
    target: Callable[..., int] = run_daemon,
) -> Optional[threading.Thread]:
    """Start the background daemon once when enabled; never raises to callers."""
    global _daemon_thread
    env = os.environ if environ is None else environ
    if not backups_enabled(env):
        return None
    with _daemon_lock:
        if _daemon_thread is not None and _daemon_thread.is_alive():
            return _daemon_thread
        try:
            thread = threading.Thread(
                target=target,
                name="legalai-executor-volume-b2-dr",
                kwargs={"environ": dict(env)},
                daemon=True,
            )
            thread.start()
            _daemon_thread = thread
            return thread
        except Exception:  # noqa: BLE001 — primary executor must keep running
            logger.exception(
                "failed to start legal-ai-executor volume B2 DR daemon"
            )
            return None


def main(argv: Optional[Iterable[str]] = None) -> int:
    configure_cli_logging()
    parser = argparse.ArgumentParser(
        description="legal-ai-executor volume disaster-recovery backup to B2",
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="once",
        choices=("once", "daemon", "verify"),
    )
    parser.add_argument(
        "--source-root",
        default=None,
        help="Volume root to back up (default: RAILWAY_VOLUME_MOUNT_PATH or /app/data)",
    )
    parser.add_argument(
        "--prefix",
        default=None,
        help="B2 key prefix (default: disaster-recovery/legal-ai-executor)",
    )
    parser.add_argument(
        "--manifest-key",
        default=None,
        help="Remote manifest object key for verify mode",
    )
    parser.add_argument(
        "--recovery-point-prefix",
        default=None,
        help="Recovery-point prefix for verify mode (loads .../manifest.json)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "daemon":
        return run_daemon()
    if args.command == "verify":
        result = verify_recovery_point(
            manifest_key=args.manifest_key,
            recovery_point_prefix=args.recovery_point_prefix,
        )
        print(
            "verify: PASS "
            f"manifest={result['manifest_object_key']} "
            f"checked={result['checked_count']}"
        )
        return 0

    result = backup_volume_to_b2(
        source_root=Path(args.source_root) if args.source_root else None,
        prefix=args.prefix,
    )
    print(
        "backup: PASS "
        f"rp={result['recovery_point_id']} "
        f"artifacts={result['artifact_count']} "
        f"manifest={result['manifest_object_key']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
