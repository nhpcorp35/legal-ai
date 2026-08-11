#!/usr/bin/env python3
"""Rebuild Case-00 derived artifacts from B2, generate one candidate, upload to B2.

This wrapper runs rebuild + generation in the same checkout, then uploads the
four finalized candidate artifacts to Backblaze B2. Local --candidate-output-root
paths (including /tmp) are ephemeral only; durable handoff is verified B2 object
keys under the canonical candidate prefix.

Question staging downloads the allowlisted canonical attorney-review markdown
packet from B2, verifies size and SHA-256, and extracts ``## QN.`` headings into
runner-local questions.json without logging packet or question body text.

Production Q1 requires an externally supplied acceptance-contract object key,
expected content SHA-256, and benchmark identity (CLI flags or environment /
secrets). The generator fails closed before model generation when the contract
is absent, invalid, identity-mismatched, or hash-mismatched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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

# Canonical private attorney-review markdown packet (B2 only; never commit body).
CANONICAL_ATTORNEY_REVIEW_PACKET_OBJECT_KEY = (
    "Benchmarks/Case-00-Triborough/derived/attorney-feedback-eval/"
    "attorney-reviews/review-20260802-2122f82dafe3/"
    "attorney_review_packet_02-original.md"
)
CANONICAL_ATTORNEY_REVIEW_PACKET_SIZE = 57278
CANONICAL_ATTORNEY_REVIEW_PACKET_SHA256 = (
    "ce7e3a25b22ec23822aec4dcd317b1df38ce6c85b59f684f45f3bdb811316d86"
)

# Production acceptance-contract pins (prefer secrets / env; never commit values).
ACCEPTANCE_CONTRACT_OBJECT_KEY_ENV = "ACCEPTANCE_CONTRACT_OBJECT_KEY"
ACCEPTANCE_CONTRACT_CONTENT_SHA256_ENV = "ACCEPTANCE_CONTRACT_CONTENT_SHA256"
ACCEPTANCE_CONTRACT_BENCHMARK_ID_ENV = "ACCEPTANCE_CONTRACT_BENCHMARK_ID"

_QUESTION_HEADING_RE = re.compile(
    r"^## (Q[1-9][0-9]*)\.\s+(.+?)\s*$",
    re.MULTILINE,
)


class DurableUploadError(Exception):
    """Fail-closed durable upload / verification error (never embeds secrets)."""

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class AcceptanceContractConfigError(Exception):
    """Fail-closed missing/invalid production acceptance-contract configuration."""

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class PacketStagingError(Exception):
    """Fail-closed canonical packet download / verify / extract error.

    Never embeds packet body or question text in ``message`` / ``details``.
    """

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


def verify_canonical_packet_bytes(
    payload: bytes,
    *,
    expected_size: int = CANONICAL_ATTORNEY_REVIEW_PACKET_SIZE,
    expected_sha256: str = CANONICAL_ATTORNEY_REVIEW_PACKET_SHA256,
) -> str:
    """Verify packet size and SHA-256; fail closed on any mismatch.

    Returns the computed hex digest on success. Does not log or return payload.
    """
    if not isinstance(payload, (bytes, bytearray)):
        raise PacketStagingError(
            "canonical packet payload must be bytes",
            payload_type=type(payload).__name__,
        )
    actual_size = len(payload)
    if actual_size != int(expected_size):
        raise PacketStagingError(
            "canonical packet size mismatch",
            expected_size=int(expected_size),
            actual_size=actual_size,
        )
    digest = hashlib.sha256(bytes(payload)).hexdigest()
    expected = str(expected_sha256 or "").strip().lower()
    if digest != expected:
        raise PacketStagingError(
            "canonical packet sha256 mismatch",
            expected_sha256=expected,
            actual_sha256=digest,
        )
    return digest


def extract_question_heading_from_markdown(markdown: str, question_id: str) -> str:
    """Extract the ``## QN. <text>`` heading for ``question_id``; fail closed."""
    qid = str(question_id or "").strip()
    if not qid:
        raise PacketStagingError("question_id must be non-empty for packet staging")
    if not isinstance(markdown, str):
        raise PacketStagingError(
            "packet markdown must be a string",
            markdown_type=type(markdown).__name__,
        )
    matched: dict[str, str] = {}
    for found_id, heading in _QUESTION_HEADING_RE.findall(markdown):
        text = heading.strip()
        if not text:
            continue
        # First heading wins for a given id (deterministic, fail-closed duplicates).
        if found_id not in matched:
            matched[found_id] = text
    if qid not in matched:
        raise PacketStagingError(
            "requested question heading missing from canonical packet",
            question_id=qid,
        )
    return matched[qid]


def write_staged_questions_json(
    case_root: Path,
    question_id: str,
    question_text: str,
) -> Path:
    """Write runner-local ``derived/question-text/questions.json`` for one question."""
    qid = str(question_id or "").strip()
    text = str(question_text or "").strip()
    if not qid:
        raise PacketStagingError("question_id must be non-empty for questions.json")
    if not text:
        raise PacketStagingError(
            "question text must be non-empty for questions.json",
            question_id=qid,
        )
    destination = (
        Path(case_root) / "derived" / "question-text" / "questions.json"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps({qid: text}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination.resolve()


def download_allowlisted_packet_bytes(
    *,
    client: Optional[Any] = None,
    config: Optional[rebuild_cli.B2Config] = None,
    environ: Optional[Mapping[str, str]] = None,
    object_key: str = CANONICAL_ATTORNEY_REVIEW_PACKET_OBJECT_KEY,
) -> bytes:
    """Download only the fixed allowlisted canonical packet object from B2."""
    key = str(object_key or "").strip()
    if key != CANONICAL_ATTORNEY_REVIEW_PACKET_OBJECT_KEY:
        raise PacketStagingError(
            "refusing non-allowlisted attorney-review packet object key",
            object_key=key,
        )
    cfg = config if config is not None else rebuild_cli.B2Config.from_env(environ)
    s3 = client if client is not None else rebuild_cli.create_b2_client(cfg)
    try:
        response = s3.get_object(Bucket=cfg.bucket, Key=key)
        body = response["Body"]
        payload = body.read() if hasattr(body, "read") else body
    except PacketStagingError:
        raise
    except Exception as exc:  # noqa: BLE001 — fail closed, no secret echo
        raise PacketStagingError(
            "B2 download failed for canonical attorney-review packet",
            object_key=key,
            error_type=type(exc).__name__,
        ) from exc
    if not isinstance(payload, (bytes, bytearray)):
        raise PacketStagingError(
            "canonical packet B2 body must be bytes",
            payload_type=type(payload).__name__,
        )
    return bytes(payload)


def stage_question_from_canonical_b2_packet(
    *,
    case_root: Path,
    question_id: str,
    client: Optional[Any] = None,
    config: Optional[rebuild_cli.B2Config] = None,
    environ: Optional[Mapping[str, str]] = None,
    expected_size: int = CANONICAL_ATTORNEY_REVIEW_PACKET_SIZE,
    expected_sha256: str = CANONICAL_ATTORNEY_REVIEW_PACKET_SHA256,
) -> dict[str, Any]:
    """Download, verify, extract, and stage one question into questions.json.

    Never prints or returns packet body or question text.
    """
    qid = str(question_id or "").strip()
    if not qid:
        raise PacketStagingError("question_id must be non-empty for packet staging")
    payload = download_allowlisted_packet_bytes(
        client=client,
        config=config,
        environ=environ,
    )
    digest = verify_canonical_packet_bytes(
        payload,
        expected_size=expected_size,
        expected_sha256=expected_sha256,
    )
    try:
        markdown = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PacketStagingError(
            "canonical packet is not valid utf-8",
            error_type=type(exc).__name__,
        ) from exc
    heading = extract_question_heading_from_markdown(markdown, qid)
    destination = write_staged_questions_json(case_root, qid, heading)
    return {
        "ok": True,
        "question_id": qid,
        "object_key": CANONICAL_ATTORNEY_REVIEW_PACKET_OBJECT_KEY,
        "size": int(expected_size),
        "sha256": digest,
        "questions_json": str(destination),
    }


def candidate_artifact_names(question_id: str) -> tuple[str, ...]:
    """Return the four durable candidate basenames for a question id.

    Q1 keeps the historical filenames; Q2+ use ``{question_id}_candidate_answer.*``.
    """
    qid = str(question_id or "").strip()
    if not qid:
        raise DurableUploadError("question_id must be non-empty for candidate artifacts")
    return (
        f"{qid}_candidate_answer.json",
        f"{qid}_candidate_answer.md",
        "generation_manifest.json",
        "model_input_audit.json",
    )


# Historical Q1 tuple retained for callers/tests that pin the classic names.
CANDIDATE_ARTIFACT_NAMES = candidate_artifact_names("Q1")


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


def _env_strip(environ: Mapping[str, str], name: str) -> str:
    return str(environ.get(name, "") or "").strip()


def resolve_production_acceptance_contract(
    *,
    question_id: str,
    object_key: Optional[str] = None,
    content_sha256: Optional[str] = None,
    benchmark_id: Optional[str] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> dict[str, str]:
    """Require external acceptance-contract object key, SHA-256, and identities.

    Values may come from CLI flags or environment/secrets. Benchmark and
    question identities are passed explicitly — never inferred from private
    corpus contents. Does not read or return contract body bytes.
    """
    env = os.environ if environ is None else environ
    qid = str(question_id or "").strip()
    key = (object_key or _env_strip(env, ACCEPTANCE_CONTRACT_OBJECT_KEY_ENV)).strip()
    sha = (
        content_sha256 or _env_strip(env, ACCEPTANCE_CONTRACT_CONTENT_SHA256_ENV)
    ).strip()
    bench = (
        benchmark_id or _env_strip(env, ACCEPTANCE_CONTRACT_BENCHMARK_ID_ENV)
    ).strip()

    missing: list[str] = []
    if not key:
        missing.append("object_key")
    if not sha:
        missing.append("content_sha256")
    if not bench:
        missing.append("benchmark_id")
    if not qid:
        missing.append("question_id")
    if missing:
        raise AcceptanceContractConfigError(
            "production Q1 requires externally supplied acceptance-contract "
            "object key, content SHA-256, benchmark id, and question id",
            missing=missing,
        )
    return {
        "object_key": key,
        "content_sha256": sha,
        "benchmark_id": bench,
        "question_id": qid,
    }


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
    *,
    question_id: str = "Q1",
) -> str:
    normalized_prefix = normalize_candidate_b2_prefix(prefix)
    base = (candidate_basename or "").strip().replace("\\", "/")
    name = (filename or "").strip().replace("\\", "/")
    if not base or "/" in base or base in (".", ".."):
        raise DurableUploadError(
            "candidate directory basename is unsafe or empty",
            candidate_basename=candidate_basename,
        )
    allowed = candidate_artifact_names(question_id)
    if name not in allowed:
        raise DurableUploadError(
            "refusing to upload unexpected candidate artifact name",
            filename=filename,
            allowed=list(allowed),
            question_id=str(question_id or "").strip(),
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
    question_id: str = "Q1",
) -> dict[str, Any]:
    """Upload the four finalized artifacts and verify each with head_object.

    Local ``candidate_dir`` is treated as ephemeral. Success requires remote
    verification of every object; missing or size-mismatched objects fail closed.
    Artifact basenames follow ``candidate_artifact_names(question_id)`` so Q1
    keeps historical names while Q2+ use question-aware filenames.
    """
    cfg = config if config is not None else rebuild_cli.B2Config.from_env(environ)
    s3 = client if client is not None else rebuild_cli.create_b2_client(cfg)
    normalized_prefix = normalize_candidate_b2_prefix(prefix)
    candidate_path = Path(candidate_dir).resolve()
    basename = candidate_path.name
    artifact_names = candidate_artifact_names(question_id)

    objects: list[dict[str, Any]] = []
    for filename in artifact_names:
        local_path = candidate_path / filename
        if not local_path.is_file():
            raise DurableUploadError(
                f"required candidate artifact missing before upload: {filename}",
                path=str(local_path),
            )
        expected_size = local_path.stat().st_size
        object_key = build_candidate_object_key(
            normalized_prefix,
            basename,
            filename,
            question_id=question_id,
        )
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

    if len(objects) != len(artifact_names):
        raise DurableUploadError(
            "durable upload incomplete; refusing success",
            uploaded=len(objects),
            required=len(artifact_names),
        )

    return {
        "bucket": cfg.bucket,
        "prefix": normalized_prefix,
        "candidate_basename": basename,
        "question_id": str(question_id or "").strip(),
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
    parser.add_argument(
        "--acceptance-contract-object-key",
        default=None,
        help=(
            "Required private acceptance-contract B2 object key "
            f"(or set {ACCEPTANCE_CONTRACT_OBJECT_KEY_ENV})."
        ),
    )
    parser.add_argument(
        "--acceptance-contract-content-sha256",
        default=None,
        help=(
            "Required expected acceptance-contract content SHA-256 "
            f"(or set {ACCEPTANCE_CONTRACT_CONTENT_SHA256_ENV})."
        ),
    )
    parser.add_argument(
        "--acceptance-contract-benchmark-id",
        default=None,
        help=(
            "Required explicit benchmark identity for the acceptance contract "
            f"(or set {ACCEPTANCE_CONTRACT_BENCHMARK_ID_ENV})."
        ),
    )
    args = parser.parse_args(argv)

    try:
        acceptance = resolve_production_acceptance_contract(
            question_id=args.question_id,
            object_key=args.acceptance_contract_object_key,
            content_sha256=args.acceptance_contract_content_sha256,
            benchmark_id=args.acceptance_contract_benchmark_id,
        )
    except AcceptanceContractConfigError as exc:
        _emit(
            {
                "ok": False,
                "phase": "acceptance_contract",
                "blocker": exc.message,
                **exc.details,
            }
        )
        return 1

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
            acceptance["question_id"],
            "--required-commit",
            args.required_commit,
            "--candidate-output-root",
            args.candidate_output_root,
            "--authorize-private-evidence-transmission",
            AUTHORIZATION_ACKNOWLEDGEMENT,
            "--generation-only",
            "--repo-root",
            str(repo_root),
            "--acceptance-contract-object-key",
            acceptance["object_key"],
            "--acceptance-contract-content-sha256",
            acceptance["content_sha256"],
            "--acceptance-contract-benchmark-id",
            acceptance["benchmark_id"],
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
            question_id=acceptance["question_id"],
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
