"""Verified active-matter intake materialization.

This module turns a supplied source ZIP and its hash manifest into a local,
page-preserving LegalAI corpus.  It deliberately performs no model calls and
never treats a filename as unverified evidence: every extracted PDF must be
listed in the manifest with the matching byte size and SHA-256.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CASE_ID_RE = re.compile(r"^NY-[A-Za-z]+-[0-9]{6}-[0-9]{4}-[A-Za-z0-9-]{2,80}$")
DOC_NUMBER_RE = re.compile(r"_(\d+)(?:\s*\(\d+\))?\.pdf$", re.IGNORECASE)


class ActiveMatterIntakeError(Exception):
    """Fail-closed active-matter intake error."""


@dataclass(frozen=True)
class VerifiedIntake:
    case_id: str
    source_bundle: Path
    manifest: Path
    source_sha256: str
    manifest_sha256: str
    documents: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class VerifiedMatter:
    """One base intake plus zero or more immutable document supplements."""

    case_id: str
    intakes: tuple[VerifiedIntake, ...]

    @property
    def documents(self) -> tuple[dict[str, Any], ...]:
        return tuple(item for intake in self.intakes for item in intake.documents)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_basename(value: object, *, field: str) -> str:
    name = Path(str(value or "")).name
    if not name or name != str(value or "") or name in {".", ".."}:
        raise ActiveMatterIntakeError(f"manifest {field} must be a filename")
    return name


def _manifest_documents(payload: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    documents = payload.get("documents")
    if not isinstance(documents, list) or not documents:
        raise ActiveMatterIntakeError("manifest must contain a non-empty documents list")
    normalized: list[dict[str, Any]] = []
    names: set[str] = set()
    for index, raw in enumerate(documents):
        if not isinstance(raw, Mapping):
            raise ActiveMatterIntakeError(f"manifest documents[{index}] must be an object")
        name = _safe_basename(raw.get("filename"), field=f"documents[{index}].filename")
        if Path(name).suffix.lower() != ".pdf":
            raise ActiveMatterIntakeError(f"manifest documents[{index}] must name a PDF")
        if name in names:
            raise ActiveMatterIntakeError(f"manifest contains duplicate filename: {name}")
        names.add(name)
        size = raw.get("size_bytes", raw.get("size"))
        if not isinstance(size, int) or size <= 0:
            raise ActiveMatterIntakeError(f"manifest documents[{index}].size must be a positive integer")
        digest = str(raw.get("sha256") or "").lower()
        if not SHA256_RE.fullmatch(digest):
            raise ActiveMatterIntakeError(f"manifest documents[{index}].sha256 is invalid")
        normalized.append({"filename": name, "size_bytes": size, "sha256": digest})
    return tuple(normalized)


def verify_intake_bundle(source_bundle: Path, manifest: Path, *, case_id: str | None = None) -> VerifiedIntake:
    """Verify an intake ZIP and manifest before exposing any PDF path."""
    source = Path(source_bundle).resolve()
    manifest_path = Path(manifest).resolve()
    if not source.is_file() or not manifest_path.is_file():
        raise ActiveMatterIntakeError("source bundle and manifest must both exist")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ActiveMatterIntakeError("manifest is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise ActiveMatterIntakeError("manifest root must be an object")
    resolved_case_id = str(case_id or payload.get("case_id") or "")
    if not CASE_ID_RE.fullmatch(resolved_case_id):
        raise ActiveMatterIntakeError("case_id has an unsupported format")
    documents = _manifest_documents(payload)
    try:
        archive = zipfile.ZipFile(source)
    except zipfile.BadZipFile as exc:
        raise ActiveMatterIntakeError("source bundle is not a valid ZIP") from exc
    expected = {item["filename"]: item for item in documents}
    found: dict[str, zipfile.ZipInfo] = {}
    with archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            member_path = Path(info.filename)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise ActiveMatterIntakeError("source bundle contains an unsafe path")
            name = Path(info.filename).name
            if not name:
                raise ActiveMatterIntakeError("source bundle contains an empty filename")
            if name not in expected:
                raise ActiveMatterIntakeError(f"source bundle contains unmanifested file: {name}")
            if name in found:
                raise ActiveMatterIntakeError(f"source bundle contains duplicate file: {name}")
            if info.file_size != expected[name]["size_bytes"]:
                raise ActiveMatterIntakeError(f"source bundle size mismatch: {name}")
            payload_bytes = archive.read(info)
            if sha256_bytes(payload_bytes) != expected[name]["sha256"]:
                raise ActiveMatterIntakeError(f"source bundle SHA-256 mismatch: {name}")
            found[name] = info
    if set(found) != set(expected):
        missing = sorted(set(expected) - set(found))
        raise ActiveMatterIntakeError("source bundle missing manifest files: " + ", ".join(missing))
    return VerifiedIntake(
        case_id=resolved_case_id,
        source_bundle=source,
        manifest=manifest_path,
        source_sha256=sha256_file(source),
        manifest_sha256=sha256_file(manifest_path),
        documents=documents,
    )


def verify_active_matter_intake(
    source_bundle: Path,
    manifest: Path,
    *,
    supplements: tuple[tuple[Path, Path], ...] = (),
    case_id: str | None = None,
) -> VerifiedMatter:
    """Verify the base bundle and every supplied supplement as one source set."""
    base = verify_intake_bundle(source_bundle, manifest, case_id=case_id)
    intakes = [base]
    names = {item["filename"] for item in base.documents}
    for supplement_source, supplement_manifest in supplements:
        supplement = verify_intake_bundle(
            supplement_source, supplement_manifest, case_id=base.case_id
        )
        duplicate = names.intersection(item["filename"] for item in supplement.documents)
        if duplicate:
            raise ActiveMatterIntakeError(
                "supplement duplicates an existing verified filename: " + ", ".join(sorted(duplicate))
            )
        names.update(item["filename"] for item in supplement.documents)
        intakes.append(supplement)
    return VerifiedMatter(case_id=base.case_id, intakes=tuple(intakes))


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def materialize_verified_pdfs(verified: VerifiedIntake | VerifiedMatter, destination: Path) -> Path:
    """Extract exactly the verified PDFs into an empty destination directory."""
    target = Path(destination).resolve()
    target.mkdir(parents=True, exist_ok=True)
    if any(target.iterdir()):
        raise ActiveMatterIntakeError("verified PDF destination must be empty")
    intakes = verified.intakes if isinstance(verified, VerifiedMatter) else (verified,)
    for source_set in intakes:
        expected = {item["filename"] for item in source_set.documents}
        with zipfile.ZipFile(source_set.source_bundle) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                name = Path(info.filename).name
                if name not in expected or (target / name).exists():
                    raise ActiveMatterIntakeError("source bundle changed after verification")
                (target / name).write_bytes(archive.read(info))
    return target


def build_filing_inventory(verified: VerifiedIntake | VerifiedMatter) -> dict[str, Any]:
    """Create the minimum deterministic inventory required by canonical ingestion."""
    filings: list[dict[str, Any]] = []
    for item in verified.documents:
        match = DOC_NUMBER_RE.search(item["filename"])
        if match is None:
            raise ActiveMatterIntakeError(
                "cannot derive NYSCEF document number from verified filename: "
                + item["filename"]
            )
        filings.append(
            {
                "nyscef_document_number": int(match.group(1)),
                "filename": item["filename"],
                "sha256": item["sha256"],
                "size_bytes": item["size_bytes"],
            }
        )
    filings.sort(key=lambda item: (item["nyscef_document_number"], item["filename"]))
    return {"case_id": verified.case_id, "filings": filings}


def write_active_matter_provenance(case_root: Path, verified: VerifiedIntake | VerifiedMatter) -> Path:
    """Write non-secret source provenance alongside derived artifacts."""
    destination = Path(case_root) / "derived" / "source-provenance" / "intake_provenance.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    intakes = verified.intakes if isinstance(verified, VerifiedMatter) else (verified,)
    payload = {
        "schema_version": "active-matter-intake-provenance.v1",
        "case_id": verified.case_id,
        "intake_sets": [
            {
                "source_bundle": {"filename": item.source_bundle.name, "size_bytes": item.source_bundle.stat().st_size, "sha256": item.source_sha256},
                "manifest": {"filename": item.manifest.name, "size_bytes": item.manifest.stat().st_size, "sha256": item.manifest_sha256},
            }
            for item in intakes
        ],
        "documents": list(verified.documents),
    }
    destination.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return destination


def verified_pdf_directory(verified: VerifiedIntake):
    """Yield a temporary directory containing only verified PDFs."""
    return tempfile.TemporaryDirectory(prefix="legalai-active-matter-")
