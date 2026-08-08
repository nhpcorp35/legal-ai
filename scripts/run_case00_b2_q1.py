#!/usr/bin/env python3
"""Rebuild Case-00 derived artifacts from B2, generate one candidate, upload to B2.

This wrapper runs rebuild + generation in the same checkout, then uploads the
four finalized candidate artifacts to Backblaze B2. Local --candidate-output-root
paths (including /tmp) are ephemeral only; durable handoff is verified B2 object
keys under the canonical candidate prefix.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import rebuild_case00_derived as rebuild_cli  # noqa: E402

AUTHORIZATION_ACKNOWLEDGEMENT = (
    "I_AUTHORIZE_PRIVATE_EVIDENCE_TRANSMISSION_TO_MODEL_PROVIDER"
)

# Canonical durable prefix for Case-00 attorney-feedback candidate answers.
DEFAULT_CANDIDATE_B2_PREFIX = (
    "Benchmarks/Case-00-Triborough/derived/attorney-feedback-eval/candidate-answers/"
)

CANDIDATE_ARTIFACT_NAMES = (
    "Q1_candidate_answer.json",
    "Q1_candidate_answer.md",
    "generation_manifest.json",
    "model_input_audit.json",
)


class DurableUploadError(Exception):
    """Fail-closed durable upload / verification error (never embeds secrets)."""

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


def _run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _emit(payload: dict) -> None:
    print(json.dumps(payload, sort_keys=True))


def normalize_candidate_b2_prefix(prefix: str) -> str:
    """Normalize a candidate object prefix; reject empty / traversal / absolute."""
    raw = (prefix or "").strip().replace("\\", "/")
    if not raw:
        raise DurableUploadError("candidate B2 prefix must not be empty")
    if raw.startswith("/") or raw.startswith("~"):
        raise DurableUploadError(
            "candidate B2 prefix must be a relative object key prefix",
            prefix=raw,
        )
    # Reject Windows-style drive prefixes and URI schemes.
    if "://" in raw or (len(raw) >= 2 and raw[1] == ":"):
        raise DurableUploadError(
            "candidate B2 prefix must not include a URI or drive prefix",
            prefix=raw,
        )
    parts = [part for part in raw.split("/") if part != ""]
    if not parts:
        raise DurableUploadError("candidate B2 prefix must not be empty")
    if any(part in (".", "..") for part in parts):
        raise DurableUploadError(
            "candidate B2 prefix must not contain path traversal segments",
            prefix=raw,
        )
    # Never treat a local filesystem path as a durable object prefix.
    if parts[0] in ("tmp", "var", "private") or raw.lower().startswith("tmp/"):
        raise DurableUploadError(
            "candidate B2 prefix must not look like a local filesystem path",
            prefix=raw,
        )
    return "/".join(parts) + "/"


def assert_key_under_prefix(object_key: str, prefix: str) -> None:
    normalized_prefix = normalize_candidate_b2_prefix(prefix)
    key = (object_key or "").replace("\\", "/")
    if not key or key.endswith("/"):
        raise DurableUploadError(
            "object key must be a non-empty file key",
            key=key,
            prefix=normalized_prefix,
        )
    if any(part in (".", "..") for part in key.split("/")):
        raise DurableUploadError(
            "object key must not contain path traversal segments",
            key=key,
        )
    if not key.startswith(normalized_prefix):
        raise DurableUploadError(
            "object key escapes the selected candidate B2 prefix",
            key=key,
            prefix=normalized_prefix,
        )
    remainder = key[len(normalized_prefix) :]
    if not remainder or remainder.startswith("/") or "/../" in f"/{remainder}/":
        raise DurableUploadError(
            "object key escapes the selected candidate B2 prefix",
            key=key,
            prefix=normalized_prefix,
        )


def build_candidate_object_key(
    prefix: str,
    candidate_basename: str,
    filename: str,
) -> str:
    normalized_prefix = normalize_candidate_b2_prefix(prefix)
    base = (candidate_basename or "").strip().replace("\\", "/")
    name = (filename or "").strip().replace("\\", "/")
    if not base or "/" in base or base in (".", ".."):
        raise DurableUploadError(
            "candidate directory basename is unsafe or empty",
            candidate_basename=candidate_basename,
        )
    if name not in CANDIDATE_ARTIFACT_NAMES:
        raise DurableUploadError(
            "refusing to upload unexpected candidate artifact name",
            filename=filename,
            allowed=list(CANDIDATE_ARTIFACT_NAMES),
        )
    key = f"{normalized_prefix}{base}/{name}"
    assert_key_under_prefix(key, normalized_prefix)
    return key


def _parse_generation_payload(stdout: str) -> dict[str, Any]:
    text = (stdout or "").strip()
    if not text:
        raise DurableUploadError("generation produced empty stdout; cannot locate artifacts")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DurableUploadError(
            "generation stdout is not valid JSON",
            error=str(exc),
        ) from exc
    if not isinstance(payload, dict):
        raise DurableUploadError("generation stdout JSON must be an object")
    if not payload.get("ok") or not payload.get("finalized"):
        raise DurableUploadError(
            "generation did not report finalized success",
            generation_ok=payload.get("ok"),
            finalized=payload.get("finalized"),
        )
    return payload


def _candidate_dir_from_payload(payload: dict[str, Any]) -> Path:
    raw = payload.get("candidate_directory")
    if not raw or not isinstance(raw, str):
        raise DurableUploadError("generation payload missing candidate_directory")
    path = Path(raw)
    if not path.is_dir():
        raise DurableUploadError(
            "candidate_directory does not exist on disk",
            candidate_directory=str(path),
        )
    return path.resolve()


def upload_candidate_artifacts_to_b2(
    candidate_dir: Path,
    *,
    prefix: str = DEFAULT_CANDIDATE_B2_PREFIX,
    client: Optional[Any] = None,
    config: Optional[rebuild_cli.B2Config] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> dict[str, Any]:
    """Upload the four finalized artifacts and verify each with head_object.

    Local ``candidate_dir`` is treated as ephemeral. Success requires remote
    verification of every object; missing or size-mismatched objects fail closed.
    """
    cfg = config if config is not None else rebuild_cli.B2Config.from_env(environ)
    s3 = client if client is not None else rebuild_cli.create_b2_client(cfg)
    normalized_prefix = normalize_candidate_b2_prefix(prefix)
    candidate_path = Path(candidate_dir).resolve()
    basename = candidate_path.name

    objects: list[dict[str, Any]] = []
    for filename in CANDIDATE_ARTIFACT_NAMES:
        local_path = candidate_path / filename
        if not local_path.is_file():
            raise DurableUploadError(
                f"required candidate artifact missing before upload: {filename}",
                path=str(local_path),
            )
        expected_size = local_path.stat().st_size
        object_key = build_candidate_object_key(normalized_prefix, basename, filename)
        try:
            s3.upload_file(str(local_path), cfg.bucket, object_key)
        except Exception as exc:  # noqa: BLE001 — fail closed, no secret echo
            raise DurableUploadError(
                f"B2 upload failed for {filename}",
                object_key=object_key,
                error_type=type(exc).__name__,
            ) from exc
        try:
            head = s3.head_object(Bucket=cfg.bucket, Key=object_key)
        except Exception as exc:  # noqa: BLE001
            raise DurableUploadError(
                f"B2 head_object verification failed for {filename}",
                object_key=object_key,
                error_type=type(exc).__name__,
            ) from exc
        remote_size = head.get("ContentLength")
        if remote_size != expected_size:
            raise DurableUploadError(
                f"B2 object size mismatch for {filename}",
                object_key=object_key,
                expected_size=expected_size,
                remote_size=remote_size,
            )
        entry: dict[str, Any] = {
            "filename": filename,
            "object_key": object_key,
            "size": expected_size,
        }
        etag = head.get("ETag")
        if isinstance(etag, str) and etag.strip():
            entry["etag"] = etag.strip().strip('"')
        objects.append(entry)

    if len(objects) != len(CANDIDATE_ARTIFACT_NAMES):
        raise DurableUploadError(
            "durable upload incomplete; refusing success",
            uploaded=len(objects),
            required=len(CANDIDATE_ARTIFACT_NAMES),
        )

    return {
        "bucket": cfg.bucket,
        "prefix": normalized_prefix,
        "candidate_basename": basename,
        "object_keys": [item["object_key"] for item in objects],
        "objects": objects,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild Case-00 from Backblaze B2, generate one attorney-feedback "
            "candidate, and upload verified candidate artifacts to B2. "
            "Local --candidate-output-root is ephemeral only."
        )
    )
    parser.add_argument("--case-root", required=True)
    parser.add_argument("--question-id", required=True)
    parser.add_argument("--required-commit", required=True)
    parser.add_argument(
        "--candidate-output-root",
        required=True,
        help=(
            "Ephemeral local directory root for generation outputs "
            "(for example a temp path). Not a durable destination."
        ),
    )
    parser.add_argument(
        "--candidate-b2-prefix",
        default=DEFAULT_CANDIDATE_B2_PREFIX,
        help=(
            "Explicit B2 object prefix for durable candidate artifacts "
            f"(default: {DEFAULT_CANDIDATE_B2_PREFIX}). "
            "Never falls back to a local /tmp path as durable storage."
        ),
    )
    parser.add_argument(
        "--authorization-confirmed",
        action="store_true",
        required=True,
        help="Confirms the caller already obtained authorization to transmit private evidence.",
    )
    parser.add_argument(
        "--generation-only",
        action="store_true",
        required=True,
        help="Required safety gate; evaluation is not run by this wrapper.",
    )
    parser.add_argument(
        "--reuse-derived",
        action="store_true",
        help=(
            "Validate and reuse pre-staged derived artifacts instead of "
            "rebuilding the full source docket."
        ),
    )
    args = parser.parse_args(argv)

    try:
        candidate_prefix = normalize_candidate_b2_prefix(args.candidate_b2_prefix)
    except DurableUploadError as exc:
        _emit(
            {
                "ok": False,
                "phase": "durable_upload",
                "blocker": exc.message,
                **exc.details,
            }
        )
        return 1

    repo_root = Path(__file__).resolve().parents[1]
    rebuild_script = repo_root / "scripts" / "rebuild_case00_derived.py"
    generator_script = repo_root / "scripts" / "generate_attorney_feedback_candidate.py"

    rebuild_argv = [
        sys.executable,
        str(rebuild_script),
        "--case-root",
        args.case_root,
    ]
    if args.reuse_derived:
        rebuild_argv.append("--validate-only")
    else:
        rebuild_argv.append("--b2-prefix")

    rebuild = _run(rebuild_argv, repo_root)
    if rebuild.returncode != 0:
        _emit(
            {
                "ok": False,
                "phase": "rebuild",
                "return_code": rebuild.returncode,
                "stdout": rebuild.stdout,
                "stderr": rebuild.stderr,
            }
        )
        return rebuild.returncode or 1

    generation = _run(
        [
            sys.executable,
            str(generator_script),
            "--case-root",
            args.case_root,
            "--question-id",
            args.question_id,
            "--required-commit",
            args.required_commit,
            "--candidate-output-root",
            args.candidate_output_root,
            "--authorize-private-evidence-transmission",
            AUTHORIZATION_ACKNOWLEDGEMENT,
            "--generation-only",
            "--repo-root",
            str(repo_root),
        ],
        repo_root,
    )
    if generation.returncode != 0:
        _emit(
            {
                "ok": False,
                "phase": "generation",
                "return_code": generation.returncode,
                "stdout": generation.stdout,
                "stderr": generation.stderr,
            }
        )
        return generation.returncode or 1

    # Local generation success is not durable success — upload + verify required.
    try:
        generation_payload = _parse_generation_payload(generation.stdout)
        candidate_dir = _candidate_dir_from_payload(generation_payload)
        durable = upload_candidate_artifacts_to_b2(
            candidate_dir,
            prefix=candidate_prefix,
        )
    except rebuild_cli.RebuildError as exc:
        _emit(
            {
                "ok": False,
                "phase": "durable_upload",
                "blocker": exc.message,
                **exc.details,
                "ephemeral_local_directory": None,
            }
        )
        return 1
    except DurableUploadError as exc:
        _emit(
            {
                "ok": False,
                "phase": "durable_upload",
                "blocker": exc.message,
                **exc.details,
                "ephemeral_local_directory": str(candidate_dir)
                if "candidate_dir" in locals()
                else None,
            }
        )
        return 1

    _emit(
        {
            "ok": True,
            "phase": "complete",
            "rebuild_stdout": rebuild.stdout,
            "generation_stdout": generation.stdout,
            "ephemeral_local_directory": str(candidate_dir),
            "durable_artifacts": {
                "bucket": durable["bucket"],
                "prefix": durable["prefix"],
                "object_keys": durable["object_keys"],
                "objects": durable["objects"],
            },
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
