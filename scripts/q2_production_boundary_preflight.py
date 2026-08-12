#!/usr/bin/env python3
"""Q2 production-boundary CI preflight (privacy-safe, deterministic).

Invokes the same public generation entrypoint used by
``scripts/run_case00_b2_q1.py --generation-only`` — namely
``generate_attorney_feedback_candidate.run_generation`` through finalization
and ``write_candidate_artifacts``.

Mocks only external model / storage / network boundaries. Does not bypass
relief synthesis claim rebuild, canonical serialization, or acceptance
validation. Emits privacy-safe machine-readable reason codes only; never
private B2 payloads or benchmark prose dumps.
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

DEFAULT_FIXTURE_PATH = (
    REPO_ROOT / "testdata" / "q2_production_boundary_31629603939_fixture.json"
)

PREFLIGHT_SCHEMA_VERSION = "q2_production_boundary_preflight_result.v1"
PHASE = "q2_production_boundary_preflight"

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


def load_fixture(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    doc = json.loads(raw)
    if not isinstance(doc, dict):
        raise PreflightError(
            "fixture_not_object",
            stage="fixture_load",
            details={"python_type": type(doc).__name__},
        )
    if doc.get("schema_version") != "q2_production_boundary_preflight_fixture.v1":
        raise PreflightError(
            "fixture_schema_mismatch",
            stage="fixture_load",
            details={"schema_version": str(doc.get("schema_version") or "")},
        )
    return doc


def build_evidence_packet(fixture: Mapping[str, Any]) -> dict[str, Any]:
    page_25 = str(fixture["page_ids"]["page_25"])
    page_26 = str(fixture["page_ids"]["page_26"])
    return {
        "question": str(fixture["question_text"]),
        "retrieval_hit_count": 2,
        "retrieval_hits": [
            {
                "result_id": "hit-synth-31629603939-p25",
                "page_id": page_25,
                "nyscef_document_number": 1,
                "pdf_page": 25,
                "document_type": "complaint",
                "excerpt": str(fixture["page_25_excerpt"]),
                "page_text": str(fixture["page_25_page_text"]),
                "classifications": ["legal_position"],
                "score": 0.91,
            },
            {
                "result_id": "hit-synth-31629603939-p26",
                "page_id": page_26,
                "nyscef_document_number": 1,
                "pdf_page": 26,
                "document_type": "complaint",
                "excerpt": str(fixture["page_26_excerpt"]),
                "classifications": ["legal_position"],
                "score": 0.85,
            },
        ],
    }


def build_quote_gap_answer(fixture: Mapping[str, Any]) -> str:
    page_25 = str(fixture["page_ids"]["page_25"])
    ocr_quote = str(fixture["ocr_rescission_quote_body"])
    catch = str(fixture["clean_catch_all_excerpt"])
    return (
        "This answer describes pleaded requested relief in the complaint, "
        "not a judicial determination. The complaint requests a declaration "
        "that coverage is void ab initio based on alleged material "
        "misrepresentations and non-disclosures, as reflected in the cited "
        f'pleading language: "{ocr_quote}" '
        f"(page_id {page_25}). The complaint also includes "
        "catch-all requested relief, as reflected in the cited pleading "
        f'language: "{catch}" '
        f"(page_id {page_25})."
    )


def build_acceptance_contract_config(fixture: Mapping[str, Any]) -> dict[str, Any]:
    spec = fixture["acceptance_contract"]
    contract = ac.build_synthetic_contract(
        contract_id=str(spec["contract_id"]),
        version=str(spec["version"]),
        benchmark_id=str(spec["benchmark_id"]),
        question_id=str(spec["question_id"]),
        object_key=str(spec["object_key"]),
        required_criterion_ids=list(spec["required_criterion_ids"]),
        criteria=list(spec["criteria"]),
    )
    return {
        "object_key": contract["object_key"],
        "benchmark_id": str(spec["benchmark_id"]),
        "question_id": str(spec["question_id"]),
        "content_sha256": contract["content_sha256"],
        "raw_bytes": json.dumps(contract, sort_keys=True).encode("utf-8"),
    }


def seed_minimal_case_root(case_root: Path, fixture: Mapping[str, Any]) -> Path:
    """Permitted corpus scaffolding only — evidence comes from the fixture packet."""
    nyscef = 1
    page_id = str(fixture["page_ids"]["page_25"])
    page = mb.build_page_record(
        25,
        str(fixture["page_25_page_text"]),
        "native",
        nyscef_document_number=nyscef,
    )
    page.update(
        {
            "nyscef_document_number": nyscef,
            "pdf_page_number": 25,
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
        json.dumps({"Q2": str(fixture["question_text"])}, indent=2) + "\n",
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


def assert_fixture_diagnostic_shape(fixture: Mapping[str, Any], packet: Mapping[str, Any]) -> None:
    """Confirm the synthetic packet matches the production diagnostic structure."""
    cache = q2diag.diagnose_restored_cache_evidence(packet)
    if int(cache.get("hit_record_count") or 0) != 2:
        raise PreflightError(
            "fixture_hit_count_mismatch",
            stage="fixture_shape",
            details={"hit_record_count": cache.get("hit_record_count")},
        )
    hits = list(cache.get("hits") or [])
    if len(hits) != 2:
        raise PreflightError(
            "fixture_hit_list_mismatch",
            stage="fixture_shape",
            details={"hits_len": len(hits)},
        )
    page_25 = str(fixture["page_ids"]["page_25"])
    page_26 = str(fixture["page_ids"]["page_26"])
    by_page = {str(h.get("page_id")): h for h in hits}
    if page_25 not in by_page or page_26 not in by_page:
        raise PreflightError(
            "fixture_page_id_mismatch",
            stage="fixture_shape",
            details={"page_ids": sorted(by_page)},
        )
    h25 = by_page[page_25]
    h26 = by_page[page_26]
    if not (
        h25.get("excerpt", {}).get("present")
        and h25.get("page_text", {}).get("present")
        and int(h25.get("page_text", {}).get("char_length") or 0)
        > int(h25.get("excerpt", {}).get("char_length") or 0)
    ):
        raise PreflightError(
            "fixture_page25_length_shape_mismatch",
            stage="fixture_shape",
        )
    if not (
        h26.get("excerpt", {}).get("present")
        and not h26.get("page_text", {}).get("present")
        and int(h26.get("page_text", {}).get("char_length") or 0) == 0
    ):
        raise PreflightError(
            "fixture_page26_excerpt_only_shape_mismatch",
            stage="fixture_shape",
        )

    relief = q2diag.diagnose_relief_synthesis(packet)
    expected = fixture["expected_relief_selection_reason_codes"]
    categories = relief.get("categories") or {}
    for category, expected_code in expected.items():
        row = categories.get(category) or {}
        if not row.get("supported"):
            raise PreflightError(
                "fixture_relief_unsupported",
                stage="fixture_shape",
                details={"category": category},
            )
        if row.get("selection_reason_code") != expected_code:
            raise PreflightError(
                "fixture_relief_selection_reason_mismatch",
                stage="fixture_shape",
                details={
                    "category": category,
                    "expected": expected_code,
                    "actual": row.get("selection_reason_code"),
                },
            )
    no_def = categories.get("no_defense_or_indemnity") or {}
    if no_def.get("page_id") != page_25:
        raise PreflightError(
            "fixture_no_defense_page_id_mismatch",
            stage="fixture_shape",
            details={"page_id": no_def.get("page_id")},
        )


def _markdown_proposed_answer(markdown: str) -> str:
    marker = "## Proposed answer\n\n"
    start = markdown.index(marker) + len(marker)
    end = markdown.index("\n## Review limitation", start)
    return markdown[start:end].strip("\n")


def assert_q2_boundary_success(
    *,
    fixture: Mapping[str, Any],
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

    contract_cfg = build_acceptance_contract_config(fixture)
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

    lowered = proposed.lower()
    page_25 = str(fixture["page_ids"]["page_25"])
    if "no defense or indemnity" not in lowered:
        raise PreflightError(
            "no_defense_paraphrase_missing",
            stage="relief_paraphrase",
        )
    if f"page_id {page_25}" not in proposed:
        raise PreflightError(
            "no_defense_citation_missing",
            stage="relief_paraphrase",
            details={"expected_page_id": page_25},
        )
    if "originating source page" not in lowered and "requested relief" not in lowered:
        raise PreflightError(
            "pleaded_requested_relief_framing_missing",
            stage="relief_paraphrase",
        )
    for banned in fixture.get("banned_ocr_markers") or []:
        if str(banned) in proposed:
            raise PreflightError(
                "ocr_artifact_present",
                stage="ocr_scrub",
                details={"marker_kind": "banned_ocr_marker"},
            )
    if str(fixture["page_25_page_text"]) in proposed:
        raise PreflightError(
            "page_text_dump_present",
            stage="ocr_scrub",
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
    if no_def_claim.get("page_id") != page_25:
        raise PreflightError(
            "verified_claim_no_defense_page_mismatch",
            stage="audit_claim_rebuild",
            details={"page_id": no_def_claim.get("page_id")},
        )

    return {
        "criterion_ids_passed": list(_REQUIRED_CRITERIA),
        "proposed_answer_char_length": len(proposed),
        "parity_ok": True,
        "no_defense_page_id": page_25,
        "no_defense_selection_reason_code": "supported_needs_paraphrase",
    }


def _stale_audit_claims(fixture: Mapping[str, Any]) -> list[dict[str, Any]]:
    page_25 = str(fixture["page_ids"]["page_25"])
    catch = str(fixture["clean_catch_all_excerpt"])
    return [
        {
            "category": "rescission_void_ab_initio",
            "supported": True,
            "page_id": page_25,
            "nyscef_document_number": 1,
            "pdf_page": 25,
            "evidence_snippet": "void the Policies ab initio",
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
            "page_id": page_25,
            "nyscef_document_number": 1,
            "pdf_page": 25,
            "evidence_snippet": catch,
            "selection_reason_code": "supported_with_clean_excerpt",
        },
    ]


def run_preflight(
    *,
    fixture_path: Path,
    candidate_output_root: Optional[Path] = None,
) -> dict[str, Any]:
    """Execute deterministic Q2 production-boundary preflight; return result dict."""
    stage = "fixture_load"
    try:
        fixture = load_fixture(fixture_path)
        stage = "fixture_shape"
        packet = build_evidence_packet(fixture)
        assert_fixture_diagnostic_shape(fixture, packet)

        stage = "case_root_seed"
        with tempfile.TemporaryDirectory(prefix="q2-preflight-") as tmp:
            root = Path(tmp)
            case_root = root / "case"
            case_root.mkdir()
            out_root = Path(candidate_output_root) if candidate_output_root else root / "out"
            out_root.mkdir(parents=True, exist_ok=True)
            inventory = seed_minimal_case_root(case_root, fixture)
            contract_cfg = build_acceptance_contract_config(fixture)
            reasoner = {
                "status": de.STATUS_READY,
                "proposed_answer": build_quote_gap_answer(fixture),
                "propositions": [],
                "supporting_evidence": [],
                "contrary_evidence": [],
                "unresolved_questions": [],
                "documents_pages_reviewed": [],
                "attorney_review": {"requires_attorney_review": True},
                "audit": {
                    "model": "synth-preflight",
                    "provider": "synth-preflight",
                    "verified_relief_claims": _stale_audit_claims(fixture),
                },
                "confidence": 0.5,
            }

            stage = "run_generation"
            # Model / network / storage boundaries only. Packet injection keeps
            # the diagnostic shape deterministic; claim rebuild + finalize +
            # write_candidate_artifacts remain the real production path.
            with mock.patch.object(
                de, "answer_attorney_record_question", return_value=reasoner
            ), mock.patch.object(
                de, "build_evidence_packet", return_value=packet
            ), mock.patch.object(
                gen,
                "audit_serialized_model_input",
                return_value={
                    "audit": {"retrieval_hit_count": 2, "relief_intent": True},
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
                )

            stage = "boundary_assertions"
            assertion_meta = assert_q2_boundary_success(
                fixture=fixture, result=result
            )

        return {
            "ok": True,
            "phase": PHASE,
            "schema_version": PREFLIGHT_SCHEMA_VERSION,
            "stage": "complete",
            "diagnostic_run_correlation_id": fixture.get(
                "diagnostic_run_correlation_id"
            ),
            "question_id": "Q2",
            "finalized": True,
            **assertion_meta,
        }
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
        return {
            "ok": False,
            "phase": PHASE,
            "schema_version": PREFLIGHT_SCHEMA_VERSION,
            "stage": stage,
            "reason_code": "generation_entrypoint_failed",
            "details": {
                "blocker_kind": "GenerationError",
                # Never echo private blocker prose — classify only.
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
            "Deterministic Q2 production-boundary preflight using the same "
            "run_generation entrypoint as Case-00 generation-only CI."
        )
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=DEFAULT_FIXTURE_PATH,
        help="Privacy-safe synthetic fixture path (default: checked-in testdata).",
    )
    parser.add_argument(
        "--candidate-output-root",
        type=Path,
        default=None,
        help="Optional ephemeral output root for candidate artifacts.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    payload = run_preflight(
        fixture_path=Path(args.fixture),
        candidate_output_root=args.candidate_output_root,
    )
    _emit(payload)
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
