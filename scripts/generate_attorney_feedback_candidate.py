#!/usr/bin/env python3
"""Durable attorney-feedback candidate generation CLI.

Thin orchestration over existing production retrieval / evidence-packet /
serialization / drafting / validation / bounded synthesis-patch repair /
hashing helpers.
Does not call a live model unless the host process already has provider
credentials and an injectable model_call is not supplied.
Does not load gold, provisional, original answers, attorney feedback,
prior candidate prose, or evaluation artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import matter_builder as mb  # noqa: E402
import complaint_structure as cs  # noqa: E402
from engines import drafting_engine as de  # noqa: E402
from engines.q2_production_evidence_diagnostics import (  # noqa: E402
    DIAGNOSTIC_RESULT_KEY,
    build_q2_production_evidence_diagnostics,
)
import acceptance_contract as ac  # noqa: E402
import rebuild_case00_derived as rebuild_cli  # noqa: E402

AUTHORIZATION_ACK = "I_AUTHORIZE_PRIVATE_EVIDENCE_TRANSMISSION_TO_MODEL_PROVIDER"

# Production acceptance-contract object pin (env / secrets; never commit private keys).
ACCEPTANCE_CONTRACT_OBJECT_KEY_ENV = "ACCEPTANCE_CONTRACT_OBJECT_KEY"
ACCEPTANCE_CONTRACT_CONTENT_SHA256_ENV = "ACCEPTANCE_CONTRACT_CONTENT_SHA256"
ACCEPTANCE_CONTRACT_BENCHMARK_ID_ENV = "ACCEPTANCE_CONTRACT_BENCHMARK_ID"
ACCEPTANCE_CONTRACT_ENV_NAMES = (
    ACCEPTANCE_CONTRACT_OBJECT_KEY_ENV,
    ACCEPTANCE_CONTRACT_CONTENT_SHA256_ENV,
    ACCEPTANCE_CONTRACT_BENCHMARK_ID_ENV,
)

# Privacy-safe Q2 validated structured-claims handoff (preflight → generation).
VALIDATED_CLAIMS_SCHEMA_VERSION = "q2_validated_structured_claims.v1"
VALIDATED_CLAIMS_PATH_ENV = "Q2_VALIDATED_CLAIMS_PATH"
VALIDATED_CLAIMS_SHA256_ENV = "Q2_VALIDATED_CLAIMS_SHA256"
_VALIDATED_RELIEF_CATEGORIES = (
    "rescission_void_ab_initio",
    "no_defense_or_indemnity",
    "catch_all_relief",
)
_SAFE_PAGE_OR_REASON_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

# Trusted Railway deployment metadata (present when .git is stripped at runtime).
RAILWAY_GIT_COMMIT_SHA = "RAILWAY_GIT_COMMIT_SHA"
RAILWAY_GIT_REPO_OWNER = "RAILWAY_GIT_REPO_OWNER"
RAILWAY_GIT_REPO_NAME = "RAILWAY_GIT_REPO_NAME"
RAILWAY_GIT_BRANCH = "RAILWAY_GIT_BRANCH"
RAILWAY_PROVENANCE_ENV_VARS = (
    RAILWAY_GIT_COMMIT_SHA,
    RAILWAY_GIT_REPO_OWNER,
    RAILWAY_GIT_REPO_NAME,
    RAILWAY_GIT_BRANCH,
)

# Expected repository identity for Railway provenance checks.
EXPECTED_REPO_OWNER = "nhpcorp35"
EXPECTED_REPO_NAME = "legal-ai"
EXPECTED_REPO_BRANCH = "main"

# Path substrings that must never be opened as generation inputs.
_PROTECTED_PATH_MARKERS = (
    "attorney-gold-benchmark",
    "provisional-gold-answers",
    "attorney-approved-gold-answers",
    "attorney_gold_labels",
    "attorney-feedback-eval/",
    "case00_attorney_feedback_eval",
    "candidate-answers/",
    "candidates/eval_",
)

ModelCall = Callable[[str, str], Any]


class GenerationError(Exception):
    """Machine-readable generation failure."""

    def __init__(self, blocker: str, **details: Any) -> None:
        super().__init__(blocker)
        self.blocker = blocker
        self.details = details


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _canonical_json_bytes(obj: Any) -> bytes:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_validated_claims_bytes(doc: Mapping[str, Any]) -> bytes:
    """Deterministic canonical JSON bytes for validated structured claims."""
    return _canonical_json_bytes(doc)


def validated_claims_sha256(doc: Mapping[str, Any]) -> str:
    """SHA-256 hex digest of canonical validated structured claims JSON."""
    return _sha256_bytes(canonical_validated_claims_bytes(doc))


def build_validated_structured_claims(
    *,
    benchmark_id: str,
    question_id: str,
    acceptance_contract_object_key: str,
    acceptance_contract_content_sha256: str,
    claims: Sequence[Mapping[str, Any]],
    schema_version: str = VALIDATED_CLAIMS_SCHEMA_VERSION,
) -> dict[str, Any]:
    """Assemble a privacy-safe validated claims object (no private source text)."""
    normalized: list[dict[str, Any]] = []
    for raw in claims:
        if not isinstance(raw, Mapping):
            raise GenerationError(
                "validated_claims_malformed_claim_row",
                reason_code="validated_claims_malformed_claim_row",
                finalized=False,
            )
        category = str(raw.get("category") or "").strip()
        page_id = str(raw.get("page_id") or "").strip() or None
        reason = str(raw.get("selection_reason_code") or "").strip()
        # Explicitly omit evidence_snippet / free text — privacy-safe handoff only.
        row: dict[str, Any] = {
            "category": category,
            "supported": bool(raw.get("supported")),
            "page_id": page_id,
            "nyscef_document_number": raw.get("nyscef_document_number"),
            "pdf_page": raw.get("pdf_page"),
            "selection_reason_code": reason,
        }
        normalized.append(row)
    return {
        "schema_version": str(schema_version),
        "benchmark_id": str(benchmark_id or "").strip(),
        "question_id": str(question_id or "").strip(),
        "acceptance_contract_object_key": str(
            acceptance_contract_object_key or ""
        ).strip(),
        "acceptance_contract_content_sha256": str(
            acceptance_contract_content_sha256 or ""
        )
        .strip()
        .lower(),
        "claims": normalized,
    }


def verified_relief_claims_from_validated(
    doc: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Map validated handoff claims into finalizer/audit claim rows."""
    out: list[dict[str, Any]] = []
    for raw in doc.get("claims") or []:
        if not isinstance(raw, Mapping):
            continue
        out.append(
            {
                "category": str(raw.get("category") or ""),
                "supported": bool(raw.get("supported")),
                "page_id": str(raw.get("page_id") or "").strip() or None,
                "nyscef_document_number": raw.get("nyscef_document_number"),
                "pdf_page": raw.get("pdf_page"),
                # Empty by design: handoff never carries private OCR snippets.
                "evidence_snippet": "",
                "selection_reason_code": str(
                    raw.get("selection_reason_code") or ""
                ).strip(),
            }
        )
    return out


def validated_claims_safe_provenance(doc: Mapping[str, Any]) -> dict[str, Any]:
    """Privacy-safe schema/hash/identity record for manifest/audit (no claim text)."""
    return {
        "validated_claims_schema_version": str(doc.get("schema_version") or ""),
        "validated_claims_sha256": validated_claims_sha256(doc),
        "validated_claims_benchmark_id": str(doc.get("benchmark_id") or ""),
        "validated_claims_question_id": str(doc.get("question_id") or ""),
        "validated_claims_acceptance_contract_object_key": str(
            doc.get("acceptance_contract_object_key") or ""
        ),
        "validated_claims_acceptance_contract_content_sha256": str(
            doc.get("acceptance_contract_content_sha256") or ""
        ),
        "validated_claims_category_count": len(list(doc.get("claims") or [])),
    }


def _fail_validated_claims(reason_code: str, **details: Any) -> None:
    raise GenerationError(
        f"Validated structured claims rejected: {reason_code}",
        reason_code=reason_code,
        finalized=False,
        **details,
    )


def assert_validated_structured_claims_shape(doc: Mapping[str, Any]) -> None:
    """Fail closed on malformed / duplicate / unsupported / citation-less claims."""
    if not isinstance(doc, Mapping):
        _fail_validated_claims("validated_claims_not_object")
    schema = str(doc.get("schema_version") or "")
    if schema != VALIDATED_CLAIMS_SCHEMA_VERSION:
        _fail_validated_claims(
            "validated_claims_schema_mismatch",
            schema_version=schema,
        )
    for field in (
        "benchmark_id",
        "question_id",
        "acceptance_contract_object_key",
        "acceptance_contract_content_sha256",
    ):
        if not str(doc.get(field) or "").strip():
            _fail_validated_claims(
                "validated_claims_identity_missing",
                field=field,
            )
    contract_sha = str(doc.get("acceptance_contract_content_sha256") or "").strip()
    if not _SHA256_HEX_RE.fullmatch(contract_sha.lower()):
        _fail_validated_claims("validated_claims_contract_sha_malformed")

    claims = doc.get("claims")
    if not isinstance(claims, list) or not claims:
        _fail_validated_claims("validated_claims_missing")

    seen: set[str] = set()
    by_cat: dict[str, Mapping[str, Any]] = {}
    for raw in claims:
        if not isinstance(raw, Mapping):
            _fail_validated_claims("validated_claims_malformed_claim_row")
        category = str(raw.get("category") or "").strip()
        if category not in _VALIDATED_RELIEF_CATEGORIES:
            _fail_validated_claims(
                "validated_claims_unknown_category",
                category=category,
            )
        if category in seen:
            _fail_validated_claims(
                "validated_claims_duplicate_category",
                category=category,
            )
        seen.add(category)
        by_cat[category] = raw
        if not bool(raw.get("supported")):
            _fail_validated_claims(
                "validated_claims_unsupported_required",
                category=category,
            )
        page_id = str(raw.get("page_id") or "").strip()
        if not page_id or not _SAFE_PAGE_OR_REASON_RE.fullmatch(page_id):
            _fail_validated_claims(
                "validated_claims_citation_missing",
                category=category,
            )
        reason = str(raw.get("selection_reason_code") or "").strip()
        if not reason or not _SAFE_PAGE_OR_REASON_RE.fullmatch(reason):
            _fail_validated_claims(
                "validated_claims_reason_missing",
                category=category,
            )
        # Reject private free-text fields if a caller smuggles them in.
        for banned in ("evidence_snippet", "page_text", "excerpt", "proposed_answer"):
            if banned in raw and str(raw.get(banned) or "").strip():
                _fail_validated_claims(
                    "validated_claims_private_text_rejected",
                    field=banned,
                    category=category,
                )

    for required in _VALIDATED_RELIEF_CATEGORIES:
        if required not in by_cat:
            _fail_validated_claims(
                "validated_claims_required_category_missing",
                category=required,
            )


def load_and_verify_validated_claims(
    path: Path,
    *,
    expected_sha256: str,
    benchmark_id: str,
    question_id: str,
    acceptance_contract_object_key: str,
    acceptance_contract_content_sha256: str,
) -> dict[str, Any]:
    """Load validated claims, verify canonical hash + identities, fail closed."""
    expected = str(expected_sha256 or "").strip().lower()
    if not expected or not _SHA256_HEX_RE.fullmatch(expected):
        _fail_validated_claims("validated_claims_expected_sha_malformed")
    claims_path = Path(path)
    if not claims_path.is_file():
        _fail_validated_claims(
            "validated_claims_path_missing",
            path_kind="validated_claims",
        )
    try:
        raw = json.loads(claims_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        _fail_validated_claims("validated_claims_unreadable")
    if not isinstance(raw, dict):
        _fail_validated_claims("validated_claims_not_object")

    assert_validated_structured_claims_shape(raw)
    # Re-canonicalize so key order / whitespace cannot bypass integrity.
    canonical_doc = build_validated_structured_claims(
        benchmark_id=str(raw.get("benchmark_id") or ""),
        question_id=str(raw.get("question_id") or ""),
        acceptance_contract_object_key=str(
            raw.get("acceptance_contract_object_key") or ""
        ),
        acceptance_contract_content_sha256=str(
            raw.get("acceptance_contract_content_sha256") or ""
        ),
        claims=list(raw.get("claims") or []),
        schema_version=str(raw.get("schema_version") or ""),
    )
    actual_sha = validated_claims_sha256(canonical_doc)
    if actual_sha != expected:
        _fail_validated_claims(
            "validated_claims_hash_mismatch",
            expected_sha256_prefix=expected[:12],
            actual_sha256_prefix=actual_sha[:12],
        )

    if str(canonical_doc.get("benchmark_id") or "") != str(benchmark_id or "").strip():
        _fail_validated_claims("validated_claims_benchmark_mismatch")
    if str(canonical_doc.get("question_id") or "") != str(question_id or "").strip():
        _fail_validated_claims("validated_claims_question_mismatch")
    if str(canonical_doc.get("acceptance_contract_object_key") or "") != str(
        acceptance_contract_object_key or ""
    ).strip():
        _fail_validated_claims("validated_claims_contract_key_mismatch")
    if str(canonical_doc.get("acceptance_contract_content_sha256") or "").lower() != str(
        acceptance_contract_content_sha256 or ""
    ).strip().lower():
        _fail_validated_claims("validated_claims_contract_sha_mismatch")

    return canonical_doc


def resolve_validated_claims_handoff_args(
    *,
    path: Optional[str] = None,
    sha256: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> tuple[Optional[Path], Optional[str]]:
    """Resolve optional validated-claims path + expected SHA (both or neither)."""
    environ = env if env is not None else os.environ
    resolved_path = (path or str(environ.get(VALIDATED_CLAIMS_PATH_ENV) or "")).strip()
    resolved_sha = (
        sha256 or str(environ.get(VALIDATED_CLAIMS_SHA256_ENV) or "")
    ).strip()
    if not resolved_path and not resolved_sha:
        return None, None
    if not resolved_path or not resolved_sha:
        _fail_validated_claims(
            "validated_claims_handoff_incomplete",
            has_path=bool(resolved_path),
            has_sha256=bool(resolved_sha),
        )
    return Path(resolved_path), resolved_sha.lower()


def _normalize_ref_names(ref_name: str) -> tuple[str, set[str]]:
    """Return (path under .git/refs/, packed-refs name candidates)."""
    cleaned = ref_name.strip()
    if cleaned.startswith("refs/"):
        under_refs = cleaned[len("refs/") :]
        packed = {cleaned}
    else:
        under_refs = cleaned
        packed = {cleaned, f"refs/{cleaned}"}
    return under_refs, packed


def _read_git_ref(repo_root: Path, ref_name: str) -> Optional[str]:
    """Read a git ref from the filesystem (no git subprocess).

    Loose refs live under ``.git/refs/...`` (never directly under ``.git/``).
    Packed refs are matched by full ``refs/...`` name.
    """
    under_refs, packed_names = _normalize_ref_names(ref_name)
    ref_path = repo_root / ".git" / "refs" / under_refs
    if ref_path.is_file():
        return ref_path.read_text(encoding="utf-8").strip()
    packed = repo_root / ".git" / "packed-refs"
    if not packed.is_file():
        return None
    for line in packed.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("^"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[-1] in packed_names:
            return parts[0].strip()
    return None


def read_checked_out_commit(repo_root: Path) -> Optional[str]:
    head_path = repo_root / ".git" / "HEAD"
    if not head_path.is_file():
        return None
    head = head_path.read_text(encoding="utf-8").strip()
    if head.startswith("ref:"):
        ref = head.split(":", 1)[1].strip()
        # Prefer the full refs/... path; also try without the refs/ prefix.
        return _read_git_ref(repo_root, ref) or (
            _read_git_ref(repo_root, ref[len("refs/") :])
            if ref.startswith("refs/")
            else None
        )
    return head or None


def read_origin_main_commit(repo_root: Path) -> Optional[str]:
    return _read_git_ref(repo_root, "refs/remotes/origin/main") or _read_git_ref(
        repo_root, "remotes/origin/main"
    )


def is_commit_ancestor_of_origin_main(
    repo_root: Path, required_commit: str, origin_main: Optional[str]
) -> bool:
    """True when ``required_commit`` is an ancestor of ``origin/main`` (inclusive).

    Equality is treated as ancestry without spawning git. Otherwise uses
    ``git merge-base --is-ancestor`` and fails closed on any error.
    """
    if not required_commit or not origin_main:
        return False
    if required_commit == origin_main:
        return True
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "merge-base",
                "--is-ancestor",
                required_commit,
                "origin/main",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return False
    return result.returncode == 0


def git_metadata_available(repo_root: Path) -> bool:
    """True when a usable ``.git`` directory is present."""
    git_dir = repo_root / ".git"
    return git_dir.is_dir() or git_dir.is_file()


def read_railway_deployment_provenance() -> dict[str, Optional[str]]:
    """Read trusted Railway git provenance env vars (may be incomplete)."""
    return {
        "commit": (os.environ.get(RAILWAY_GIT_COMMIT_SHA) or "").strip() or None,
        "owner": (os.environ.get(RAILWAY_GIT_REPO_OWNER) or "").strip() or None,
        "name": (os.environ.get(RAILWAY_GIT_REPO_NAME) or "").strip() or None,
        "branch": (os.environ.get(RAILWAY_GIT_BRANCH) or "").strip() or None,
    }


def _normalize_branch_name(branch: str) -> str:
    value = branch.strip()
    if value.startswith("refs/heads/"):
        return value[len("refs/heads/") :]
    return value


def assert_railway_provenance_matches(
    required_commit: str,
    *,
    expected_owner: str = EXPECTED_REPO_OWNER,
    expected_name: str = EXPECTED_REPO_NAME,
    expected_branch: str = EXPECTED_REPO_BRANCH,
) -> dict:
    """Fail-closed validation of Railway deployment metadata."""
    provenance = read_railway_deployment_provenance()
    missing = [
        name
        for name, key in (
            (RAILWAY_GIT_COMMIT_SHA, "commit"),
            (RAILWAY_GIT_REPO_OWNER, "owner"),
            (RAILWAY_GIT_REPO_NAME, "name"),
            (RAILWAY_GIT_BRANCH, "branch"),
        )
        if not provenance.get(key)
    ]
    if missing:
        raise GenerationError(
            "Commit provenance missing: .git unavailable and Railway deployment "
            f"metadata incomplete (missing {', '.join(missing)})",
            required_commit=required_commit,
            railway_provenance=provenance,
            missing_env=missing,
            provenance_source="railway_deployment_metadata",
        )

    commit = provenance["commit"]
    owner = provenance["owner"]
    name = provenance["name"]
    branch = _normalize_branch_name(provenance["branch"] or "")

    if commit != required_commit:
        raise GenerationError(
            "Railway deployment commit does not match required commit "
            f"{required_commit}; RAILWAY_GIT_COMMIT_SHA={commit!r}",
            checkout_commit=commit,
            origin_main_commit=commit,
            required_commit=required_commit,
            railway_provenance=provenance,
            provenance_source="railway_deployment_metadata",
        )
    if (owner or "").lower() != expected_owner.lower():
        raise GenerationError(
            "Railway deployment repository owner mismatch: "
            f"expected {expected_owner!r}, got {owner!r}",
            checkout_commit=commit,
            required_commit=required_commit,
            railway_provenance=provenance,
            expected_owner=expected_owner,
            provenance_source="railway_deployment_metadata",
        )
    if (name or "").lower() != expected_name.lower():
        raise GenerationError(
            "Railway deployment repository name mismatch: "
            f"expected {expected_name!r}, got {name!r}",
            checkout_commit=commit,
            required_commit=required_commit,
            railway_provenance=provenance,
            expected_name=expected_name,
            provenance_source="railway_deployment_metadata",
        )
    if branch != expected_branch:
        raise GenerationError(
            "Railway deployment branch mismatch: "
            f"expected {expected_branch!r}, got {branch!r}",
            checkout_commit=commit,
            required_commit=required_commit,
            railway_provenance=provenance,
            expected_branch=expected_branch,
            provenance_source="railway_deployment_metadata",
        )

    return {
        "checkout_commit": commit,
        "origin_main_commit": commit,
        "required_commit": required_commit,
        "provenance_source": "railway_deployment_metadata",
        "railway_repo_owner": owner,
        "railway_repo_name": name,
        "railway_branch": branch,
    }


def assert_commits_match(repo_root: Path, required_commit: str) -> dict:
    """Verify checkout matches ``required_commit``; fail closed.

    Prefer normal ``.git`` metadata when present. When ``.git`` is absent
    (typical Railway runtime image), validate trusted Railway deployment
    metadata instead. Missing or mismatched provenance always raises.
    """
    if git_metadata_available(repo_root):
        head = read_checked_out_commit(repo_root)
        origin_main = read_origin_main_commit(repo_root)
        if head != required_commit:
            raise GenerationError(
                "HEAD is not exactly the required commit "
                f"{required_commit}; HEAD={head!r} origin/main={origin_main!r}",
                checkout_commit=head,
                origin_main_commit=origin_main,
                required_commit=required_commit,
                provenance_source="git_metadata",
            )
        if not is_commit_ancestor_of_origin_main(repo_root, required_commit, origin_main):
            raise GenerationError(
                "required commit is not an ancestor of origin/main "
                f"{required_commit}; HEAD={head!r} origin/main={origin_main!r}",
                checkout_commit=head,
                origin_main_commit=origin_main,
                required_commit=required_commit,
                provenance_source="git_metadata",
            )
        return {
            "checkout_commit": head,
            "origin_main_commit": origin_main,
            "required_commit": required_commit,
            "provenance_source": "git_metadata",
        }

    provenance = read_railway_deployment_provenance()
    if any(provenance.values()):
        return assert_railway_provenance_matches(required_commit)

    raise GenerationError(
        "Commit provenance missing: no .git metadata and no Railway deployment "
        f"metadata ({', '.join(RAILWAY_PROVENANCE_ENV_VARS)})",
        checkout_commit=None,
        origin_main_commit=None,
        required_commit=required_commit,
        provenance_source=None,
    )


def _ensure_not_protected(path: Path, *, role: str) -> Path:
    resolved = path.resolve()
    text = str(resolved).replace("\\", "/")
    lower = text.lower()
    for marker in _PROTECTED_PATH_MARKERS:
        # Allow writing under candidate-output-root even when nested beneath
        # attorney-feedback-eval; only block using those trees as inputs.
        if role == "input" and marker.lower() in lower:
            raise GenerationError(
                f"Refusing to load protected reference material as {role}: {resolved}",
                path=str(resolved),
                marker=marker,
            )
    return resolved


def _load_json(path: Path, *, role: str = "input") -> Any:
    safe = _ensure_not_protected(path, role=role)
    if not safe.is_file():
        raise GenerationError(f"Required input missing: {safe}")
    return json.loads(safe.read_text(encoding="utf-8"))


def resolve_case_input_paths(case_root: Path) -> dict[str, Path]:
    root = case_root.resolve()
    return {
        "page_records": root
        / "derived"
        / "page-extraction"
        / "canonical_page_records.json",
        "exhibit_map": root
        / "derived"
        / "exhibit-segmentation"
        / "filing_exhibit_map.json",
        "case_map": root / "derived" / "case-map" / "case_map.json",
        "complaint_structure": root
        / "derived"
        / "complaint-structure"
        / "complaint_structure_map.json",
        "question_packet": root
        / "derived"
        / "attorney-review-packet-02-live"
        / "attorney_review_packet_02.json",
        "question_text_file": root / "derived" / "question-text" / "questions.json",
    }


def load_question_text_only(case_root: Path, question_id: str) -> str:
    """Load only the question text for question_id; discard all other fields."""
    paths = resolve_case_input_paths(case_root)
    # Prefer a questions-only JSON (id -> text or list of {question_id,text}).
    qfile = paths["question_text_file"]
    if qfile.is_file():
        raw = _load_json(qfile, role="input")
        if isinstance(raw, dict) and question_id in raw:
            text = raw[question_id]
            if isinstance(text, dict):
                text = text.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict) and item.get("question_id") == question_id:
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        return text.strip()
        raise GenerationError(
            f"Question {question_id!r} text missing from questions-only file",
            path=str(qfile),
        )

    packet_path = paths["question_packet"]
    data = _load_json(packet_path, role="input")
    text = None
    for question in data.get("questions") or []:
        if not isinstance(question, dict):
            continue
        if question.get("question_id") == question_id:
            text = question.get("text")
            break
    # Drop packet payload immediately; never retain answers/feedback fields.
    del data
    if not isinstance(text, str) or not text.strip():
        raise GenerationError(
            f"Question {question_id!r} text field missing from permitted inputs",
            path=str(packet_path),
        )
    return text.strip()


def load_permitted_case_inputs(
    case_root: Path,
    question_id: str,
    *,
    inventory_path: Optional[Path] = None,
    repo_root: Optional[Path] = None,
) -> dict[str, Any]:
    paths = resolve_case_input_paths(case_root)
    question_text = load_question_text_only(case_root, question_id)
    page_wrap = _load_json(paths["page_records"], role="input")
    exhibit_map = _load_json(paths["exhibit_map"], role="input")
    case_map_wrap = _load_json(paths["case_map"], role="input")
    case_map = case_map_wrap.get("case_map")
    if not isinstance(case_map, dict):
        # Allow either wrapped {"case_map": {...}} or bare case_map object.
        if isinstance(case_map_wrap, dict) and (
            "parties" in case_map_wrap or "nodes" in case_map_wrap or "filings" in case_map_wrap
        ):
            case_map = case_map_wrap
        else:
            raise GenerationError("case_map.json missing usable case_map object")

    # Complaint structure map: degrade explicitly when absent/stale — never fabricate.
    structure_path = paths["complaint_structure"]
    complaint_structure_map = None
    if structure_path.is_file():
        try:
            raw_structure = _load_json(structure_path, role="input")
        except GenerationError:
            raw_structure = None
        complaint_structure_status = cs.structure_map_status(raw_structure)
        if complaint_structure_status.get("ok"):
            complaint_structure_map = raw_structure
    else:
        complaint_structure_status = cs.structure_map_status(None)

    inv_path = inventory_path
    if inv_path is None:
        resolved = mb.resolve_inventory_path(None)
        if resolved is not None:
            inv_path = Path(resolved)
        else:
            root = repo_root or REPO_ROOT
            inv_path = root / "data" / "case-00-triborough" / "nyscef_filing_inventory.json"
    inv_path = _ensure_not_protected(Path(inv_path), role="input")
    inventory = mb.load_nyscef_filing_inventory(inv_path)
    if not inventory:
        raise GenerationError(f"NYSCEF inventory unavailable: {inv_path}")

    return {
        "question_id": question_id,
        "question_text": question_text,
        "page_records": page_wrap,
        "exhibit_map": exhibit_map,
        "case_map": case_map,
        "complaint_structure_map": complaint_structure_map,
        "complaint_structure_status": complaint_structure_status,
        "inventory": inventory,
        "inventory_path": str(inv_path),
        "input_paths": {k: str(v) for k, v in paths.items()},
    }


def _inventory_canonical_filings(inventory: dict) -> list[dict]:
    filings = [
        f for f in inventory.get("filings", []) if f.get("ingest_canonical") is True
    ]
    return sorted(filings, key=lambda f: int(f["nyscef_document_number"]))


def _group_pages_by_filing(pages: list[dict]) -> dict[int, list[dict]]:
    grouped: dict[int, list[dict]] = defaultdict(list)
    for page in pages:
        nyscef = page.get("nyscef_document_number")
        if nyscef is None:
            raise GenerationError(
                "Canonical page record missing nyscef_document_number",
                page_id=page.get("page_id"),
            )
        grouped[int(nyscef)].append(page)
    for doc_no in grouped:
        grouped[doc_no].sort(key=lambda p: int(p["page_number"]))
    return dict(sorted(grouped.items()))


def build_documents_from_permitted_inputs(
    page_wrap: dict,
    inventory: dict,
    exhibit_map: dict,
) -> list[dict]:
    """Assemble retrieval documents from permitted corpus inputs only."""
    pages = page_wrap.get("pages") or []
    grouped = _group_pages_by_filing(pages)
    canonical_filings = _inventory_canonical_filings(inventory)
    exhibit_by_nyscef = {
        int(f["nyscef_document_number"]): f for f in exhibit_map.get("filings") or []
    }
    documents = []
    for entry in canonical_filings:
        doc_no = int(entry["nyscef_document_number"])
        doc_pages = grouped.get(doc_no)
        if not doc_pages:
            raise GenerationError(f"No canonical page records for filing {doc_no}")
        filing_ex = exhibit_by_nyscef.get(doc_no)
        if filing_ex is None:
            raise GenerationError(f"No exhibit-map entry for filing {doc_no}")
        documents.append(
            {
                "filename": entry.get("filename") or doc_pages[0].get("source_filename"),
                "path": doc_pages[0].get("source_path", ""),
                "title": entry.get("filename") or doc_pages[0].get("source_filename"),
                "nyscef_document_number": doc_no,
                "page_count": len(doc_pages),
                "pages": doc_pages,
                "exhibit_segments": list(filing_ex.get("segments") or []),
                "uncertain_exhibit_boundaries": list(
                    filing_ex.get("uncertain_boundaries")
                    or filing_ex.get("uncertain_exhibit_boundaries")
                    or []
                ),
                "sha256": entry.get("sha256"),
                "source": "nyscef_canonical_page_records",
                "include_exhibit_segments": True,
            }
        )
    return documents


def _documents_for_hit_pages(
    merged_hits: list[dict], documents: list[dict]
) -> list[dict]:
    needed_pages: dict[int, set[str]] = defaultdict(set)
    for hit in merged_hits:
        nyscef = hit.get("nyscef_document_number")
        page_id = hit.get("page_id")
        if nyscef is None or not page_id:
            continue
        needed_pages[int(nyscef)].add(page_id)
    subset = []
    for doc in documents:
        nyscef = int(doc["nyscef_document_number"])
        wanted = needed_pages.get(nyscef)
        if not wanted:
            continue
        pages = [p for p in doc.get("pages") or [] if p.get("page_id") in wanted]
        if not pages:
            continue
        subset.append(
            {
                **{k: v for k, v in doc.items() if k != "pages"},
                "pages": pages,
                "page_count": len(pages),
            }
        )
    return subset


def run_production_retrieval(
    documents: list[dict],
    case_map: dict,
    question_text: str,
    *,
    top_k: int = 30,
) -> dict:
    prepared = mb.prepare_documents_for_canonical_retrieval(documents)
    return mb.retrieve_canonical_records(
        prepared,
        question_text,
        case_map=case_map,
        top_k=top_k,
        build_case_map_if_missing=False,
    )


def audit_serialized_model_input(
    question_text: str,
    retrieval: dict,
    *,
    case_map: Optional[dict] = None,
    complaint_structure_map: Optional[dict] = None,
    documents: Optional[list] = None,
) -> dict:
    """Build/audit exact serialized evidence input via production helpers."""
    evidence_packet = de.build_evidence_packet(
        question_text,
        retrieval,
        case_map=case_map,
        exhibit_context=None,
        allowed_sources=[],
        complaint_structure_map=complaint_structure_map,
        documents=documents,
    )
    party_role_intent = de.detect_party_role_question_intent(question_text)
    relief_intent = de.detect_relief_question_intent(question_text)
    user_prompt = de.build_user_prompt(
        evidence_packet,
        party_role_completeness=party_role_intent,
    )
    serialized = de._stable_json(evidence_packet)
    hits = list(evidence_packet.get("retrieval_hits") or [])
    per_page_lengths = {
        h.get("page_id"): len(h.get("excerpt") or "") for h in hits if h.get("page_id")
    }
    expected = (
        de.extract_party_role_expected_attributes(evidence_packet)
        if party_role_intent
        else []
    )
    audit = {
        "question": question_text,
        "party_role_intent": bool(party_role_intent),
        "relief_intent": bool(relief_intent),
        "evidence_page_ids": [h.get("page_id") for h in hits],
        "per_page_serialized_excerpt_lengths": per_page_lengths,
        "total_serialized_evidence_characters": sum(per_page_lengths.values()),
        "serialized_evidence_packet_sha256": _sha256_bytes(serialized.encode("utf-8")),
        "serialized_user_prompt_sha256": _sha256_bytes(user_prompt.encode("utf-8")),
        "expected_attribute_count": len(expected),
        # Backward-compatible legacy field: this is the bounded packet count,
        # not the number of hits returned by production retrieval.
        "retrieval_hit_count": evidence_packet.get("retrieval_hit_count"),
        "upstream_retrieval_hit_count": len(retrieval.get("results") or []),
        "serialized_evidence_page_count": len(hits),
        "complaint_structure_status": evidence_packet.get(
            "complaint_structure_status"
        ),
        "complaint_structure_attached": bool(
            evidence_packet.get("complaint_structure_context")
        ),
        "complaint_relief_routing": retrieval.get("complaint_relief_routing"),
        "retrieval_count_semantics": {
            "upstream_retrieval_hit_count": (
                "Hits returned before evidence-packet materiality and budget filtering."
            ),
            "serialized_evidence_page_count": (
                "Pages serialized into the model evidence packet."
            ),
            "retrieval_hit_count": (
                "Deprecated alias for serialized_evidence_page_count."
            ),
        },
    }
    return {
        "evidence_packet": evidence_packet,
        "user_prompt": user_prompt,
        "party_role_intent": party_role_intent,
        "relief_intent": relief_intent,
        "expected_attributes": expected,
        "audit": audit,
    }


def candidate_content_sha256(candidate: dict) -> str:
    without = {k: v for k, v in candidate.items() if k != "candidate_sha256"}
    return _sha256_bytes(_canonical_json_bytes(without))


_LITERAL_ESCAPE_ARTIFACT_RE = re.compile(r"\\([nrt])")
_MARKDOWN_LIST_LINE_RE = re.compile(r"^\s*(?:[-*]|\d+\.)\s+\S")
_NUMBERED_ITEM_START_RE = re.compile(r"(?=\b\d+\.\s+\S)")


def normalize_proposed_answer_whitespace(text: str) -> str:
    """Documented whitespace normalization for JSON/Markdown answer parity.

    Collapses all Unicode whitespace runs (spaces, tabs, newlines) to a single
    space and strips ends. The JSON candidate ``proposed_answer`` and the
    Markdown ``## Proposed answer`` body must be identical under this function.
    """
    return " ".join(str(text or "").split()).strip()


def _decode_literal_escape_artifacts(text: str) -> str:
    """Replace literal ``\\n`` / ``\\t`` / ``\\r`` sequences with real whitespace.

    Prevents two-character escape artifacts from appearing mid-answer when an
    upstream string carried escaped newlines instead of real line breaks.
    """

    def _repl(match: re.Match[str]) -> str:
        return {"n": "\n", "r": "\n", "t": " "}[match.group(1)]

    return _LITERAL_ESCAPE_ARTIFACT_RE.sub(_repl, str(text or ""))


def _collapse_inline_whitespace(text: str) -> str:
    return " ".join(str(text or "").split())


_CITED_PLEADING_LANGUAGE_QUOTE_RE = re.compile(
    r'as reflected in the cited pleading language:\s*"((?:[^"\\]|\\.)*)"'
    r'(?P<cite>\s*\(\s*page_id\s+[^)]+\))?',
    flags=re.IGNORECASE | re.DOTALL,
)


def _relief_presence_flags(text: str) -> dict[str, bool]:
    """Coarse presence of each relief category in attorney prose (not OCR dumps)."""
    # Strip quoted spans so OCR dumps inside quotes do not count as retained prose.
    stripped = _CITED_PLEADING_LANGUAGE_QUOTE_RE.sub(
        "as reflected in the cited pleading language: \"\"",
        str(text or ""),
    )
    low = stripped.lower()
    return {
        "rescission_void_ab_initio": bool(
            re.search(r"\b(?:rescission|void ab initio)\b", low)
        ),
        "no_defense_or_indemnity": bool(
            re.search(r"\bno defense or indemnity\b", low)
        ),
        "catch_all_relief": bool(
            re.search(r"\bcatch-all requested relief\b", low)
            or re.search(r"\bsuch other and further relief\b", low)
            or re.search(r"\bjust and (?:equitable|proper)\b", low)
        ),
    }


def scrub_unreadable_quoted_excerpts(
    proposed: str,
    *,
    verified_relief_claims: Optional[Sequence[Mapping[str, Any]]] = None,
) -> str:
    """
    Final-serializer defense: drop raw OCR dumps from proposed-answer prose.

    When a ``cited pleading language: "..."`` span fails the shared readability
    gate, run the evidence-selection handoff: retain verified citation/evidence
    identity from the quote, prefer a category-scoped clean excerpt when one
    exists, otherwise emit a concise originating-source paraphrase. Verified
    sibling relief categories carried only inside the rejected quote (for
    example no-defense/no-indemnification) are appended as clean-excerpt or
    paraphrase paragraphs so OCR scrubbing cannot drop supported relief.
    Structured verified relief claims from synthesis are then merged
    independently of displayed quote objects (``supported_needs_paraphrase``
    only, requiring supported=true and page_id; deduped by category+citation).
    Never restores raw OCR. Fail-closed when the quote has no verified support.
    """
    source = str(proposed or "")
    extras: list[str] = []

    def _repl(match: re.Match[str]) -> str:
        quote = match.group(1)
        cite = match.group("cite") or ""
        # Decode common escape artifacts before gating so multiline OCR dumps
        # embedded via literal ``\\n`` are still rejected.
        quote_text = _decode_literal_escape_artifacts(quote)
        page_id = None
        cite_match = re.search(
            r"page_id\s+([^)]+)", cite or "", flags=re.IGNORECASE
        )
        if cite_match:
            page_id = cite_match.group(1).strip()

        lead_start = max(0, match.start() - 240)
        lead_text = source[lead_start : match.start()]
        lead_category = de.infer_relief_lead_category(lead_text)

        if not de.displayed_quote_fails_readability_gate(quote_text):
            clean = de.prefer_clean_relief_display_excerpt(
                quote_text, category=lead_category
            ) or de.normalize_whitespace(quote_text)
            if de.displayed_quote_fails_readability_gate(clean):
                handoff = de.handoff_rejected_ocr_relief_quote(
                    quote_text,
                    page_id=page_id,
                    lead_category=lead_category,
                    already_present=_relief_presence_flags(source),
                )
                extras.extend(handoff.get("extra_paragraphs") or [])
                return handoff["display_clause"] + cite
            return f'as reflected in the cited pleading language: "{clean}"' + cite

        handoff = de.handoff_rejected_ocr_relief_quote(
            quote_text,
            page_id=page_id,
            lead_category=lead_category,
            already_present=_relief_presence_flags(source),
        )
        extras.extend(handoff.get("extra_paragraphs") or [])
        return handoff["display_clause"] + cite

    text = _CITED_PLEADING_LANGUAGE_QUOTE_RE.sub(_repl, source)
    if extras:
        # Append verified sibling relief paragraphs once, skipping categories the
        # scrubbed prose already retains.
        present = _relief_presence_flags(text)
        to_append: list[str] = []
        seen: set[str] = set()
        for para in extras:
            norm = de.normalize_whitespace(para)
            if not norm or norm in seen:
                continue
            key = de.infer_relief_lead_category(norm)
            if key and present.get(key):
                continue
            seen.add(norm)
            to_append.append(norm)
            if key:
                present[key] = True
        if to_append:
            base = text.rstrip()
            if base and base[-1] not in ".!?":
                base += "."
            text = de.normalize_whitespace(base + " " + " ".join(to_append))

    # Structured synthesis claims → final serialization, independent of quotes.
    return de.merge_structured_verified_relief_claims_into_answer(
        text, verified_relief_claims
    )


def _split_overview_sentences(compact: str) -> list[str]:
    """Split prose into sentences without breaking quoted excerpt spans."""
    parts: list[str] = []
    buf: list[str] = []
    in_quote = False
    i = 0
    length = len(compact)
    while i < length:
        ch = compact[i]
        if ch == '"':
            in_quote = not in_quote
            buf.append(ch)
            i += 1
            continue
        if (
            not in_quote
            and ch in ".!?"
            and i + 1 < length
            and compact[i + 1].isspace()
        ):
            j = i + 1
            while j < length and compact[j].isspace():
                j += 1
            if j < length and compact[j].isupper():
                buf.append(ch)
                part = "".join(buf).strip()
                if part:
                    parts.append(part)
                buf = []
                i = j
                continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _format_proposed_answer_markdown(
    proposed: str,
    *,
    verified_relief_claims: Optional[Sequence[Mapping[str, Any]]] = None,
) -> str:
    """Turn compact bullet/numbered prose into scannable Markdown lists.

    Preserves list substance; does not inject literal escape artifacts.
    """
    text = scrub_unreadable_quoted_excerpts(
        _decode_literal_escape_artifacts(proposed),
        verified_relief_claims=verified_relief_claims,
    ).strip()
    if not text:
        return ""

    # Already a clean multiline Markdown list: keep structure, drop escape noise.
    lines = text.splitlines()
    list_line_count = sum(1 for ln in lines if _MARKDOWN_LIST_LINE_RE.match(ln))
    if list_line_count >= 2:
        cleaned: list[str] = []
        for ln in lines:
            stripped = ln.rstrip()
            if not stripped:
                if cleaned and cleaned[-1] != "":
                    cleaned.append("")
                continue
            if _MARKDOWN_LIST_LINE_RE.match(stripped):
                marker_match = re.match(r"^(\s*(?:[-*]|\d+\.)\s+)(.*)$", stripped)
                assert marker_match is not None
                cleaned.append(
                    marker_match.group(1)
                    + _collapse_inline_whitespace(marker_match.group(2))
                )
            else:
                cleaned.append(_collapse_inline_whitespace(stripped))
        while cleaned and cleaned[-1] == "":
            cleaned.pop()
        return "\n".join(cleaned)

    compact = _collapse_inline_whitespace(text)

    parts = [part.strip() for part in compact.split(" • ") if part.strip()]
    if len(parts) > 2:
        overview, *items = parts
        cleaned_items = [
            re.sub(r"^[-*]\s+", "", item).strip() for item in items if item.strip()
        ]
        return overview + "\n\n" + "\n".join(f"- {item}" for item in cleaned_items)

    numbered_starts = list(_NUMBERED_ITEM_START_RE.finditer(compact))
    if len(numbered_starts) >= 2:
        first_at = numbered_starts[0].start()
        overview = compact[:first_at].strip()
        rest = compact[first_at:].strip()
        items = [
            _collapse_inline_whitespace(part)
            for part in _NUMBERED_ITEM_START_RE.split(rest)
            if part.strip()
        ]
        # split() keeps delimiters empty; filter to true numbered items only.
        items = [part for part in items if re.match(r"^\d+\.\s+\S", part)]
        if len(items) >= 2:
            body = "\n".join(items)
            if overview:
                return overview + "\n\n" + body
            return body

    parts = _split_overview_sentences(compact)
    if len(parts) <= 2:
        return compact
    overview, *items = parts
    return overview + "\n\n" + "\n".join(f"- {item}" for item in items)


def canonical_proposed_answer(
    proposed: str,
    *,
    verified_relief_claims: Optional[Sequence[Mapping[str, Any]]] = None,
) -> str:
    """Single canonical proposed-answer string for JSON and Markdown serializers.

    Both artifact channels derive from this representation so substance matches
    after ``normalize_proposed_answer_whitespace``. Final serialization also
    rejects raw OCR dump quotes via ``scrub_unreadable_quoted_excerpts`` and
    merges structured verified relief claims from synthesis independently of
    displayed quote objects.
    """
    return _format_proposed_answer_markdown(
        proposed, verified_relief_claims=verified_relief_claims
    )


def _criterion_dimension_satisfied(result: ac.CriterionResult) -> dict[str, bool]:
    """Map which acceptance dimensions were already satisfied for a criterion."""
    return {
        "presence": result.presence == ac.PRESENCE_PRESENT,
        "evidence": result.evidence == ac.EVIDENCE_SUPPORTED,
        "semantic": result.semantic
        in {ac.SEMANTIC_PRESERVED, ac.SEMANTIC_NOT_APPLICABLE},
        "pass": result.result_code == ac.CRIT_PASS,
    }


def presentation_rewrite_lost_satisfied_criteria(
    before: ac.AcceptanceValidationResult,
    after: ac.AcceptanceValidationResult,
) -> list[str]:
    """Return criterion ids whose previously satisfied dimensions were lost.

    Compares safe result codes only — never criterion prose or private phrases.
    """
    after_by_id = {c.criterion_id: c for c in after.criterion_results}
    lost: list[str] = []
    for prior in before.criterion_results:
        dims = _criterion_dimension_satisfied(prior)
        if not any(dims.values()):
            continue
        post = after_by_id.get(prior.criterion_id)
        if post is None:
            lost.append(prior.criterion_id)
            continue
        post_dims = _criterion_dimension_satisfied(post)
        if dims["pass"] and not post_dims["pass"]:
            lost.append(prior.criterion_id)
            continue
        if dims["presence"] and not post_dims["presence"]:
            lost.append(prior.criterion_id)
            continue
        if dims["evidence"] and not post_dims["evidence"]:
            lost.append(prior.criterion_id)
            continue
        if (
            prior.semantic == ac.SEMANTIC_PRESERVED
            and post.semantic != ac.SEMANTIC_PRESERVED
        ):
            lost.append(prior.criterion_id)
    return lost


_Q1_RELATED_ACTION_CUE_RE = re.compile(
    r"(?i)\b(?:underlying|related|separate|third[ -]party)\s+(?:action|case|litigation)\b"
)
_Q1_RELATED_ROLE_RE = re.compile(
    r"(?i)\b(?:third[ -]party plaintiff|third[ -]party defendant|"
    r"respondent on appeal|appellant|plaintiff|defendant)\b"
)


_Q1_SUBSTANTIVE_ROLE_RE = re.compile(
    r"(?i)\b(?:insurer|underwriter|named insured|additional insured|"
    r"owner|contractor|tenant|landlord|broker)\b"
)

# Privacy boundary: labels and patterns are fixed in source. Diagnostics report
# only nonzero integer counts for these known legal terms; they never emit
# matched text or evidence identifiers.
_Q1_ROLE_VOCABULARY_PATTERNS = {
    "substantive_role_terms": {
        "insurer": r"\binsurer\b",
        "underwriter": r"\bunderwriter\b",
        "named_insured": r"\bnamed insured\b",
        "additional_insured": r"\badditional insured\b",
        "insured": r"\binsured\b",
        "insurance_carrier": r"\binsurance carrier\b",
        "owner": r"\bowner\b",
        "property_owner": r"\bproperty owner\b",
        "contractor": r"\bcontractor\b",
        "general_contractor": r"\bgeneral contractor\b",
        "subcontractor": r"\bsubcontractor\b",
        "tenant": r"\btenant\b",
        "landlord": r"\blandlord\b",
        "lessor": r"\blessor\b",
        "lessee": r"\blessee\b",
        "broker": r"\bbroker\b",
        "agent": r"\bagent\b",
        "managing_agent": r"\bmanaging agent\b",
        "manager": r"\bmanager\b",
        "property_manager": r"\bproperty manager\b",
        "operator": r"\boperator\b",
        "developer": r"\bdeveloper\b",
        "employer": r"\bemployer\b",
        "employee": r"\bemployee\b",
        "seller": r"\bseller\b",
        "purchaser": r"\bpurchaser\b",
    },
    "related_action_cues": {
        "underlying_action": r"\bunderlying action\b",
        "underlying_case": r"\bunderlying case\b",
        "underlying_litigation": r"\bunderlying litigation\b",
        "related_action": r"\brelated action\b",
        "related_case": r"\brelated case\b",
        "related_litigation": r"\brelated litigation\b",
        "separate_action": r"\bseparate action\b",
        "separate_case": r"\bseparate case\b",
        "separate_litigation": r"\bseparate litigation\b",
        "third_party_action": r"\bthird[ -]party action\b",
    },
    "procedural_role_terms": {
        "plaintiff": r"\bplaintiff\b",
        "defendant": r"\bdefendant\b",
        "third_party_plaintiff": r"\bthird[ -]party plaintiff\b",
        "third_party_defendant": r"\bthird[ -]party defendant\b",
        "appellant": r"\bappellant\b",
        "respondent_on_appeal": r"\brespondent on appeal\b",
    },
}


def q1_role_vocabulary_counts(
    evidence_packet: Mapping[str, Any],
) -> dict[str, dict[str, int]]:
    """Count literal occurrences of fixed legal-role vocabulary in evidence excerpts."""
    evidence_text = "\n".join(
        str(hit.get("excerpt") or "")
        for hit in evidence_packet.get("retrieval_hits") or []
        if isinstance(hit, Mapping)
    )
    return {
        category: {
            label: len(re.findall(pattern, evidence_text, flags=re.IGNORECASE))
            for label, pattern in patterns.items()
            if re.search(pattern, evidence_text, flags=re.IGNORECASE)
        }
        for category, patterns in _Q1_ROLE_VOCABULARY_PATTERNS.items()
    }


def build_q1_validated_party_claims(
    reasoner_result: Mapping[str, Any],
    *,
    evidence_packet: Optional[Mapping[str, Any]] = None,
    diagnostics_out: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build typed Q1 claims only from deterministic inventory and evidence."""
    audit = reasoner_result.get("audit")
    expected = audit.get("party_role_expected_attributes") or [] if isinstance(audit, Mapping) else []
    expected_identities = [
        normalize_proposed_answer_whitespace(str(item.get("identity") or ""))
        for item in expected
        if isinstance(item, Mapping)
        and normalize_proposed_answer_whitespace(str(item.get("identity") or ""))
    ]
    # The exact serialized pre-draft packet is deterministic and bounded. Do
    # not mine model-produced proposed_answer or propositions for typed claims.
    packet = evidence_packet if isinstance(evidence_packet, Mapping) else {}
    sentence_groups: list[list[str]] = []
    for hit in packet.get("retrieval_hits") or []:
        if not isinstance(hit, Mapping):
            continue
        excerpt = str(hit.get("excerpt") or "")
        group = [
            normalize_proposed_answer_whitespace(sentence)
            for sentence in re.split(r"(?<=[.!?])\s+|\n+", excerpt)
            if normalize_proposed_answer_whitespace(sentence)
        ]
        if group:
            sentence_groups.append(group)
    parties: list[dict[str, Any]] = []
    diagnostic_rows: list[dict[str, Any]] = []
    for raw in expected:
        if not isinstance(raw, Mapping):
            continue
        identity = normalize_proposed_answer_whitespace(str(raw.get("identity") or ""))
        if not identity:
            continue
        role = normalize_proposed_answer_whitespace(str(raw.get("procedural_role") or ""))
        basis = normalize_proposed_answer_whitespace(str(raw.get("pleaded_role_basis") or ""))
        related_roles: list[str] = []
        substantive_roles: list[str] = []
        evidence_sentence_match_count = 0
        evidence_field_categories: set[str] = set()
        # The inventory basis was itself extracted from the bounded evidence
        # packet. Reuse only recognized substantive designations from it.
        for matched in _Q1_SUBSTANTIVE_ROLE_RE.findall(basis):
            value = normalize_proposed_answer_whitespace(matched).lower()
            if value and value not in substantive_roles:
                substantive_roles.append(value)
                evidence_field_categories.add("substantive_role")
        for group in sentence_groups:
            for sentence_index, sentence in enumerate(group):
                if not re.search(re.escape(identity), sentence, re.IGNORECASE):
                    continue
                evidence_sentence_match_count += 1
                evidence_field_categories.add("identity")
                role_probe = re.sub(
                    re.escape(identity), " ", sentence, flags=re.IGNORECASE
                )
                for matched in _Q1_SUBSTANTIVE_ROLE_RE.findall(role_probe):
                    value = normalize_proposed_answer_whitespace(matched).lower()
                    if value and value not in substantive_roles:
                        substantive_roles.append(value)
                        evidence_field_categories.add("substantive_role")
                # Permit a substantive designation in the immediately adjacent
                # sentence only when the identity sentence names no other
                # inventoried party and the adjacent sentence names none. This
                # supports pronoun/continuation drafting without assigning a
                # nearby party's role across caption or roster sentences.
                current_has_other_identity = any(
                    other.lower() != identity.lower()
                    and re.search(re.escape(other), sentence, re.IGNORECASE)
                    for other in expected_identities
                )
                if (
                    not current_has_other_identity
                    and sentence_index + 1 < len(group)
                ):
                    adjacent_sentence = group[sentence_index + 1]
                    adjacent_has_identity = any(
                        re.search(
                            re.escape(other),
                            adjacent_sentence,
                            re.IGNORECASE,
                        )
                        for other in expected_identities
                    )
                    if not adjacent_has_identity:
                        for matched in _Q1_SUBSTANTIVE_ROLE_RE.findall(
                            adjacent_sentence
                        ):
                            value = normalize_proposed_answer_whitespace(
                                matched
                            ).lower()
                            if value and value not in substantive_roles:
                                substantive_roles.append(value)
                                evidence_field_categories.add(
                                    "substantive_role"
                                )
                # Related-action clauses often follow the identity sentence
                # with a pronoun. Permit only the immediately adjacent sentence
                # in the same retrieval hit, and still require an explicit
                # related-action cue before accepting a different role.
                window = " ".join(
                    group[sentence_index : min(len(group), sentence_index + 2)]
                )
                if not _Q1_RELATED_ACTION_CUE_RE.search(window):
                    continue
                for matched in _Q1_RELATED_ROLE_RE.findall(window):
                    value = normalize_proposed_answer_whitespace(matched).lower()
                    if (
                        value
                        and value != role.lower()
                        and value not in related_roles
                    ):
                        related_roles.append(value)
                        evidence_field_categories.add("related_action_roles")
        # A bounded substantive designation in the same evidence sentence is
        # also the pleaded-role basis when the inventory lacks a narrower one.
        # This preserves evidence language; it does not infer a legal conclusion.
        if not basis and substantive_roles:
            basis = "; ".join(substantive_roles)
            evidence_field_categories.add("pleaded_role_basis")
        party_index = len(parties)
        parties.append({
            "identity": identity,
            "procedural_roles": [role] if role else [],
            "pleaded_role_basis": basis,
            "substantive_role": "; ".join(substantive_roles),
            "entity_type": normalize_proposed_answer_whitespace(str(raw.get("entity_type") or "")),
            "residence_or_ppb": normalize_proposed_answer_whitespace(str(raw.get("residence_or_ppb") or "")),
            "related_action_roles": related_roles,
        })
        diagnostic_rows.append({
            "party_index": party_index,
            "evidence_sentence_match_count": evidence_sentence_match_count,
            "evidence_field_categories": sorted(evidence_field_categories),
        })
    if diagnostics_out is not None:
        diagnostics_out.clear()
        diagnostics_out.update({
            "party_count": len(parties),
            "parties": diagnostic_rows,
            "role_vocabulary_counts": q1_role_vocabulary_counts(packet),
        })
    scope = reasoner_result.get("review_scope")
    completeness = str(scope.get("completeness") or "").strip().lower() if isinstance(scope, Mapping) else ""
    claims = {
        "schema_version": ac.Q1_VALIDATED_PARTY_CLAIMS_SCHEMA_VERSION,
        "parties": parties,
        "roster_completeness": "complete" if completeness in {"complete", "established"} else "not_established",
    }
    if not ac.q1_party_claims_are_valid(claims):
        raise GenerationError(
            "Typed Q1 validated party claims failed shape validation",
            reason_code="q1_validated_party_claims_invalid",
            finalized=False,
        )
    return claims


def render_q1_validated_party_claims(claims: Mapping[str, Any]) -> str:
    """Render typed claims into concise attorney-facing prose."""
    if not ac.q1_party_claims_are_valid(claims):
        raise GenerationError(
            "Cannot render malformed typed Q1 party claims",
            reason_code="q1_validated_party_claims_invalid",
            finalized=False,
        )
    lines = ["Validated party/role summary:"]
    for party in claims.get("parties") or []:
        parts = [
            "current role: "
            + (", ".join(party.get("procedural_roles") or []) or "not established")
        ]
        if party.get("pleaded_role_basis"):
            parts.append(f"pleaded designation: {party['pleaded_role_basis']}")
        if party.get("substantive_role"):
            parts.append(f"substantive role: {party['substantive_role']}")
        if party.get("related_action_roles"):
            parts.append("related-action role: " + ", ".join(party["related_action_roles"]))
        lines.append(f"- {party['identity']} — " + "; ".join(parts) + ".")
    if claims.get("roster_completeness") != "complete":
        lines.append(
            "The retrieved record does not establish that this is a complete party roster."
        )
    return "\n".join(lines)


def q1_missing_rendered_claim_fields(
    answer_text: str, claims: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Return privacy-safe locations for typed claims missing from final prose."""
    norm = normalize_proposed_answer_whitespace(answer_text).lower()
    missing: list[dict[str, Any]] = []
    for party_index, party in enumerate(claims.get("parties") or []):
        fields = {
            "identity": [str(party.get("identity") or "")],
            "procedural_roles": list(party.get("procedural_roles") or []),
            "pleaded_role_basis": [str(party.get("pleaded_role_basis") or "")],
            "substantive_role": [str(party.get("substantive_role") or "")],
            "related_action_roles": list(party.get("related_action_roles") or []),
        }
        for field, values in fields.items():
            normalized = [
                normalize_proposed_answer_whitespace(value).lower()
                for value in values
                if normalize_proposed_answer_whitespace(value)
            ]
            if any(value not in norm for value in normalized):
                missing.append({"party_index": party_index, "field": field})
    if (
        claims.get("roster_completeness") != "complete"
        and "does not establish that this is a complete party roster" not in norm
    ):
        missing.append({"party_index": None, "field": "roster_completeness"})
    return missing


def q1_rendered_claims_present(
    answer_text: str, claims: Mapping[str, Any]
) -> bool:
    """True only when every typed claim rendered into the final answer."""
    return not q1_missing_rendered_claim_fields(answer_text, claims)


def record_q1_retention_stage(
    diagnostics_out: Optional[dict[str, Any]],
    *,
    stage: str,
    answer_text: str,
    claims: Mapping[str, Any],
) -> None:
    """Record privacy-safe typed-claim presence at one rendering stage."""
    if diagnostics_out is None:
        return
    stages = diagnostics_out.setdefault("stages", [])
    stages.append(
        {
            "stage": stage,
            "missing_typed_claim_fields": q1_missing_rendered_claim_fields(
                answer_text, claims
            ),
        }
    )


def retain_q1_validated_party_claims(
    answer_text: str,
    claims: Mapping[str, Any],
    *,
    canonicalize: Optional[Callable[[str], str]] = None,
) -> str:
    """Restore the deterministic Q1 summary after lossy contract repair.

    Contract fallback and duplication repair run before presentation
    canonicalization. Canonicalize the model-authored answer first, then append
    the complete deterministic summary unchanged if any typed claim is absent.
    The caller must still revalidate the exact returned string.
    """
    if q1_rendered_claims_present(answer_text, claims):
        return answer_text
    canonicalize_fn = canonicalize or canonical_proposed_answer
    canonicalized_answer = canonicalize_fn(answer_text)
    if q1_rendered_claims_present(canonicalized_answer, claims):
        return canonicalized_answer
    # The typed summary is already deterministic, bounded Markdown. Append it
    # after presentation canonicalization so a lossy formatter cannot rewrite
    # or remove an identity that the final retention check requires.
    summary = render_q1_validated_party_claims(claims)
    return f"{canonicalized_answer.rstrip()}\n\n{summary}".strip()


def validated_acceptance_evidence_text(reasoner_result: Mapping[str, Any]) -> str:
    """Serialize retained, post-validation evidence for contract checks.

    Party-role completeness repair can retain deterministic evidence-extracted
    attribute rows and synthesis units after category-specific validation.
    Include only those bounded fields plus citation-validated propositions;
    never serialize raw retrieval hits, removed propositions, review-scope
    prose, unresolved questions, or arbitrary audit content.
    """
    rows: list[str] = []
    for proposition in reasoner_result.get("propositions") or []:
        if not isinstance(proposition, Mapping):
            continue
        text_value = normalize_proposed_answer_whitespace(
            str(proposition.get("text") or "")
        )
        excerpt = normalize_proposed_answer_whitespace(
            str(
                proposition.get("source_excerpt")
                or proposition.get("excerpt")
                or ""
            )
        )
        page_id = str(proposition.get("page_id") or "").strip()
        if text_value:
            rows.append(text_value)
        if excerpt:
            rows.append(excerpt)
        if page_id:
            rows.append(f"page_id {page_id}")

    audit = reasoner_result.get("audit")
    if isinstance(audit, Mapping):
        # Stable evidence-derived inventories exist on every completed
        # party-role run, independent of whether model repair was needed.
        for item in audit.get("party_role_expected_attributes") or []:
            if not isinstance(item, Mapping):
                continue
            for field in (
                "identity",
                "procedural_role",
                "entity_type",
                "residence_or_ppb",
                "pleaded_role_basis",
            ):
                value = normalize_proposed_answer_whitespace(
                    str(item.get(field) or "")
                )
                if value:
                    rows.append(f"{field} {value}")
        for item in audit.get("party_role_expected_synthesis") or []:
            if not isinstance(item, Mapping):
                continue
            category = normalize_proposed_answer_whitespace(
                str(item.get("category") or "")
            )
            value = normalize_proposed_answer_whitespace(
                str(item.get("value") or "")
            )
            if category and value:
                rows.append(f"{category} {value}")
            for party in item.get("parties") or []:
                party_value = normalize_proposed_answer_whitespace(str(party))
                if party_value:
                    rows.append(f"{category} party {party_value}")
            for heading in item.get("section_headings") or []:
                heading_value = normalize_proposed_answer_whitespace(str(heading))
                if heading_value:
                    rows.append(f"{category} section {heading_value}")
            for number in item.get("paragraph_numbers") or []:
                if isinstance(number, int):
                    rows.append(f"{category} paragraph {number}")
        for item in audit.get("party_role_deterministic_attribute_fallbacks") or []:
            if not isinstance(item, Mapping):
                continue
            party = normalize_proposed_answer_whitespace(
                str(item.get("party") or "")
            )
            category = normalize_proposed_answer_whitespace(
                str(item.get("category") or "")
            )
            value = normalize_proposed_answer_whitespace(
                str(item.get("value") or "")
            )
            if party and category and value:
                rows.append(f"{party} {category} {value}")
        for item in audit.get("party_role_retained_synthesis_units") or []:
            if not isinstance(item, Mapping):
                continue
            category = normalize_proposed_answer_whitespace(
                str(item.get("category") or "")
            )
            text_value = normalize_proposed_answer_whitespace(
                str(item.get("text") or "")
            )
            if category and text_value:
                rows.append(f"{category} {text_value}")
    return "\n".join(rows)


def finalize_canonical_answer_against_contract(
    proposed_answer: str,
    contract_view: ac.ContractEvaluationView,
    *,
    canonicalize: Optional[Callable[[str], str]] = None,
    verified_relief_claims: Optional[Sequence[Mapping[str, Any]]] = None,
    validated_claims: Optional[Mapping[str, Any]] = None,
    validated_evidence_text: Optional[str] = None,
    q1_retention_diagnostics_out: Optional[dict[str, Any]] = None,
) -> tuple[str, ac.AcceptanceValidationResult]:
    """Repair, canonicalize for presentation, then validate the exact final string.

    Order is intentional:
    1. Contract fallback + duplication repair on the assembled answer
    2. Presentation cleanup (Markdown canonicalization / whitespace)
    3. Re-validate the exact canonical string with no further mutation
    4. Fail closed if any previously satisfied presence/evidence/semantic
       criterion was lost to the presentation rewrite

    JSON and Markdown serializers must both consume the returned canonical
    string. Optional ``verified_relief_claims`` from synthesis are merged
    during canonicalization independently of displayed quotes.

    When ``validated_claims`` is the immutable ``q2_validated_structured_claims.v1``
    object, final acceptance uses the shared Q2 no-defense semantic evaluator
    (same authority as production-boundary preflight).
    """
    if canonicalize is not None:
        canonicalize_fn = canonicalize
    elif verified_relief_claims is not None:
        canonicalize_fn = lambda text: canonical_proposed_answer(
            text, verified_relief_claims=verified_relief_claims
        )
    else:
        canonicalize_fn = canonical_proposed_answer
    is_q1_claims = (
        isinstance(validated_claims, Mapping)
        and validated_claims.get("schema_version")
        == ac.Q1_VALIDATED_PARTY_CLAIMS_SCHEMA_VERSION
    )
    if q1_retention_diagnostics_out is not None:
        q1_retention_diagnostics_out.clear()
        q1_retention_diagnostics_out["schema_version"] = (
            "q1_retention_diagnostics.v1"
        )
    # Merge structured synthesis claims before the first contract pass so
    # quote-only handoff gaps cannot trip fail-closed unsupported fallback.
    proposed_for_contract = de.merge_structured_verified_relief_claims_into_answer(
        proposed_answer or "", verified_relief_claims
    )
    if is_q1_claims:
        record_q1_retention_stage(
            q1_retention_diagnostics_out,
            stage="pre_contract",
            answer_text=proposed_for_contract,
            claims=validated_claims,
        )
    repaired = ac.validate_final_answer_against_contract(
        proposed_for_contract,
        contract_view,
        apply_fallback=True,
        apply_duplication_repair=True,
        validated_claims=validated_claims,
        validated_evidence_text=validated_evidence_text,
    )
    if is_q1_claims:
        record_q1_retention_stage(
            q1_retention_diagnostics_out,
            stage="post_contract_repair",
            answer_text=repaired.final_answer,
            claims=validated_claims,
        )
    if not repaired.ok and not is_q1_claims:
        return repaired.final_answer, repaired

    # Q1 typed claims can make the first contract pass fail when fallback or
    # duplication repair removes a deterministic party field. Continue through
    # canonicalization, typed-summary retention, and exact final revalidation.
    canonical = canonicalize_fn(repaired.final_answer)
    if is_q1_claims:
        record_q1_retention_stage(
            q1_retention_diagnostics_out,
            stage="post_canonicalization",
            answer_text=canonical,
            claims=validated_claims,
        )
        canonical = retain_q1_validated_party_claims(
            canonical,
            validated_claims,
            canonicalize=canonicalize_fn,
        )
        record_q1_retention_stage(
            q1_retention_diagnostics_out,
            stage="post_retention",
            answer_text=canonical,
            claims=validated_claims,
        )
    final = ac.validate_final_answer_against_contract(
        canonical,
        contract_view,
        apply_fallback=False,
        apply_duplication_repair=False,
        validated_claims=validated_claims,
        validated_evidence_text=validated_evidence_text,
    )
    lost = presentation_rewrite_lost_satisfied_criteria(repaired, final)
    if lost:
        final.ok = False
        # Safe ids only — never private phrases or fallback prose.
        for cid in lost:
            final.diagnostics.append(f"presentation_rewrite_lost_criterion:{cid}")
    elif not final.ok:
        final.diagnostics.append("canonical_acceptance_validation_failed")
    # Always return the canonical presentation string as the candidate body,
    # even on failure, so audits inspect the same text JSON/Markdown would emit.
    final.final_answer = canonical
    if is_q1_claims:
        record_q1_retention_stage(
            q1_retention_diagnostics_out,
            stage="final_validation",
            answer_text=final.final_answer,
            claims=validated_claims,
        )
    return canonical, final


def write_candidate_artifacts(
    out_dir: Path,
    *,
    question_id: str,
    question_text: str,
    required_commit: str,
    reasoner_result: dict,
    model_input_audit: dict,
    commit_info: dict,
    completeness: dict,
    acceptance_provenance: Optional[dict] = None,
) -> dict[str, Path]:
    """Write the four candidate artifacts and verify absolute-path hashes."""
    out_dir.mkdir(parents=True, exist_ok=False)
    generated_at = _utc_now()
    # One canonical string feeds JSON proposed_answer and Markdown body alike.
    reasoner_audit = reasoner_result.get("audit") or {}
    verified_claims = reasoner_audit.get("verified_relief_claims")
    if not isinstance(verified_claims, list):
        verified_claims = None
    proposed = canonical_proposed_answer(
        reasoner_result.get("proposed_answer") or "",
        verified_relief_claims=verified_claims,
    )
    model_name = reasoner_audit.get("model") or "unknown"
    provider = reasoner_audit.get("provider") or "unknown"
    provenance_reason = reasoner_audit.get("model_provenance_reason") or (
        "The reasoner did not expose model/provider provenance."
    )

    json_name = f"{question_id}_candidate_answer.json"
    md_name = f"{question_id}_candidate_answer.md"
    # Durable CLI keeps the historical Q1 artifact filenames when question_id is Q1.
    if question_id == "Q1":
        json_name = "Q1_candidate_answer.json"
        md_name = "Q1_candidate_answer.md"

    candidate = {
        "artifact_type": "attorney_feedback_candidate_answer",
        "status": "candidate",
        "attorney_approved": False,
        "approval_status": "pending_attorney_review",
        "finalized": True,
        "generation_finalized": True,
        "finalized_semantics": (
            "Deprecated finalized=true means generation completed; it does not mean "
            "attorney approval. Use generation_finalized and approval_status."
        ),
        "generation_commit": required_commit,
        "generated_at": generated_at,
        "question_id": question_id,
        "question_text": question_text,
        "model": model_name,
        "provider": provider,
        "model_provenance_reason": provenance_reason,
        "candidate_directory": str(out_dir.resolve()),
        "reasoner_status": reasoner_result.get("status"),
        "reasoner_result": reasoner_result,
        "proposed_answer": proposed,
        "confidence": reasoner_result.get("confidence"),
        "propositions": reasoner_result.get("propositions") or [],
        "supporting_evidence": reasoner_result.get("supporting_evidence") or [],
        "contrary_evidence": reasoner_result.get("contrary_evidence") or [],
        "unresolved_questions": reasoner_result.get("unresolved_questions") or [],
        "documents_pages_reviewed": reasoner_result.get("documents_pages_reviewed") or [],
        "attorney_review": reasoner_result.get("attorney_review")
        or {"requires_attorney_review": True},
        "review_scope": reasoner_result.get("review_scope"),
        "audit": reasoner_result.get("audit") or {},
        "completeness_validation": completeness,
        "contamination_protection": {
            "original_answer_loaded": False,
            "provisional_or_gold_answers_loaded": False,
            "gold_labels_loaded": False,
            "attorney_feedback_loaded": False,
            "prior_candidate_answer_prose_loaded": False,
            "evaluation_or_comparison_artifacts_loaded": False,
            "confirmation": (
                "Confirmed prohibited artifacts were not loaded during generation."
            ),
        },
        "permitted_inputs_used": [
            "question text field",
            "canonical page records",
            "filing exhibit map",
            "case map",
            "NYSCEF filing inventory",
            "production retrieval/evidence-packet/serialization/drafting/validation/bounded synthesis-patch repair (exact-once categories; category lifecycle diagnostics only)",
        ],
    }
    candidate_hash = candidate_content_sha256(candidate)
    candidate["candidate_sha256"] = candidate_hash

    md_text = (
        f"# {question_id} Candidate Answer\n\n"
        f"status: `candidate`\n\n"
        f"attorney_approved: `false`\n\n"
        f"approval_status: `pending_attorney_review`\n\n"
        f"generation_commit: `{required_commit}`\n\n"
        f"generation_finalized: `true`\n\n"
        f"generated_at: `{generated_at}`\n\n"
        f"candidate_sha256: `{candidate_hash}`\n\n"
        f"## Question\n\n{question_text}\n\n"
        f"## Proposed answer\n\n{proposed}\n\n"
        f"## Review limitation\n\n"
        f"This is a generation-finalized candidate, not an attorney-approved answer. "
        f"Its conclusions remain limited to the retrieved evidence identified above.\n"
    )

    absolute_paths = {
        json_name: str((out_dir / json_name).resolve()),
        md_name: str((out_dir / md_name).resolve()),
        "generation_manifest.json": str((out_dir / "generation_manifest.json").resolve()),
        "model_input_audit.json": str((out_dir / "model_input_audit.json").resolve()),
    }

    manifest = {
        "artifact_type": "attorney_feedback_candidate_generation_manifest",
        "status": "candidate",
        "attorney_approved": False,
        "approval_status": "pending_attorney_review",
        "finalized": True,
        "generation_finalized": True,
        "finalized_semantics": (
            "Deprecated finalized=true means generation completed; it does not mean "
            "attorney approval."
        ),
        "generation_commit": required_commit,
        "generated_at": generated_at,
        "checkout_commit": commit_info.get("checkout_commit"),
        "origin_main_commit": commit_info.get("origin_main_commit"),
        "candidate_directory": str(out_dir.resolve()),
        "question_id": question_id,
        "generation_only": True,
        "candidate_sha256": candidate_hash,
        "candidate_sha256_method": (
            "sha256(utf-8 of json.dumps(candidate_without_candidate_sha256_field, "
            "sort_keys=True, ensure_ascii=False, separators=(',', ':')))"
        ),
        "files": [
            json_name,
            md_name,
            "generation_manifest.json",
            "model_input_audit.json",
        ],
        "absolute_paths": absolute_paths,
        "completeness_validation": completeness,
        "reasoner_status": reasoner_result.get("status"),
    }

    audit_out = dict(model_input_audit)
    audit_out.update(
        {
            "generated_at": generated_at,
            "generation_commit": required_commit,
            "candidate_sha256": candidate_hash,
            "absolute_paths": absolute_paths,
            "completeness_validation": completeness,
        }
    )
    if acceptance_provenance:
        # Safe provenance only (ids, hashes, result codes — never contract body).
        audit_out.update(acceptance_provenance)
        manifest.update(acceptance_provenance)

    json_path = out_dir / json_name
    md_path = out_dir / md_name
    manifest_path = out_dir / "generation_manifest.json"
    audit_path = out_dir / "model_input_audit.json"

    json_path.write_text(
        json.dumps(candidate, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    md_path.write_text(md_text, encoding="utf-8")
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    audit_path.write_text(
        json.dumps(audit_out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    loaded = json.loads(json_path.read_text(encoding="utf-8"))
    verified_hash = candidate_content_sha256(loaded)
    file_sha = mb.compute_file_sha256(json_path)
    if verified_hash != candidate_hash or loaded.get("candidate_sha256") != candidate_hash:
        raise GenerationError(
            "Hash verification failed after artifact write",
            recorded=candidate_hash,
            recomputed=verified_hash,
            loaded_field=loaded.get("candidate_sha256"),
        )

    manifest["candidate_answer_json_file_sha256"] = file_sha
    audit_out["candidate_answer_json_file_sha256"] = file_sha
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    audit_path.write_text(
        json.dumps(audit_out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    return {
        json_name: json_path.resolve(),
        md_name: md_path.resolve(),
        "generation_manifest.json": manifest_path.resolve(),
        "model_input_audit.json": audit_path.resolve(),
    }


def _env_strip(environ: Mapping[str, str], name: str) -> str:
    return str(environ.get(name, "") or "").strip()


def materialize_acceptance_contract_b2_transport(
    config: dict,
    *,
    environ: Optional[Mapping[str, str]] = None,
) -> tuple[Optional[dict], Optional[str]]:
    """Attach authenticated B2 client/bucket/retry when loading by object key.

    Returns ``(config_or_None, error_code_or_None)``. Never copies credentials
    into the returned config. Safe to call when a client is already present.
    """
    if config.get("raw_bytes") is not None or config.get("raw_json") is not None:
        return config, None
    if config.get("client") is not None and config.get("bucket"):
        out = dict(config)
        if out.get("call_with_retry") is None:
            out["call_with_retry"] = rebuild_cli.call_b2_with_read_retry
        return out, None

    env = os.environ if environ is None else environ
    try:
        b2_config = rebuild_cli.B2Config.from_env(env)
        client = rebuild_cli.create_b2_client(b2_config)
    except rebuild_cli.RebuildError:
        return None, "b2_read_error"
    except Exception:  # noqa: BLE001 — fail closed; never surface secrets
        return None, "b2_read_error"

    out = dict(config)
    out["client"] = client
    out["bucket"] = b2_config.bucket
    out["call_with_retry"] = rebuild_cli.call_b2_with_read_retry
    return out, None


def resolve_acceptance_contract_config(
    *,
    question_id: str,
    object_key: Optional[str] = None,
    benchmark_id: Optional[str] = None,
    content_sha256: Optional[str] = None,
    json_path: Optional[Path] = None,
    environ: Optional[Mapping[str, str]] = None,
    client: Any = None,
    bucket: Optional[str] = None,
    call_with_retry: Optional[Callable[..., Any]] = None,
    raw_bytes: Optional[bytes] = None,
) -> Optional[dict]:
    """Build acceptance-contract load config from CLI args and/or env pins.

    Returns ``None`` when no object key is configured (optional generator path).
    When an object key is present, benchmark_id and question_id must be explicit
    (no silent identity defaults). B2 loads also require content_sha256.
    """
    env = os.environ if environ is None else environ
    key = (object_key or _env_strip(env, ACCEPTANCE_CONTRACT_OBJECT_KEY_ENV)).strip()
    if not key:
        return None

    resolved_benchmark = (
        benchmark_id or _env_strip(env, ACCEPTANCE_CONTRACT_BENCHMARK_ID_ENV)
    ).strip()
    resolved_sha = (
        content_sha256 or _env_strip(env, ACCEPTANCE_CONTRACT_CONTENT_SHA256_ENV)
    ).strip()
    qid = str(question_id or "").strip()

    config: dict[str, Any] = {
        "object_key": key,
        "benchmark_id": resolved_benchmark,
        "question_id": qid,
        "content_sha256": resolved_sha or None,
    }
    if raw_bytes is not None:
        config["raw_bytes"] = raw_bytes
    elif json_path is not None:
        config["raw_bytes"] = Path(json_path).read_bytes()
    elif client is not None and bucket:
        config["client"] = client
        config["bucket"] = str(bucket)
        if call_with_retry is not None:
            config["call_with_retry"] = call_with_retry
    return config


def load_configured_acceptance_contract(
    config: Optional[dict],
    *,
    environ: Optional[Mapping[str, str]] = None,
) -> tuple[str, Optional[ac.ContractEvaluationView], Optional[str], dict]:
    """Load an acceptance contract when configured.

    Returns ``(load_status, evaluation_view|None, error_code|None, safe_stub)``.
    Unconfigured workflows preserve prior behavior (``load_not_configured``).
    Configured runs must succeed or the caller fails closed.

    CLI B2 mode supplies object metadata only; this materializes the shared
    authenticated B2 client/configuration before reading the private object.
    """
    if not config:
        prov = ac.safe_provenance_record(load_status=ac.LOAD_NOT_CONFIGURED)
        return ac.LOAD_NOT_CONFIGURED, None, None, prov

    object_key = str(config.get("object_key") or "").strip()
    benchmark_id = str(config.get("benchmark_id") or "").strip()
    qid = str(config.get("question_id") or "").strip()
    if not object_key or not benchmark_id or not qid:
        prov = ac.safe_provenance_record(
            load_status=ac.LOAD_INVALID,
            load_error_code=ac.ERROR_SCHEMA_INVALID,
            object_key=object_key,
        )
        return ac.LOAD_INVALID, None, ac.ERROR_SCHEMA_INVALID, prov

    identity = ac.ContractIdentity(benchmark_id=benchmark_id, question_id=qid)
    expected_sha = str(config.get("content_sha256") or "").strip() or None
    raw = config.get("raw_bytes")
    if raw is None and config.get("raw_json") is not None:
        raw = str(config["raw_json"]).encode("utf-8")

    if raw is not None:
        result = ac.load_acceptance_contract_from_bytes(
            raw if isinstance(raw, (bytes, bytearray)) else str(raw).encode("utf-8"),
            object_key=object_key,
            expected_identity=identity,
            expected_content_sha256=expected_sha,
        )
    else:
        # Production / CLI B2 path: require an expected content pin, then wire
        # the authenticated client from shared B2 configuration when needed.
        if not expected_sha:
            prov = ac.safe_provenance_record(
                load_status=ac.LOAD_INVALID,
                load_error_code=ac.ERROR_SCHEMA_INVALID,
                object_key=object_key,
            )
            return ac.LOAD_INVALID, None, ac.ERROR_SCHEMA_INVALID, prov

        transport, transport_error = materialize_acceptance_contract_b2_transport(
            config, environ=environ
        )
        if transport is None:
            prov = ac.safe_provenance_record(
                load_status=ac.LOAD_UNAVAILABLE,
                load_error_code=transport_error or "b2_read_error",
                object_key=object_key,
            )
            return (
                ac.LOAD_UNAVAILABLE,
                None,
                transport_error or "b2_read_error",
                prov,
            )

        result = ac.load_acceptance_contract_from_b2(
            client=transport["client"],
            bucket=str(transport["bucket"]),
            object_key=object_key,
            expected_identity=identity,
            expected_content_sha256=expected_sha,
            call_with_retry=transport.get("call_with_retry"),
        )

    if not result.ok or result.evaluation is None:
        status = (
            ac.LOAD_UNAVAILABLE
            if result.error_code
            in {ac.ERROR_MISSING_OBJECT, "b2_read_error"}
            else ac.LOAD_INVALID
        )
        prov = ac.safe_provenance_record(
            load_status=status,
            load_error_code=result.error_code,
            object_key=object_key,
            content_sha256=result.computed_content_sha256 or "",
        )
        return status, None, result.error_code, prov

    prov = ac.safe_provenance_record(
        load_status=ac.LOAD_OK,
        view=result.evaluation,
    )
    return ac.LOAD_OK, result.evaluation, None, prov


def run_generation(
    *,
    case_root: Path,
    question_id: str,
    required_commit: str,
    candidate_output_root: Path,
    authorization_acknowledgement: str,
    generation_only: bool,
    repo_root: Optional[Path] = None,
    inventory_path: Optional[Path] = None,
    model_call: Optional[ModelCall] = None,
    skip_commit_check: bool = False,
    top_k: int = 30,
    acceptance_contract_config: Optional[dict] = None,
    validated_claims_path: Optional[Path] = None,
    validated_claims_sha256: Optional[str] = None,
) -> dict:
    """Run generation-only candidate creation. Returns machine-readable result."""
    if authorization_acknowledgement != AUTHORIZATION_ACK:
        raise GenerationError(
            "Refusing to transmit private evidence without explicit authorization "
            f"acknowledgement ({AUTHORIZATION_ACK})",
            authorization_acknowledgement=authorization_acknowledgement,
        )
    if not generation_only:
        raise GenerationError(
            "CLI is generation-only; pass --generation-only",
            generation_only=generation_only,
        )

    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    if skip_commit_check:
        commit_info = {
            "checkout_commit": required_commit,
            "origin_main_commit": required_commit,
            "required_commit": required_commit,
            "provenance_source": "skipped",
            "skipped": True,
        }
    else:
        commit_info = assert_commits_match(root, required_commit)

    # Acceptance contract: fail closed before model generation when configured.
    load_status, contract_view, load_error, acceptance_provenance = (
        load_configured_acceptance_contract(acceptance_contract_config)
    )
    if acceptance_contract_config and load_status != ac.LOAD_OK:
        raise GenerationError(
            "Acceptance contract unavailable or invalid for configured benchmark run",
            acceptance_contract_load_status=load_status,
            acceptance_contract_error_code=load_error,
            acceptance_contract=acceptance_provenance.get("acceptance_contract"),
        )

    # Optional single-path Q2 validated claims handoff from preflight.
    handoff_path, handoff_sha = resolve_validated_claims_handoff_args(
        path=str(validated_claims_path) if validated_claims_path else None,
        sha256=validated_claims_sha256,
    )
    validated_claims_doc: Optional[dict[str, Any]] = None
    validated_claims_provenance: Optional[dict[str, Any]] = None
    if handoff_path is not None:
        if not acceptance_contract_config:
            _fail_validated_claims("validated_claims_requires_acceptance_contract")
        cfg = acceptance_contract_config
        validated_claims_doc = load_and_verify_validated_claims(
            handoff_path,
            expected_sha256=str(handoff_sha or ""),
            benchmark_id=str(cfg.get("benchmark_id") or ""),
            question_id=str(cfg.get("question_id") or question_id),
            acceptance_contract_object_key=str(cfg.get("object_key") or ""),
            acceptance_contract_content_sha256=str(cfg.get("content_sha256") or ""),
        )
        if str(validated_claims_doc.get("question_id") or "") != str(question_id):
            _fail_validated_claims("validated_claims_question_mismatch")
        validated_claims_provenance = validated_claims_safe_provenance(
            validated_claims_doc
        )

    inputs = load_permitted_case_inputs(
        Path(case_root),
        question_id,
        inventory_path=inventory_path,
        repo_root=root,
    )
    documents = build_documents_from_permitted_inputs(
        inputs["page_records"],
        inputs["inventory"],
        inputs["exhibit_map"],
    )
    retrieval = run_production_retrieval(
        documents,
        inputs["case_map"],
        inputs["question_text"],
        top_k=top_k,
    )
    # Attach structure map to retrieval for party-role evidence routing only when
    # schema-current; never fabricate ranges from a stale/absent map.
    structure_map = inputs.get("complaint_structure_map")
    if isinstance(structure_map, dict) and cs.is_current_structure_schema(structure_map):
        retrieval = dict(retrieval)
        retrieval["complaint_structure_map"] = structure_map
        if de.detect_party_role_question_intent(inputs["question_text"]):
            roadmap = cs.select_party_role_complaint_roadmap_context(structure_map)
            if roadmap:
                retrieval["complaint_structure_context"] = roadmap

    # Carry contract-required ranges/categories without discarding factual_layout.
    if contract_view is not None:
        merged = cs.merge_contract_structure_requirements(
            retrieval.get("complaint_structure_context"),
            contract_view.structure_requirements.as_safe_dict(),
        )
        if merged is not None:
            retrieval = dict(retrieval)
            retrieval["complaint_structure_context"] = merged

    # Q2 / relief: route structure-backed WHEREFORE pages into retrieval before
    # hit-page subsetting so synthesis receives cited complaint relief records.
    if de.detect_relief_question_intent(inputs["question_text"]):
        retrieval = de.route_complaint_relief_evidence(
            retrieval,
            question=inputs["question_text"],
            documents=documents,
            complaint_structure_map=structure_map
            if isinstance(structure_map, dict)
            else None,
        )

    inspection = audit_serialized_model_input(
        inputs["question_text"],
        retrieval,
        case_map=inputs["case_map"],
        complaint_structure_map=structure_map
        if isinstance(structure_map, dict)
        else None,
        documents=documents,
    )

    docs_subset = _documents_for_hit_pages(
        list(retrieval.get("results") or []), documents
    )
    reasoner_result = de.answer_attorney_record_question(
        inputs["question_text"],
        retrieval,
        documents=docs_subset,
        case_map=inputs["case_map"],
        exhibit_context=None,
        allowed_sources=[],
        complaint_structure_map=structure_map
        if isinstance(structure_map, dict)
        else None,
        model_call=model_call,
    )

    audit = reasoner_result.get("audit") or {}
    provider_calls = int(audit.get("party_role_provider_calls") or 0)
    repair_attempted = bool(audit.get("party_role_repair_attempted"))
    completeness_failed = bool(audit.get("party_role_completeness_failed"))
    # Non-party questions: treat a single successful READY call as complete.
    if "party_role_provider_calls" not in audit:
        provider_calls = 1 if reasoner_result.get("status") == de.STATUS_READY else 0

    initial_ok = (not repair_attempted) and reasoner_result.get("status") == de.STATUS_READY
    repair_ok = repair_attempted and reasoner_result.get("status") == de.STATUS_READY
    completeness = {
        "initial_completeness_validation": (
            "PASS" if initial_ok else ("FAIL" if repair_attempted else "PASS")
        ),
        "repair_invoked": repair_attempted,
        "repair_validation": (
            "Not Needed"
            if not repair_attempted
            else ("PASS" if repair_ok else "FAIL")
        ),
        "party_role_provider_calls": provider_calls,
        "party_role_completeness_failed": completeness_failed,
        "missing_party_role_attributes": audit.get("missing_party_role_attributes") or [],
        "party_role_synthesis_patch_audit_reason": audit.get(
            "party_role_synthesis_patch_audit_reason"
        ),
        "party_role_synthesis_category_lifecycle": audit.get(
            "party_role_synthesis_category_lifecycle"
        )
        or [],
    }

    finalized = (
        reasoner_result.get("status") == de.STATUS_READY and not completeness_failed
    )
    if not finalized:
        raise GenerationError(
            "Production completeness validation failed after at most one bounded "
            "repair; candidate not finalized",
            completeness_validation=completeness,
            reasoner_status=reasoner_result.get("status"),
            reasoner_audit=audit,
            provider_calls=provider_calls,
            finalized=False,
        )

    # Cap: production path already enforces <=1 repair; defend in CLI result.
    if provider_calls > 2:
        raise GenerationError(
            "Provider call budget exceeded (expected at most one initial call "
            "and at most one bounded repair)",
            provider_calls=provider_calls,
        )

    # Privacy-safe Q2 evidence-routing diagnostics (metadata only). Built from
    # the same production evidence packet the reasoner consumed; never alters
    # synthesis, scrub, canonicalization, or acceptance outcomes.
    q2_diagnostics = None
    evidence_packet: Optional[dict[str, Any]] = None
    if de.detect_relief_question_intent(inputs["question_text"]):
        evidence_packet = de.build_evidence_packet(
            inputs["question_text"],
            retrieval,
            case_map=inputs["case_map"],
            documents=docs_subset,
            complaint_structure_map=structure_map
            if isinstance(structure_map, dict)
            else None,
        )
        q2_diagnostics = build_q2_production_evidence_diagnostics(
            evidence_packet=evidence_packet,
            reasoner_result=reasoner_result,
            proposed_before_canonical=str(
                reasoner_result.get("proposed_answer") or ""
            ),
        )

    # Final acceptance-contract validation after synthesis / repair / cleanup /
    # Markdown canonicalization. The exact canonical string is what JSON and
    # Markdown both serialize; fail closed if presentation rewriting drops any
    # previously satisfied presence/evidence/semantic criterion.
    if contract_view is not None:
        proposed = str(reasoner_result.get("proposed_answer") or "")
        reasoner_audit_pre = reasoner_result.get("audit") or {}
        if validated_claims_doc is not None:
            # Single-path handoff: use the exact preflight-validated claims.
            # Do not rebuild or overwrite from evidence_packet / model audit.
            verified_claims = verified_relief_claims_from_validated(
                validated_claims_doc
            )
        elif evidence_packet is not None:
            # Backward-compatible path (no validated handoff supplied).
            verified_claims = de.structured_verified_relief_claims_from_supported(
                de.extract_supported_complaint_relief(evidence_packet)
            )
        else:
            verified_claims = reasoner_audit_pre.get("verified_relief_claims")
            if not isinstance(verified_claims, list):
                verified_claims = None
        validated_evidence = validated_acceptance_evidence_text(
            reasoner_result
        )
        acceptance_claims_doc = validated_claims_doc
        q1_claim_extraction_diagnostics: Optional[dict[str, Any]] = None
        if (
            acceptance_claims_doc is None
            and question_id == "Q1"
            and de.detect_party_role_question_intent(inputs["question_text"])
        ):
            q1_claim_extraction_diagnostics = {}
            acceptance_claims_doc = build_q1_validated_party_claims(
                reasoner_result,
                evidence_packet=inspection.get("evidence_packet"),
                diagnostics_out=q1_claim_extraction_diagnostics,
            )
            typed_summary = render_q1_validated_party_claims(
                acceptance_claims_doc
            )
            if normalize_proposed_answer_whitespace(typed_summary).lower() not in (
                normalize_proposed_answer_whitespace(proposed).lower()
            ):
                proposed = f"{proposed.rstrip()}\n\n{typed_summary}".strip()
        q1_retention_diagnostics: Optional[dict[str, Any]] = (
            {} if (
                isinstance(acceptance_claims_doc, Mapping)
                and acceptance_claims_doc.get("schema_version")
                == ac.Q1_VALIDATED_PARTY_CLAIMS_SCHEMA_VERSION
            ) else None
        )
        canonical, validation = finalize_canonical_answer_against_contract(
            proposed,
            contract_view,
            verified_relief_claims=verified_claims,
            validated_claims=acceptance_claims_doc,
            validated_evidence_text=validated_evidence,
            q1_retention_diagnostics_out=q1_retention_diagnostics,
        )
        if (
            isinstance(acceptance_claims_doc, Mapping)
            and acceptance_claims_doc.get("schema_version")
            == ac.Q1_VALIDATED_PARTY_CLAIMS_SCHEMA_VERSION
        ):
            missing_typed_claim_fields = q1_missing_rendered_claim_fields(
                canonical, acceptance_claims_doc
            )
            if missing_typed_claim_fields:
                raise GenerationError(
                    "Canonical Q1 answer dropped typed party claims",
                    reason_code="q1_typed_claim_rendering_lost",
                    missing_typed_claim_fields=missing_typed_claim_fields,
                    q1_claim_extraction_diagnostics=q1_claim_extraction_diagnostics,
                    q1_retention_diagnostics=q1_retention_diagnostics,
                    finalized=False,
                )
        if q2_diagnostics is not None:
            q2_diagnostics = build_q2_production_evidence_diagnostics(
                evidence_packet=evidence_packet,
                reasoner_result=reasoner_result,
                proposed_before_canonical=proposed,
                canonical=canonical,
                validation=validation,
            )
        acceptance_provenance = ac.safe_provenance_record(
            load_status=load_status,
            view=contract_view,
            validation=validation,
        )
        if not validation.ok:
            err_kwargs: dict[str, Any] = {
                "acceptance_contract": acceptance_provenance.get(
                    "acceptance_contract"
                ),
                "finalized": False,
            }
            if q2_diagnostics is not None:
                err_kwargs[DIAGNOSTIC_RESULT_KEY] = q2_diagnostics
            if q1_claim_extraction_diagnostics is not None:
                err_kwargs["q1_claim_extraction_diagnostics"] = (
                    q1_claim_extraction_diagnostics
                )
            if validated_claims_provenance is not None:
                err_kwargs.update(validated_claims_provenance)
            raise GenerationError(
                "Acceptance-contract validation failed; candidate not finalized",
                **err_kwargs,
            )
        reasoner_result = dict(reasoner_result)
        reasoner_result["proposed_answer"] = canonical
        reasoner_audit = dict(reasoner_result.get("audit") or {})
        reasoner_audit["acceptance_contract_validation_ok"] = True
        reasoner_audit["acceptance_contract_canonical_validated"] = True
        # Authoritative claims list must win before artifact serialization.
        if verified_claims is not None:
            reasoner_audit["verified_relief_claims"] = verified_claims
        if validated_claims_provenance is not None:
            reasoner_audit.update(validated_claims_provenance)
            reasoner_audit["validated_claims_handoff_applied"] = True
        reasoner_result["audit"] = reasoner_audit

    out_root = Path(candidate_output_root)
    out_root.mkdir(parents=True, exist_ok=True)
    stamp = _utc_stamp()
    out_dir = out_root / f"{question_id.lower()}-candidate-{stamp}"
    if out_dir.exists():
        out_dir = out_root / f"{question_id.lower()}-candidate-{stamp}.{_sha256_bytes(stamp.encode())[:8]}"

    if validated_claims_provenance is not None:
        acceptance_provenance = dict(acceptance_provenance or {})
        acceptance_provenance.update(validated_claims_provenance)

    written = write_candidate_artifacts(
        out_dir,
        question_id=question_id,
        question_text=inputs["question_text"],
        required_commit=required_commit,
        reasoner_result=reasoner_result,
        model_input_audit=inspection["audit"],
        commit_info=commit_info,
        completeness=completeness,
        acceptance_provenance=acceptance_provenance,
    )

    result_payload: dict[str, Any] = {
        "ok": True,
        "finalized": True,
        "candidate_directory": str(out_dir.resolve()),
        "files": {name: str(path) for name, path in written.items()},
        "completeness_validation": completeness,
        "provider_calls": provider_calls,
        "repair_invoked": repair_attempted,
        "reasoner_status": reasoner_result.get("status"),
        "commit": commit_info,
        "model_input_audit": inspection["audit"],
        "acceptance_contract": acceptance_provenance.get("acceptance_contract"),
    }
    if validated_claims_provenance is not None:
        result_payload.update(validated_claims_provenance)
        result_payload["validated_claims_handoff_applied"] = True
    if q2_diagnostics is not None:
        # Retained on the machine-readable run result (GHA artifact, 7 days);
        # never uploaded to canonical B2 candidate objects.
        result_payload[DIAGNOSTIC_RESULT_KEY] = q2_diagnostics
    return result_payload


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Generate an attorney-feedback candidate answer using the production "
            "retrieval/drafting path (generation-only)."
        )
    )
    p.add_argument(
        "--case-root",
        type=Path,
        required=True,
        help="Case corpus root containing derived page/exhibit/case-map inputs.",
    )
    p.add_argument(
        "--question-id",
        required=True,
        help="Question identifier (for example Q1).",
    )
    p.add_argument(
        "--required-commit",
        required=True,
        help="Repository commit that HEAD and origin/main must equal.",
    )
    p.add_argument(
        "--candidate-output-root",
        type=Path,
        required=True,
        help="Directory under which a new timestamped candidate folder is created.",
    )
    p.add_argument(
        "--authorize-private-evidence-transmission",
        required=True,
        dest="authorization_acknowledgement",
        help=(
            "Explicit acknowledgement string required before private evidence may "
            f"be sent to a model provider. Must equal: {AUTHORIZATION_ACK}"
        ),
    )
    p.add_argument(
        "--generation-only",
        action="store_true",
        required=True,
        help="Required. Restricts the CLI to generation (no evaluation).",
    )
    p.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root for commit preflight (default: inferred).",
    )
    p.add_argument(
        "--inventory-path",
        type=Path,
        default=None,
        help="Optional explicit NYSCEF inventory path.",
    )
    p.add_argument(
        "--acceptance-contract-object-key",
        default=None,
        help=(
            "Private acceptance-contract B2 object key (or set "
            f"{ACCEPTANCE_CONTRACT_OBJECT_KEY_ENV}). When set, the run fails "
            "closed unless the contract loads and authenticates."
        ),
    )
    p.add_argument(
        "--acceptance-contract-benchmark-id",
        default=None,
        help=(
            "Explicit benchmark identity expected in the acceptance contract "
            f"(or set {ACCEPTANCE_CONTRACT_BENCHMARK_ID_ENV}). Required when "
            "an object key is configured."
        ),
    )
    p.add_argument(
        "--acceptance-contract-content-sha256",
        default=None,
        help=(
            "Expected content SHA-256 for the acceptance contract (or set "
            f"{ACCEPTANCE_CONTRACT_CONTENT_SHA256_ENV}). Required for B2 loads."
        ),
    )
    p.add_argument(
        "--acceptance-contract-json-path",
        type=Path,
        default=None,
        help=(
            "Optional local JSON path for acceptance-contract bytes (tests / "
            "offline). Never commit private benchmark contracts."
        ),
    )
    p.add_argument(
        "--validated-claims-path",
        type=Path,
        default=None,
        help=(
            "Optional privacy-safe validated structured-claims JSON from Q2 "
            f"preflight (or set {VALIDATED_CLAIMS_PATH_ENV}). When set, "
            "generation verifies the canonical SHA and uses that exact claims "
            "collection instead of rebuilding from evidence_packet."
        ),
    )
    p.add_argument(
        "--validated-claims-sha256",
        default=None,
        help=(
            "Expected SHA-256 of the canonical validated claims JSON (or set "
            f"{VALIDATED_CLAIMS_SHA256_ENV}). Required with --validated-claims-path."
        ),
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    acceptance_config = resolve_acceptance_contract_config(
        question_id=args.question_id,
        object_key=args.acceptance_contract_object_key,
        benchmark_id=args.acceptance_contract_benchmark_id,
        content_sha256=args.acceptance_contract_content_sha256,
        json_path=args.acceptance_contract_json_path,
    )
    try:
        result = run_generation(
            case_root=args.case_root,
            question_id=args.question_id,
            required_commit=args.required_commit,
            candidate_output_root=args.candidate_output_root,
            authorization_acknowledgement=args.authorization_acknowledgement,
            generation_only=bool(args.generation_only),
            repo_root=args.repo_root,
            inventory_path=args.inventory_path,
            acceptance_contract_config=acceptance_config,
            validated_claims_path=args.validated_claims_path,
            validated_claims_sha256=args.validated_claims_sha256,
        )
    except GenerationError as exc:
        payload = {
            "ok": False,
            "finalized": False,
            "blocker": exc.blocker,
            **exc.details,
        }
        sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        return 1
    except Exception as exc:  # noqa: BLE001
        payload = {
            "ok": False,
            "finalized": False,
            "blocker": f"{type(exc).__name__}: {exc}",
        }
        sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        return 1

    sys.stdout.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
