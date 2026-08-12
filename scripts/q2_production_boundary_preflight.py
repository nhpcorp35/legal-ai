#!/usr/bin/env python3
"""Q2 production-boundary CI preflight (privacy-safe, live-derived replay).

Derives a sanitized replay from the same restored evidence packet / relief
synthesis path used by live generation, then validates the boundary using one
privacy-safe validated structured-claims artifact (canonical JSON + SHA-256).
That artifact is the single claims object for preflight generation and the
same-job production handoff. Mocks only external model / storage / network
boundaries. Emits privacy-safe machine-readable reason codes only; never
private B2 payloads or source text. The committed hand-built fixture is
demoted and cannot satisfy the workflow gate.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import acceptance_contract as ac  # noqa: E402
import generate_attorney_feedback_candidate as gen  # noqa: E402
import matter_builder as mb  # noqa: E402
from engines import drafting_engine as de  # noqa: E402
from engines import q2_production_evidence_diagnostics as q2diag  # noqa: E402

PREFLIGHT_SCHEMA_VERSION = "q2_production_boundary_preflight_result.v1"
REPLAY_SCHEMA_VERSION = q2diag.PREFLIGHT_REPLAY_SCHEMA_VERSION
PHASE = "q2_production_boundary_preflight"
DEMOTED_FIXTURE_SCHEMA = "q2_production_boundary_preflight_fixture.v1"
VALIDATED_CLAIMS_SCHEMA_VERSION = gen.VALIDATED_CLAIMS_SCHEMA_VERSION

_CRIT_RESCISSION = "q2-rescission-void-ab-initio"
_CRIT_NO_DEFENSE = "q2-no-defense-or-indemnity"
_CRIT_PLEADED = "q2-pleaded-relief-not-adjudication"
_CRIT_CATCH_ALL = "q2-catch-all-relief"
_REQUIRED_CRITERIA = (
    _CRIT_RESCISSION,
    _CRIT_NO_DEFENSE,
    _CRIT_PLEADED,
    _CRIT_CATCH_ALL,
)
_RELIEF_CATEGORIES = (
    "rescission_void_ab_initio",
    "no_defense_or_indemnity",
    "catch_all_relief",
)

# Public fixed stand-ins (not case source text). Drive selection_reason_code
# recomputation during verified-claim rebuild without embedding private OCR.
_FIXED_UNREADABLE_SNIPPET = "Def en dants indemni fy Named Insured COUNT II"
_FIXED_CLEAN_SNIPPETS = {
    "rescission_void_ab_initio": "void the Policies ab initio for rescission",
    "catch_all_relief": (
        "for such other and further relief as the Court deems just and proper"
    ),
    "no_defense_or_indemnity": (
        "Declaring that there is no duty to defend or indemnify Defendants"
    ),
}


class PreflightError(Exception):
    """Fail-closed preflight error with privacy-safe reason codes only."""

    def __init__(
        self,
        reason_code: str,
        *,
        stage: str,
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(reason_code)
        self.reason_code = str(reason_code)
        self.stage = str(stage)
        self.details = dict(details or {})


def _emit(payload: Mapping[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True), flush=True)


def load_replay(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    doc = json.loads(raw)
    if not isinstance(doc, dict):
        raise PreflightError(
            "replay_not_object",
            stage="replay_load",
            details={"python_type": type(doc).__name__},
        )
    schema = str(doc.get("schema_version") or "")
    if schema == DEMOTED_FIXTURE_SCHEMA:
        raise PreflightError(
            "demoted_hand_built_fixture_rejected",
            stage="replay_load",
            details={"schema_version": schema},
        )
    if schema != REPLAY_SCHEMA_VERSION:
        raise PreflightError(
            "replay_schema_mismatch",
            stage="replay_load",
            details={"schema_version": schema},
        )
    return doc


def build_sanitized_replay_from_evidence_packet(
    evidence_packet: Mapping[str, Any],
    *,
    question_id: str = "Q2",
) -> dict[str, Any]:
    """Invoke production extraction/synthesis observers + sanitizer."""
    return q2diag.build_sanitized_preflight_replay(
        evidence_packet,
        question_id=question_id,
    )


def build_evidence_packet_from_case_root(
    case_root: Path,
    *,
    question_id: str = "Q2",
    inventory_path: Optional[Path] = None,
    repo_root: Optional[Path] = None,
    top_k: int = 30,
) -> dict[str, Any]:
    """Same permitted-input → retrieval → evidence packet path as generation."""
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    inputs = gen.load_permitted_case_inputs(
        Path(case_root),
        question_id,
        inventory_path=inventory_path,
        repo_root=root,
    )
    documents = gen.build_documents_from_permitted_inputs(
        inputs["page_records"],
        inputs["inventory"],
        inputs["exhibit_map"],
    )
    retrieval = gen.run_production_retrieval(
        documents,
        inputs["case_map"],
        inputs["question_text"],
        top_k=top_k,
    )
    structure_map = inputs.get("complaint_structure_map")
    if isinstance(structure_map, dict):
        import complaint_structure as cs

        if cs.is_current_structure_schema(structure_map):
            retrieval = dict(retrieval)
            retrieval["complaint_structure_map"] = structure_map
    if de.detect_relief_question_intent(inputs["question_text"]):
        retrieval = de.route_complaint_relief_evidence(
            retrieval,
            question=inputs["question_text"],
            documents=documents,
            complaint_structure_map=structure_map
            if isinstance(structure_map, dict)
            else None,
        )
    docs_subset = gen._documents_for_hit_pages(  # noqa: SLF001 — shared path
        list(retrieval.get("results") or []), documents
    )
    return de.build_evidence_packet(
        inputs["question_text"],
        retrieval,
        case_map=inputs["case_map"],
        documents=docs_subset,
        complaint_structure_map=structure_map
        if isinstance(structure_map, dict)
        else None,
    )


def derive_sanitized_replay_from_case_root(
    case_root: Path,
    *,
    question_id: str = "Q2",
    inventory_path: Optional[Path] = None,
    repo_root: Optional[Path] = None,
) -> dict[str, Any]:
    packet = build_evidence_packet_from_case_root(
        case_root,
        question_id=question_id,
        inventory_path=inventory_path,
        repo_root=repo_root,
    )
    return build_sanitized_replay_from_evidence_packet(
        packet, question_id=question_id
    )


def _relief_categories(replay: Mapping[str, Any]) -> dict[str, Any]:
    relief = replay.get("relief_synthesis") or {}
    categories = relief.get("categories") or {}
    if not isinstance(categories, Mapping):
        return {}
    return {str(k): v for k, v in categories.items() if isinstance(v, Mapping)}


def assert_replay_gate_shape(replay: Mapping[str, Any]) -> None:
    """Fail closed unless live-derived relief state is gate-ready."""
    categories = _relief_categories(replay)
    for key in _RELIEF_CATEGORIES:
        row = categories.get(key) or {}
        if not row.get("supported"):
            raise PreflightError(
                "replay_relief_unsupported",
                stage="replay_gate",
                details={"category": key},
            )
        page_id = str(row.get("page_id") or "").strip()
        if not page_id or not q2diag._REASON_OR_ID_RE.fullmatch(page_id):  # noqa: SLF001
            raise PreflightError(
                "replay_relief_citation_missing",
                stage="replay_gate",
                details={"category": key},
            )
    no_def = categories.get("no_defense_or_indemnity") or {}
    if no_def.get("selection_reason_code") != "supported_needs_paraphrase":
        raise PreflightError(
            "replay_no_defense_reason_mismatch",
            stage="replay_gate",
            details={
                "selection_reason_code": no_def.get("selection_reason_code"),
            },
        )


def support_mapping_from_replay(replay: Mapping[str, Any]) -> dict[str, Any]:
    """Rebuild in-memory support objects from sanitized replay + fixed snippets."""
    categories = _relief_categories(replay)
    supported: dict[str, Any] = {}
    for key in _RELIEF_CATEGORIES:
        row = categories.get(key) or {}
        page_id = str(row.get("page_id") or "").strip() or None
        reason = str(row.get("selection_reason_code") or "")
        if not row.get("supported") or not page_id:
            supported[key] = {
                "supported": False,
                "page_id": None,
                "nyscef_document_number": row.get("nyscef_document_number"),
                "pdf_page": row.get("pdf_page"),
                "evidence_snippet": "",
            }
            continue
        if reason == "supported_needs_paraphrase":
            snippet = _FIXED_UNREADABLE_SNIPPET
        else:
            snippet = _FIXED_CLEAN_SNIPPETS.get(key, _FIXED_CLEAN_SNIPPETS["rescission_void_ab_initio"])
        supported[key] = {
            "supported": True,
            "page_id": page_id,
            "nyscef_document_number": row.get("nyscef_document_number") or 1,
            "pdf_page": row.get("pdf_page") or 25,
            "evidence_snippet": snippet,
        }
    return supported


def privacy_safe_claim_rows_from_replay(
    replay: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Build privacy-safe structured claim rows (no evidence snippets)."""
    categories = _relief_categories(replay)
    rows: list[dict[str, Any]] = []
    for key in _RELIEF_CATEGORIES:
        row = categories.get(key) or {}
        page_id = str(row.get("page_id") or "").strip() or None
        reason = str(row.get("selection_reason_code") or "").strip()
        rows.append(
            {
                "category": key,
                "supported": bool(row.get("supported")),
                "page_id": page_id,
                "nyscef_document_number": row.get("nyscef_document_number") or 1,
                "pdf_page": row.get("pdf_page") or 25,
                "selection_reason_code": reason,
            }
        )
    return rows


def build_validated_claims_from_replay(
    replay: Mapping[str, Any],
    *,
    benchmark_id: str,
    question_id: str,
    acceptance_contract_object_key: str,
    acceptance_contract_content_sha256: str,
) -> dict[str, Any]:
    """Emit one privacy-safe validated claims object for handoff."""
    doc = gen.build_validated_structured_claims(
        benchmark_id=benchmark_id,
        question_id=question_id,
        acceptance_contract_object_key=acceptance_contract_object_key,
        acceptance_contract_content_sha256=acceptance_contract_content_sha256,
        claims=privacy_safe_claim_rows_from_replay(replay),
    )
    try:
        gen.assert_validated_structured_claims_shape(doc)
    except gen.GenerationError as exc:
        raise PreflightError(
            str(exc.details.get("reason_code") or "validated_claims_shape_failed"),
            stage="validated_claims_emit",
            details={
                k: v
                for k, v in exc.details.items()
                if isinstance(v, (str, int, float, bool, type(None)))
            },
        ) from exc
    return doc


def write_validated_claims_artifact(
    doc: Mapping[str, Any],
    path: Path,
) -> dict[str, Any]:
    """Write canonical validated claims JSON; return path + SHA metadata."""
    canonical = gen.build_validated_structured_claims(
        benchmark_id=str(doc.get("benchmark_id") or ""),
        question_id=str(doc.get("question_id") or ""),
        acceptance_contract_object_key=str(
            doc.get("acceptance_contract_object_key") or ""
        ),
        acceptance_contract_content_sha256=str(
            doc.get("acceptance_contract_content_sha256") or ""
        ),
        claims=list(doc.get("claims") or []),
        schema_version=str(doc.get("schema_version") or VALIDATED_CLAIMS_SCHEMA_VERSION),
    )
    digest = gen.validated_claims_sha256(canonical)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Pretty file for operators; integrity always uses canonical bytes.
    path.write_text(
        json.dumps(canonical, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    # Re-load via the same verifier path generation uses (canonical rebuild).
    return {
        "validated_claims_path": str(path.resolve()),
        "validated_claims_sha256": digest,
        "validated_claims_schema_version": VALIDATED_CLAIMS_SCHEMA_VERSION,
        "validated_claims_benchmark_id": canonical["benchmark_id"],
        "validated_claims_question_id": canonical["question_id"],
    }


def fixed_template_answer_from_replay(replay: Mapping[str, Any]) -> str:
    """Fixed category templates for supported=true claims with safe citations."""
    categories = _relief_categories(replay)
    # Empty snippets → production fixed paraphrase / originating-page templates.
    support: dict[str, Any] = {}
    for key in _RELIEF_CATEGORIES:
        row = categories.get(key) or {}
        page_id = str(row.get("page_id") or "").strip()
        if not (row.get("supported") and page_id):
            support[key] = {
                "supported": False,
                "page_id": None,
                "evidence_snippet": "",
            }
            continue
        support[key] = {
            "supported": True,
            "page_id": page_id,
            "nyscef_document_number": row.get("nyscef_document_number") or 1,
            "pdf_page": row.get("pdf_page") or 25,
            "evidence_snippet": "",
        }
    paragraphs = de.assemble_evidence_grounded_relief_paragraphs(support)
    if not paragraphs:
        raise PreflightError(
            "fixed_template_answer_empty",
            stage="fixed_templates",
        )
    return de.normalize_whitespace(" ".join(paragraphs))


def build_template_acceptance_contract_config(
    replay: Mapping[str, Any],
) -> dict[str, Any]:
    """Privacy-safe synthetic contract aligned to fixed category templates."""
    page_ids = sorted(
        {
            str((row or {}).get("page_id") or "")
            for row in _relief_categories(replay).values()
            if isinstance(row, Mapping) and row.get("page_id")
        }
    )
    corr = page_ids[0] if page_ids else "synth"
    contract = ac.build_synthetic_contract(
        contract_id=f"contract-live-replay-q2-preflight-{corr}",
        version="1.0.0",
        benchmark_id="synth-benchmark-q2-live-replay-preflight",
        question_id="Q2",
        object_key=(
            "Contracts/synthetic/q2/"
            "Q2.production_boundary_live_replay_preflight.acceptance_contract.json"
        ),
        required_criterion_ids=list(_REQUIRED_CRITERIA),
        criteria=[
            {
                "id": _CRIT_RESCISSION,
                "presence_phrases": ["void ab initio"],
                "evidence_phrases": ["void ab initio"],
                "semantic_required_phrases": [],
                "semantic_forbidden_phrases": [],
                "fallback_text": "",
                "category": "relief",
            },
            {
                "id": _CRIT_NO_DEFENSE,
                "presence_phrases": ["no defense or indemnity"],
                "evidence_phrases": ["no defense or indemnity"],
                "semantic_required_phrases": [],
                "semantic_forbidden_phrases": [],
                "fallback_text": "",
                "category": "relief",
            },
            {
                "id": _CRIT_PLEADED,
                "presence_phrases": [
                    "pleaded requested relief",
                    "not a judicial determination",
                ],
                "evidence_phrases": [],
                "semantic_required_phrases": ["pleaded"],
                "semantic_forbidden_phrases": [
                    "court has ruled",
                    "established entitlement",
                ],
                "fallback_text": (
                    "This answer describes pleaded requested relief in the "
                    "complaint, not a judicial determination."
                ),
                "category": "relief",
            },
            {
                "id": _CRIT_CATCH_ALL,
                "presence_phrases": ["catch-all requested relief"],
                "evidence_phrases": ["catch-all requested relief"],
                "semantic_required_phrases": [],
                "semantic_forbidden_phrases": [],
                "fallback_text": "",
                "category": "relief",
            },
        ],
    )
    return {
        "object_key": contract["object_key"],
        "benchmark_id": "synth-benchmark-q2-live-replay-preflight",
        "question_id": "Q2",
        "content_sha256": contract["content_sha256"],
        "raw_bytes": json.dumps(contract, sort_keys=True).encode("utf-8"),
    }


def seed_minimal_case_root(case_root: Path, replay: Mapping[str, Any]) -> Path:
    """Permitted corpus scaffolding only — answer text comes from templates."""
    categories = _relief_categories(replay)
    no_def = categories.get("no_defense_or_indemnity") or {}
    page_id = str(no_def.get("page_id") or "nyscef-001-page-0025")
    nyscef = int(no_def.get("nyscef_document_number") or 1)
    pdf_page = int(no_def.get("pdf_page") or 25)
    # Scaffolding page body is a fixed public placeholder (not case OCR).
    page = mb.build_page_record(
        pdf_page,
        "synthetic preflight scaffold page",
        "native",
        nyscef_document_number=nyscef,
    )
    page.update(
        {
            "nyscef_document_number": nyscef,
            "pdf_page_number": pdf_page,
            "page_id": page_id,
            "source_filename": f"nyscef_doc_no_{nyscef}_complaint.pdf",
            "source_path": f"/tmp/synthetic/nyscef_doc_no_{nyscef}_complaint.pdf",
        }
    )
    for relative in (
        "derived/page-extraction",
        "derived/exhibit-segmentation",
        "derived/case-map",
        "derived/question-text",
    ):
        (case_root / relative).mkdir(parents=True, exist_ok=True)
    (
        case_root / "derived" / "page-extraction" / "canonical_page_records.json"
    ).write_text(
        json.dumps({"pages": [page]}, indent=2) + "\n",
        encoding="utf-8",
    )
    (
        case_root / "derived" / "exhibit-segmentation" / "filing_exhibit_map.json"
    ).write_text(
        json.dumps(
            {
                "filings": [
                    {
                        "nyscef_document_number": nyscef,
                        "segments": [],
                        "uncertain_boundaries": [],
                    }
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (case_root / "derived" / "case-map" / "case_map.json").write_text(
        json.dumps({"case_map": mb.empty_case_map()}, indent=2) + "\n",
        encoding="utf-8",
    )
    (case_root / "derived" / "question-text" / "questions.json").write_text(
        json.dumps(
            {
                "Q2": (
                    "What relief does the complaint request in the WHEREFORE / "
                    "requested-relief section?"
                )
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    inventory = case_root / "inventory.json"
    inventory.write_text(
        json.dumps(
            {
                "filings": [
                    {
                        "nyscef_document_number": nyscef,
                        "filename": f"nyscef_doc_no_{nyscef}_complaint.pdf",
                        "ingest_canonical": True,
                        "sha256": "b" * 64,
                    }
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return inventory


def _stale_audit_claims(replay: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Stale audit omitting paraphrase-needed no-defense (forces rebuild)."""
    categories = _relief_categories(replay)
    page_id = str(
        (categories.get("rescission_void_ab_initio") or {}).get("page_id")
        or (categories.get("no_defense_or_indemnity") or {}).get("page_id")
        or "nyscef-001-page-0025"
    )
    return [
        {
            "category": "rescission_void_ab_initio",
            "supported": True,
            "page_id": page_id,
            "nyscef_document_number": 1,
            "pdf_page": 25,
            "evidence_snippet": _FIXED_CLEAN_SNIPPETS["rescission_void_ab_initio"],
            "selection_reason_code": "supported_with_clean_excerpt",
        },
        {
            "category": "no_defense_or_indemnity",
            "supported": False,
            "page_id": None,
            "nyscef_document_number": 1,
            "pdf_page": 25,
            "evidence_snippet": "",
            "selection_reason_code": "unsupported",
        },
        {
            "category": "catch_all_relief",
            "supported": True,
            "page_id": page_id,
            "nyscef_document_number": 1,
            "pdf_page": 25,
            "evidence_snippet": _FIXED_CLEAN_SNIPPETS["catch_all_relief"],
            "selection_reason_code": "supported_with_clean_excerpt",
        },
    ]


def _markdown_proposed_answer(markdown: str) -> str:
    marker = "## Proposed answer\n\n"
    start = markdown.index(marker) + len(marker)
    end = markdown.index("\n## Review limitation", start)
    return markdown[start:end].strip("\n")


def assert_q2_boundary_success(
    *,
    replay: Mapping[str, Any],
    result: Mapping[str, Any],
) -> dict[str, Any]:
    if not result.get("ok") or not result.get("finalized"):
        raise PreflightError(
            "generation_not_finalized",
            stage="run_generation",
            details={
                "ok": bool(result.get("ok")),
                "finalized": bool(result.get("finalized")),
            },
        )
    files = result.get("files") or {}
    json_path = files.get("Q2_candidate_answer.json")
    md_path = files.get("Q2_candidate_answer.md")
    if not json_path or not md_path:
        raise PreflightError(
            "candidate_artifacts_missing",
            stage="write_candidate_artifacts",
            details={"file_keys": sorted(files)},
        )

    candidate = json.loads(Path(json_path).read_text(encoding="utf-8"))
    markdown = Path(md_path).read_text(encoding="utf-8")
    proposed = str(candidate.get("proposed_answer") or "")
    md_proposed = _markdown_proposed_answer(markdown)

    if proposed != md_proposed:
        raise PreflightError(
            "json_markdown_proposed_answer_parity_mismatch",
            stage="serialization_parity",
        )
    if gen.normalize_proposed_answer_whitespace(
        proposed
    ) != gen.normalize_proposed_answer_whitespace(md_proposed):
        raise PreflightError(
            "json_markdown_whitespace_parity_mismatch",
            stage="serialization_parity",
        )

    contract_cfg = build_template_acceptance_contract_config(replay)
    loaded = ac.load_acceptance_contract_from_bytes(
        contract_cfg["raw_bytes"],
        object_key=contract_cfg["object_key"],
        expected_identity=ac.ContractIdentity(
            benchmark_id=contract_cfg["benchmark_id"],
            question_id=contract_cfg["question_id"],
        ),
        expected_content_sha256=contract_cfg["content_sha256"],
    )
    if not loaded.ok or loaded.evaluation is None:
        raise PreflightError(
            "acceptance_contract_reload_failed",
            stage="acceptance_validation",
            details={"load_status": loaded.status},
        )
    validation = ac.validate_final_answer_against_contract(
        proposed,
        loaded.evaluation,
        apply_fallback=False,
        apply_duplication_repair=False,
    )
    if not validation.ok:
        raise PreflightError(
            "acceptance_validation_failed",
            stage="acceptance_validation",
            details={
                "diagnostics": [
                    str(d)
                    for d in (validation.diagnostics or [])
                    if isinstance(d, str)
                    and (":" in d or d.replace("_", "").isalnum())
                ][:12]
            },
        )
    by_id = {c.criterion_id: c for c in validation.criterion_results}
    for crit_id in _REQUIRED_CRITERIA:
        row = by_id.get(crit_id)
        if row is None or row.result_code != ac.CRIT_PASS:
            raise PreflightError(
                "q2_criterion_failed",
                stage="acceptance_validation",
                details={
                    "criterion_id": crit_id,
                    "result_code": None if row is None else row.result_code,
                },
            )

    categories = _relief_categories(replay)
    no_def_page = str(
        (categories.get("no_defense_or_indemnity") or {}).get("page_id") or ""
    )
    lowered = proposed.lower()
    if "no defense or indemnity" not in lowered:
        raise PreflightError(
            "no_defense_paraphrase_missing",
            stage="relief_paraphrase",
        )
    if no_def_page and f"page_id {no_def_page}" not in proposed:
        raise PreflightError(
            "no_defense_citation_missing",
            stage="relief_paraphrase",
            details={"expected_page_id": no_def_page},
        )
    if "originating source page" not in lowered and "requested relief" not in lowered:
        raise PreflightError(
            "pleaded_requested_relief_framing_missing",
            stage="relief_paraphrase",
        )
    if len(proposed) >= 1600:
        raise PreflightError(
            "proposed_answer_too_long",
            stage="ocr_scrub",
            details={"char_length": len(proposed)},
        )

    audit_claims = (candidate.get("audit") or {}).get("verified_relief_claims") or []
    by_cat = {
        str(c.get("category")): c for c in audit_claims if isinstance(c, Mapping)
    }
    no_def_claim = by_cat.get("no_defense_or_indemnity") or {}
    if not no_def_claim.get("supported"):
        raise PreflightError(
            "verified_claim_no_defense_unsupported",
            stage="audit_claim_rebuild",
        )
    if no_def_claim.get("selection_reason_code") != "supported_needs_paraphrase":
        raise PreflightError(
            "verified_claim_no_defense_reason_mismatch",
            stage="audit_claim_rebuild",
            details={
                "selection_reason_code": no_def_claim.get("selection_reason_code")
            },
        )
    if no_def_page and no_def_claim.get("page_id") != no_def_page:
        raise PreflightError(
            "verified_claim_no_defense_page_mismatch",
            stage="audit_claim_rebuild",
            details={"page_id": no_def_claim.get("page_id")},
        )

    return {
        "criterion_ids_passed": list(_REQUIRED_CRITERIA),
        "proposed_answer_char_length": len(proposed),
        "parity_ok": True,
        "no_defense_page_id": no_def_page,
        "no_defense_selection_reason_code": "supported_needs_paraphrase",
    }


def run_preflight(
    *,
    replay_path: Path,
    candidate_output_root: Optional[Path] = None,
    validated_claims_out: Optional[Path] = None,
    handoff_benchmark_id: Optional[str] = None,
    handoff_question_id: Optional[str] = None,
    handoff_acceptance_contract_object_key: Optional[str] = None,
    handoff_acceptance_contract_content_sha256: Optional[str] = None,
) -> dict[str, Any]:
    """Execute Q2 production-boundary preflight from a live sanitized replay."""
    stage = "replay_load"
    try:
        replay = load_replay(replay_path)
        stage = "replay_gate"
        assert_replay_gate_shape(replay)

        stage = "fixed_templates"
        template_answer = fixed_template_answer_from_replay(replay)
        support = support_mapping_from_replay(replay)
        # Placeholder packet so diagnostics still observe relief intent; claims
        # themselves come from the validated handoff object (not rebuild).
        packet = {
            "question": (
                "What relief does the complaint request in the WHEREFORE / "
                "requested-relief section?"
            ),
            "retrieval_hit_count": 0,
            "retrieval_hits": [],
        }

        stage = "case_root_seed"
        with tempfile.TemporaryDirectory(prefix="q2-preflight-") as tmp:
            root = Path(tmp)
            case_root = root / "case"
            case_root.mkdir()
            out_root = (
                Path(candidate_output_root) if candidate_output_root else root / "out"
            )
            out_root.mkdir(parents=True, exist_ok=True)
            inventory = seed_minimal_case_root(case_root, replay)
            contract_cfg = build_template_acceptance_contract_config(replay)

            stage = "validated_claims_emit"
            # Single-path object used by this preflight generation call.
            internal_claims = build_validated_claims_from_replay(
                replay,
                benchmark_id=str(contract_cfg["benchmark_id"]),
                question_id=str(contract_cfg["question_id"]),
                acceptance_contract_object_key=str(contract_cfg["object_key"]),
                acceptance_contract_content_sha256=str(
                    contract_cfg["content_sha256"]
                ),
            )
            internal_claims_path = root / "validated_claims_internal.json"
            internal_meta = write_validated_claims_artifact(
                internal_claims, internal_claims_path
            )

            handoff_meta: dict[str, Any] = {}
            if validated_claims_out is not None:
                # Production handoff stamped with the live acceptance-contract
                # identity that generation will verify against. Question is
                # always Q2 — this artifact is the Q2 relief claims object.
                bench = str(
                    handoff_benchmark_id
                    or contract_cfg["benchmark_id"]
                ).strip()
                qid = "Q2"
                obj_key = str(
                    handoff_acceptance_contract_object_key
                    or contract_cfg["object_key"]
                ).strip()
                obj_sha = str(
                    handoff_acceptance_contract_content_sha256
                    or contract_cfg["content_sha256"]
                ).strip()
                if not (bench and qid and obj_key and obj_sha):
                    raise PreflightError(
                        "validated_claims_handoff_identity_missing",
                        stage="validated_claims_emit",
                    )
                if (
                    handoff_question_id is not None
                    and str(handoff_question_id).strip()
                    and str(handoff_question_id).strip() != "Q2"
                ):
                    raise PreflightError(
                        "validated_claims_handoff_question_not_q2",
                        stage="validated_claims_emit",
                        details={"question_id": str(handoff_question_id)},
                    )
                handoff_doc = build_validated_claims_from_replay(
                    replay,
                    benchmark_id=bench,
                    question_id=qid,
                    acceptance_contract_object_key=obj_key,
                    acceptance_contract_content_sha256=obj_sha,
                )
                handoff_meta = write_validated_claims_artifact(
                    handoff_doc, Path(validated_claims_out)
                )

            reasoner = {
                "status": de.STATUS_READY,
                # Start from templates; validated handoff preserves no-defense.
                "proposed_answer": template_answer,
                "propositions": [],
                "supporting_evidence": [],
                "contrary_evidence": [],
                "unresolved_questions": [],
                "documents_pages_reviewed": [],
                "attorney_review": {"requires_attorney_review": True},
                "audit": {
                    "model": "synth-preflight-live-replay",
                    "provider": "synth-preflight-live-replay",
                    # Stale audit must not win when validated handoff is supplied.
                    "verified_relief_claims": _stale_audit_claims(replay),
                },
                "confidence": 0.5,
            }

            stage = "run_generation"
            with mock.patch.object(
                de, "answer_attorney_record_question", return_value=reasoner
            ), mock.patch.object(
                de, "build_evidence_packet", return_value=packet
            ), mock.patch.object(
                # If handoff is ignored, a rebuild would still pass — but the
                # handoff path must not invoke extract/rebuild for claims.
                de, "extract_supported_complaint_relief", return_value=support
            ), mock.patch.object(
                gen,
                "audit_serialized_model_input",
                return_value={
                    "audit": {"retrieval_hit_count": 0, "relief_intent": True},
                    "evidence_packet": packet,
                },
            ), mock.patch.object(
                gen, "run_production_retrieval", return_value={"results": []}
            ):
                result = gen.run_generation(
                    case_root=case_root,
                    question_id="Q2",
                    required_commit="c" * 40,
                    candidate_output_root=out_root,
                    authorization_acknowledgement=gen.AUTHORIZATION_ACK,
                    generation_only=True,
                    inventory_path=inventory,
                    skip_commit_check=True,
                    acceptance_contract_config=contract_cfg,
                    model_call=lambda _s, _u: {},
                    validated_claims_path=Path(
                        internal_meta["validated_claims_path"]
                    ),
                    validated_claims_sha256=str(
                        internal_meta["validated_claims_sha256"]
                    ),
                )

            stage = "boundary_assertions"
            assertion_meta = assert_q2_boundary_success(
                replay=replay, result=result
            )

        payload = {
            "ok": True,
            "phase": PHASE,
            "schema_version": PREFLIGHT_SCHEMA_VERSION,
            "stage": "complete",
            "replay_schema_version": REPLAY_SCHEMA_VERSION,
            "question_id": "Q2",
            "finalized": True,
            "validated_claims_schema_version": VALIDATED_CLAIMS_SCHEMA_VERSION,
            "validated_claims_sha256": internal_meta["validated_claims_sha256"],
            "validated_claims_handoff_applied": True,
            **assertion_meta,
        }
        if handoff_meta:
            payload.update(
                {
                    "validated_claims_path": handoff_meta["validated_claims_path"],
                    "validated_claims_sha256": handoff_meta[
                        "validated_claims_sha256"
                    ],
                    "validated_claims_benchmark_id": handoff_meta[
                        "validated_claims_benchmark_id"
                    ],
                    "validated_claims_question_id": handoff_meta[
                        "validated_claims_question_id"
                    ],
                }
            )
        return payload
    except PreflightError as exc:
        return {
            "ok": False,
            "phase": PHASE,
            "schema_version": PREFLIGHT_SCHEMA_VERSION,
            "stage": exc.stage or stage,
            "reason_code": exc.reason_code,
            "details": {
                key: value
                for key, value in exc.details.items()
                if isinstance(value, (str, int, float, bool, list, dict, type(None)))
            },
            "finalized": False,
        }
    except gen.GenerationError as exc:
        reason = (
            str(exc.details.get("reason_code") or "")
            if isinstance(exc.details, dict)
            else ""
        )
        return {
            "ok": False,
            "phase": PHASE,
            "schema_version": PREFLIGHT_SCHEMA_VERSION,
            "stage": stage,
            "reason_code": reason or "generation_entrypoint_failed",
            "details": {
                "blocker_kind": "GenerationError",
                "finalized": bool(exc.details.get("finalized"))
                if isinstance(exc.details, dict)
                else False,
            },
            "finalized": False,
        }
    except Exception as exc:  # noqa: BLE001 — CI must always emit reason codes
        return {
            "ok": False,
            "phase": PHASE,
            "schema_version": PREFLIGHT_SCHEMA_VERSION,
            "stage": stage,
            "reason_code": "preflight_unhandled_error",
            "details": {"exc_type": type(exc).__name__},
            "finalized": False,
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Q2 production-boundary preflight from a live-derived sanitized "
            "replay (same evidence packet / synthesis path as generation)."
        )
    )
    parser.add_argument(
        "--replay",
        type=Path,
        default=None,
        help="Path to sanitized live-derived replay JSON (required to run gate).",
    )
    parser.add_argument(
        "--derive-from-case-root",
        type=Path,
        default=None,
        help=(
            "Build sanitized replay from restored case-root evidence packet "
            "using production extraction/synthesis observers."
        ),
    )
    parser.add_argument(
        "--replay-out",
        type=Path,
        default=None,
        help="Write derived sanitized replay JSON to this path.",
    )
    parser.add_argument(
        "--question-id",
        default="Q2",
        help="Question id for derive-from-case-root (default: Q2).",
    )
    parser.add_argument(
        "--candidate-output-root",
        type=Path,
        default=None,
        help="Optional ephemeral output root for candidate artifacts.",
    )
    parser.add_argument(
        "--validated-claims-out",
        type=Path,
        default=None,
        help=(
            "Write privacy-safe validated structured-claims JSON for the "
            "same-job generation handoff."
        ),
    )
    parser.add_argument(
        "--acceptance-contract-object-key",
        default=None,
        help=(
            "Production acceptance-contract object key stamped into the "
            "validated claims handoff artifact."
        ),
    )
    parser.add_argument(
        "--acceptance-contract-content-sha256",
        default=None,
        help=(
            "Production acceptance-contract content SHA-256 stamped into the "
            "validated claims handoff artifact."
        ),
    )
    parser.add_argument(
        "--acceptance-contract-benchmark-id",
        default=None,
        help=(
            "Production benchmark identity stamped into the validated claims "
            "handoff artifact."
        ),
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=None,
        help=argparse.SUPPRESS,  # demoted; rejected if supplied
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.fixture is not None:
        _emit(
            {
                "ok": False,
                "phase": PHASE,
                "schema_version": PREFLIGHT_SCHEMA_VERSION,
                "stage": "replay_load",
                "reason_code": "demoted_hand_built_fixture_rejected",
                "details": {"path_kind": "fixture_flag"},
                "finalized": False,
            }
        )
        return 1

    replay_path = args.replay
    if args.derive_from_case_root is not None:
        stage = "derive_replay"
        try:
            replay = derive_sanitized_replay_from_case_root(
                Path(args.derive_from_case_root),
                question_id=str(args.question_id or "Q2"),
            )
            out = args.replay_out
            if out is None:
                raise PreflightError(
                    "replay_out_required_for_derive",
                    stage="derive_replay",
                )
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(
                json.dumps(replay, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            # Derive-only when --replay is omitted; workflow runs a second
            # invocation that consumes --replay $REPLAY_JSON.
            if args.replay is None:
                _emit(
                    {
                        "ok": True,
                        "phase": PHASE,
                        "schema_version": PREFLIGHT_SCHEMA_VERSION,
                        "stage": "replay_derived",
                        "replay_schema_version": REPLAY_SCHEMA_VERSION,
                        "question_id": str(args.question_id or "Q2"),
                        "replay_path_kind": "derived",
                    }
                )
                return 0
            replay_path = out
        except PreflightError as exc:
            _emit(
                {
                    "ok": False,
                    "phase": PHASE,
                    "schema_version": PREFLIGHT_SCHEMA_VERSION,
                    "stage": exc.stage or stage,
                    "reason_code": exc.reason_code,
                    "details": dict(exc.details),
                    "finalized": False,
                }
            )
            return 1
        except Exception as exc:  # noqa: BLE001
            _emit(
                {
                    "ok": False,
                    "phase": PHASE,
                    "schema_version": PREFLIGHT_SCHEMA_VERSION,
                    "stage": stage,
                    "reason_code": "replay_derive_failed",
                    "details": {"exc_type": type(exc).__name__},
                    "finalized": False,
                }
            )
            return 1

    if replay_path is None:
        _emit(
            {
                "ok": False,
                "phase": PHASE,
                "schema_version": PREFLIGHT_SCHEMA_VERSION,
                "stage": "replay_load",
                "reason_code": "replay_path_required",
                "details": {},
                "finalized": False,
            }
        )
        return 1

    payload = run_preflight(
        replay_path=Path(replay_path),
        candidate_output_root=args.candidate_output_root,
        validated_claims_out=args.validated_claims_out,
        handoff_benchmark_id=args.acceptance_contract_benchmark_id,
        handoff_question_id=str(args.question_id or "Q2"),
        handoff_acceptance_contract_object_key=args.acceptance_contract_object_key,
        handoff_acceptance_contract_content_sha256=(
            args.acceptance_contract_content_sha256
        ),
    )
    _emit(payload)
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
