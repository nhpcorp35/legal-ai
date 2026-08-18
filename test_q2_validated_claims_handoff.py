"""Bounded tests for Q2 single-path validated structured-claims handoff.

Groups (each intended <5 minutes):
1. Workflow handoff wiring
2. Exact claims object reaches finalizer and artifact writer
3. Model/audit mutation cannot remove a validated claim
4. Tamper/hash/identity failures block publication
5. JSON/Markdown parity and all four Q2 criteria
6. No secret/private text leakage
"""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from engines import drafting_engine as de


REPO_ROOT = Path(__file__).resolve().parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "hal-case00-q1.yml"
PREFLIGHT_PATH = REPO_ROOT / "scripts" / "q2_production_boundary_preflight.py"
GEN_PATH = REPO_ROOT / "scripts" / "generate_attorney_feedback_candidate.py"
Q1_PATH = REPO_ROOT / "scripts" / "run_case00_b2_q1.py"

_SECRET = "SECRET_PRIVATE_OCR_SNIPPET_never_in_validated_claims_9f3a"
_SECRET_NAME = "PrivatePartyName_validated_claims_leak_test"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    if str(REPO_ROOT) not in os.sys.path:
        os.sys.path.insert(0, str(REPO_ROOT))
    os.sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


PRE = _load("q2_preflight_validated_claims", PREFLIGHT_PATH)
GEN = _load("gen_validated_claims", GEN_PATH)
Q1 = _load("run_case00_b2_q1_validated_claims", Q1_PATH)


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _load_workflow() -> dict:
    doc = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    if isinstance(doc, dict) and True in doc and "on" not in doc:
        doc["on"] = doc.pop(True)
    return doc


def _live_packet() -> dict:
    page = (
        "25\n\n"
        "184. entitled to void the Policies ab initio and for rescission. "
        f"{_SECRET} {_SECRET_NAME}\n"
        "COUNT II Declaring that there is no duty to defend or indemni fy "
        "Def en dants under the Policies.\n"
        "187. WHEREFORE for such other and further relief as the Court deems "
        "just and proper."
    )
    return {
        "question": (
            "What relief does the complaint request in the WHEREFORE / "
            "requested-relief section?"
        ),
        "retrieval_hit_count": 1,
        "retrieval_hits": [
            {
                "result_id": "hit-validated-claims",
                "page_id": "nyscef-001-page-0025",
                "nyscef_document_number": 1,
                "pdf_page": 25,
                "document_type": "complaint",
                "excerpt": page[:120],
                "page_text": page,
                "classifications": ["legal_position"],
                "score": 0.9,
            }
        ],
    }


def _replay() -> dict:
    return PRE.build_sanitized_replay_from_evidence_packet(_live_packet())


def _identity(**overrides):
    base = {
        "benchmark_id": "Case-00-Triborough",
        "question_id": "Q2",
        "object_key": (
            "Benchmarks/acceptance-contracts/case-00-triborough/"
            "q2/v1.0.0/acceptance_contract.json"
        ),
        "content_sha256": "a" * 64,
    }
    base.update(overrides)
    return base


def _claims_doc(replay=None, **identity_overrides) -> dict:
    ident = _identity(**identity_overrides)
    return PRE.build_validated_claims_from_replay(
        replay or _replay(),
        benchmark_id=ident["benchmark_id"],
        question_id=ident["question_id"],
        acceptance_contract_object_key=ident["object_key"],
        acceptance_contract_content_sha256=ident["content_sha256"],
    )


def _contract_cfg_from_ident(ident: dict, proposed_seed: str = "") -> dict:
    """Synthetic acceptance contract matching four Q2 criteria."""
    import acceptance_contract as ac

    contract = ac.build_synthetic_contract(
        contract_id="contract-validated-claims-handoff",
        version="1.0.0",
        benchmark_id=ident["benchmark_id"],
        question_id=ident["question_id"],
        object_key=ident["object_key"],
        required_criterion_ids=[
            "q2-rescission-void-ab-initio",
            "q2-no-defense-or-indemnity",
            "q2-pleaded-relief-not-adjudication",
            "q2-catch-all-relief",
        ],
        criteria=[
            {
                "id": "q2-rescission-void-ab-initio",
                "presence_phrases": ["void ab initio"],
                "evidence_phrases": ["void ab initio"],
                "semantic_required_phrases": [],
                "semantic_forbidden_phrases": [],
                "fallback_text": "",
                "category": "relief",
            },
            {
                "id": "q2-no-defense-or-indemnity",
                "presence_phrases": ["no defense or indemnity"],
                "evidence_phrases": ["no defense or indemnity"],
                "semantic_required_phrases": [],
                "semantic_forbidden_phrases": [],
                "fallback_text": "",
                "category": "relief",
            },
            {
                "id": "q2-pleaded-relief-not-adjudication",
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
                "id": "q2-catch-all-relief",
                "presence_phrases": ["catch-all requested relief"],
                "evidence_phrases": ["catch-all requested relief"],
                "semantic_required_phrases": [],
                "semantic_forbidden_phrases": [],
                "fallback_text": "",
                "category": "relief",
            },
        ],
    )
    # Align content hash / object key with handoff identity when overridden.
    raw = json.dumps(contract, sort_keys=True).encode("utf-8")
    # Use the synthetic contract's own hash unless caller pinned a fake sha
    # for negative tests; for positive tests rebuild identity from contract.
    return {
        "object_key": contract["object_key"],
        "benchmark_id": ident["benchmark_id"],
        "question_id": ident["question_id"],
        "content_sha256": contract["content_sha256"],
        "raw_bytes": raw,
        "_proposed_seed": proposed_seed,
        "_contract": contract,
    }


# ---------------------------------------------------------------------------
# 1. Workflow handoff wiring
# ---------------------------------------------------------------------------


class WorkflowHandoffWiringTests(unittest.TestCase):
    def test_preflight_emits_and_generation_consumes_validated_claims(self) -> None:
        text = _workflow_text()
        pre = text.split("Q2 production-boundary preflight", 1)[1].split(
            "Generate requested question", 1
        )[0]
        gen = text.split(
            "Generate requested question and publish five verified artifacts to B2",
            1,
        )[1].split("Upload machine-readable run result", 1)[0]
        self.assertIn("--validated-claims-out", pre)
        self.assertIn("VALIDATED_CLAIMS_JSON", pre)
        self.assertIn("validated_claims_sha256", pre)
        self.assertIn("--acceptance-contract-object-key", pre)
        self.assertIn("--acceptance-contract-content-sha256", pre)
        self.assertIn("--validated-claims-path", gen)
        self.assertIn("--validated-claims-sha256", gen)
        self.assertIn('QUESTION_ID" = "Q2"', gen)
        self.assertIn("scripts/run_case00_b2_q1.py", gen)

    def test_run_case00_forwards_validated_claims_flags(self) -> None:
        src = Q1_PATH.read_text(encoding="utf-8")
        self.assertIn("--validated-claims-path", src)
        self.assertIn("--validated-claims-sha256", src)
        self.assertIn("validated_claims_handoff_incomplete", src)


# ---------------------------------------------------------------------------
# 2. Exact claims object reaches finalizer + artifact writer
# ---------------------------------------------------------------------------


class ExactClaimsReachFinalizerTests(unittest.TestCase):
    def test_handoff_claims_reach_finalizer_and_artifacts(self) -> None:
        replay = _replay()
        ident_contract = _contract_cfg_from_ident(_identity())
        # Stamp claims with the real synthetic contract identity.
        doc = PRE.build_validated_claims_from_replay(
            replay,
            benchmark_id=ident_contract["benchmark_id"],
            question_id=ident_contract["question_id"],
            acceptance_contract_object_key=ident_contract["object_key"],
            acceptance_contract_content_sha256=ident_contract["content_sha256"],
        )
        template = PRE.fixed_template_answer_from_replay(replay)
        expected_claims = GEN.verified_relief_claims_from_validated(doc)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            claims_path = root / "claims.json"
            meta = PRE.write_validated_claims_artifact(doc, claims_path)
            case_root = root / "case"
            case_root.mkdir()
            inventory = PRE.seed_minimal_case_root(case_root, replay)
            out_root = root / "out"
            out_root.mkdir()

            captured: dict = {}

            real_finalize = GEN.finalize_canonical_answer_against_contract

            def _capture_finalize(
                proposed,
                view,
                verified_relief_claims=None,
                validated_claims=None,
                **kwargs,
            ):
                captured["verified_relief_claims"] = list(
                    verified_relief_claims or []
                )
                captured["validated_claims"] = validated_claims
                return real_finalize(
                    proposed,
                    view,
                    verified_relief_claims=verified_relief_claims,
                    validated_claims=validated_claims,
                    **kwargs,
                )

            reasoner = {
                "status": de.STATUS_READY,
                "proposed_answer": template,
                "propositions": [],
                "supporting_evidence": [],
                "contrary_evidence": [],
                "unresolved_questions": [],
                "documents_pages_reviewed": [],
                "attorney_review": {"requires_attorney_review": True},
                "audit": {
                    "model": "synth",
                    "provider": "synth",
                    "verified_relief_claims": PRE._stale_audit_claims(replay),
                },
                "confidence": 0.5,
            }
            packet = {
                "question": replay.get("question_id") or "Q2",
                "retrieval_hit_count": 0,
                "retrieval_hits": [],
            }

            with mock.patch.object(
                de, "answer_attorney_record_question", return_value=reasoner
            ), mock.patch.object(
                de, "build_evidence_packet", return_value=packet
            ), mock.patch.object(
                # Diagnostics may observe extract; claims must still come from handoff.
                de,
                "extract_supported_complaint_relief",
                return_value={
                    "rescission_void_ab_initio": {"supported": False},
                    "no_defense_or_indemnity": {"supported": False},
                    "catch_all_relief": {"supported": False},
                },
            ), mock.patch.object(
                GEN,
                "audit_serialized_model_input",
                return_value={
                    "audit": {"retrieval_hit_count": 0, "relief_intent": True},
                    "evidence_packet": packet,
                },
            ), mock.patch.object(
                GEN, "run_production_retrieval", return_value={"results": []}
            ), mock.patch.object(
                GEN,
                "finalize_canonical_answer_against_contract",
                side_effect=_capture_finalize,
            ):
                result = GEN.run_generation(
                    case_root=case_root,
                    question_id="Q2",
                    required_commit="c" * 40,
                    candidate_output_root=out_root,
                    authorization_acknowledgement=GEN.AUTHORIZATION_ACK,
                    generation_only=True,
                    inventory_path=inventory,
                    skip_commit_check=True,
                    acceptance_contract_config=ident_contract,
                    model_call=lambda _s, _u: {},
                    validated_claims_path=claims_path,
                    validated_claims_sha256=meta["validated_claims_sha256"],
                )

            self.assertTrue(result["ok"])
            self.assertTrue(result.get("validated_claims_handoff_applied"))
            self.assertEqual(
                captured["verified_relief_claims"],
                expected_claims,
            )
            self.assertEqual(captured.get("validated_claims"), doc)
            candidate = json.loads(
                Path(result["files"]["Q2_candidate_answer.json"]).read_text(
                    encoding="utf-8"
                )
            )
            audit = candidate.get("audit") or {}
            self.assertEqual(audit.get("verified_relief_claims"), expected_claims)
            self.assertEqual(
                audit.get("validated_claims_sha256"),
                meta["validated_claims_sha256"],
            )
            manifest = json.loads(
                Path(result["files"]["generation_manifest.json"]).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                manifest.get("validated_claims_sha256"),
                meta["validated_claims_sha256"],
            )
            self.assertEqual(
                manifest.get("validated_claims_schema_version"),
                GEN.VALIDATED_CLAIMS_SCHEMA_VERSION,
            )


# ---------------------------------------------------------------------------
# 3. Model/audit mutation cannot remove a validated claim
# ---------------------------------------------------------------------------


class MutationCannotRemoveValidatedClaimTests(unittest.TestCase):
    def test_stale_audit_and_packet_rebuild_cannot_drop_no_defense(self) -> None:
        replay = _replay()
        ident_contract = _contract_cfg_from_ident(_identity())
        doc = PRE.build_validated_claims_from_replay(
            replay,
            benchmark_id=ident_contract["benchmark_id"],
            question_id=ident_contract["question_id"],
            acceptance_contract_object_key=ident_contract["object_key"],
            acceptance_contract_content_sha256=ident_contract["content_sha256"],
        )
        template = PRE.fixed_template_answer_from_replay(replay)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            claims_path = root / "claims.json"
            meta = PRE.write_validated_claims_artifact(doc, claims_path)
            case_root = root / "case"
            case_root.mkdir()
            inventory = PRE.seed_minimal_case_root(case_root, replay)
            out_root = root / "out"
            out_root.mkdir()

            # Model/audit omits no-defense; packet extract would also omit it.
            stale = PRE._stale_audit_claims(replay)
            unsupported_support = {
                "rescission_void_ab_initio": {
                    "supported": True,
                    "page_id": "nyscef-001-page-0025",
                    "evidence_snippet": "void",
                },
                "no_defense_or_indemnity": {
                    "supported": False,
                    "page_id": None,
                    "evidence_snippet": "",
                },
                "catch_all_relief": {
                    "supported": True,
                    "page_id": "nyscef-001-page-0025",
                    "evidence_snippet": "further relief",
                },
            }
            reasoner = {
                "status": de.STATUS_READY,
                "proposed_answer": template,
                "propositions": [],
                "supporting_evidence": [],
                "contrary_evidence": [],
                "unresolved_questions": [],
                "documents_pages_reviewed": [],
                "attorney_review": {"requires_attorney_review": True},
                "audit": {
                    "model": "synth",
                    "provider": "synth",
                    "verified_relief_claims": stale,
                },
                "confidence": 0.5,
            }
            packet = {"question": "relief?", "retrieval_hit_count": 0, "retrieval_hits": []}

            with mock.patch.object(
                de, "answer_attorney_record_question", return_value=reasoner
            ), mock.patch.object(
                de, "build_evidence_packet", return_value=packet
            ), mock.patch.object(
                de,
                "extract_supported_complaint_relief",
                return_value=unsupported_support,
            ), mock.patch.object(
                GEN,
                "audit_serialized_model_input",
                return_value={
                    "audit": {"retrieval_hit_count": 0, "relief_intent": True},
                    "evidence_packet": packet,
                },
            ), mock.patch.object(
                GEN, "run_production_retrieval", return_value={"results": []}
            ):
                result = GEN.run_generation(
                    case_root=case_root,
                    question_id="Q2",
                    required_commit="c" * 40,
                    candidate_output_root=out_root,
                    authorization_acknowledgement=GEN.AUTHORIZATION_ACK,
                    generation_only=True,
                    inventory_path=inventory,
                    skip_commit_check=True,
                    acceptance_contract_config=ident_contract,
                    model_call=lambda _s, _u: {},
                    validated_claims_path=claims_path,
                    validated_claims_sha256=meta["validated_claims_sha256"],
                )

            candidate = json.loads(
                Path(result["files"]["Q2_candidate_answer.json"]).read_text(
                    encoding="utf-8"
                )
            )
            by_cat = {
                c["category"]: c
                for c in (candidate.get("audit") or {}).get(
                    "verified_relief_claims"
                )
                or []
            }
            no_def = by_cat["no_defense_or_indemnity"]
            self.assertTrue(no_def["supported"])
            self.assertEqual(
                no_def["selection_reason_code"], "supported_needs_paraphrase"
            )
            self.assertIn("no defense or indemnity", candidate["proposed_answer"].lower())


# ---------------------------------------------------------------------------
# 4. Tamper / hash / identity failures block publication
# ---------------------------------------------------------------------------


class TamperHashIdentityFailClosedTests(unittest.TestCase):
    def _run_with_claims(self, doc: dict, sha=None) -> None:
        replay = _replay()
        ident_contract = _contract_cfg_from_ident(
            {
                "benchmark_id": doc["benchmark_id"],
                "question_id": doc["question_id"],
                "object_key": doc["acceptance_contract_object_key"],
                "content_sha256": doc["acceptance_contract_content_sha256"],
            }
        )
        # Re-stamp so identities match the contract loader.
        doc = PRE.build_validated_claims_from_replay(
            replay,
            benchmark_id=ident_contract["benchmark_id"],
            question_id=ident_contract["question_id"],
            acceptance_contract_object_key=ident_contract["object_key"],
            acceptance_contract_content_sha256=ident_contract["content_sha256"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            claims_path = root / "claims.json"
            meta = PRE.write_validated_claims_artifact(doc, claims_path)
            if sha is None:
                sha = meta["validated_claims_sha256"]
            case_root = root / "case"
            case_root.mkdir()
            inventory = PRE.seed_minimal_case_root(case_root, replay)
            out_root = root / "out"
            out_root.mkdir()
            reasoner = {
                "status": de.STATUS_READY,
                "proposed_answer": PRE.fixed_template_answer_from_replay(replay),
                "propositions": [],
                "supporting_evidence": [],
                "contrary_evidence": [],
                "unresolved_questions": [],
                "documents_pages_reviewed": [],
                "attorney_review": {"requires_attorney_review": True},
                "audit": {"model": "synth", "provider": "synth"},
                "confidence": 0.5,
            }
            packet = {"question": "relief?", "retrieval_hit_count": 0, "retrieval_hits": []}
            with mock.patch.object(
                de, "answer_attorney_record_question", return_value=reasoner
            ), mock.patch.object(
                de, "build_evidence_packet", return_value=packet
            ), mock.patch.object(
                GEN,
                "audit_serialized_model_input",
                return_value={
                    "audit": {"retrieval_hit_count": 0, "relief_intent": True},
                    "evidence_packet": packet,
                },
            ), mock.patch.object(
                GEN, "run_production_retrieval", return_value={"results": []}
            ):
                GEN.run_generation(
                    case_root=case_root,
                    question_id="Q2",
                    required_commit="c" * 40,
                    candidate_output_root=out_root,
                    authorization_acknowledgement=GEN.AUTHORIZATION_ACK,
                    generation_only=True,
                    inventory_path=inventory,
                    skip_commit_check=True,
                    acceptance_contract_config=ident_contract,
                    model_call=lambda _s, _u: {},
                    validated_claims_path=claims_path,
                    validated_claims_sha256=sha,
                )

    def test_hash_mismatch_blocks(self) -> None:
        doc = _claims_doc()
        with self.assertRaises(GEN.GenerationError) as ctx:
            self._run_with_claims(doc, sha="b" * 64)
        self.assertEqual(
            ctx.exception.details.get("reason_code"),
            "validated_claims_hash_mismatch",
        )

    def test_tampered_file_blocks(self) -> None:
        replay = _replay()
        ident_contract = _contract_cfg_from_ident(_identity())
        doc = PRE.build_validated_claims_from_replay(
            replay,
            benchmark_id=ident_contract["benchmark_id"],
            question_id=ident_contract["question_id"],
            acceptance_contract_object_key=ident_contract["object_key"],
            acceptance_contract_content_sha256=ident_contract["content_sha256"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            claims_path = root / "claims.json"
            meta = PRE.write_validated_claims_artifact(doc, claims_path)
            # Tamper after hashing.
            tampered = json.loads(claims_path.read_text(encoding="utf-8"))
            for row in tampered["claims"]:
                if row["category"] == "no_defense_or_indemnity":
                    row["supported"] = False
                    row["page_id"] = None
            claims_path.write_text(
                json.dumps(tampered, sort_keys=True, indent=2), encoding="utf-8"
            )
            case_root = root / "case"
            case_root.mkdir()
            inventory = PRE.seed_minimal_case_root(case_root, replay)
            out_root = root / "out"
            out_root.mkdir()
            reasoner = {
                "status": de.STATUS_READY,
                "proposed_answer": PRE.fixed_template_answer_from_replay(replay),
                "propositions": [],
                "supporting_evidence": [],
                "contrary_evidence": [],
                "unresolved_questions": [],
                "documents_pages_reviewed": [],
                "attorney_review": {"requires_attorney_review": True},
                "audit": {"model": "synth", "provider": "synth"},
                "confidence": 0.5,
            }
            packet = {"question": "relief?", "retrieval_hit_count": 0, "retrieval_hits": []}
            with mock.patch.object(
                de, "answer_attorney_record_question", return_value=reasoner
            ), mock.patch.object(
                de, "build_evidence_packet", return_value=packet
            ), mock.patch.object(
                GEN,
                "audit_serialized_model_input",
                return_value={
                    "audit": {"retrieval_hit_count": 0, "relief_intent": True},
                    "evidence_packet": packet,
                },
            ), mock.patch.object(
                GEN, "run_production_retrieval", return_value={"results": []}
            ):
                with self.assertRaises(GEN.GenerationError) as ctx:
                    GEN.run_generation(
                        case_root=case_root,
                        question_id="Q2",
                        required_commit="c" * 40,
                        candidate_output_root=out_root,
                        authorization_acknowledgement=GEN.AUTHORIZATION_ACK,
                        generation_only=True,
                        inventory_path=inventory,
                        skip_commit_check=True,
                        acceptance_contract_config=ident_contract,
                        model_call=lambda _s, _u: {},
                        validated_claims_path=claims_path,
                        validated_claims_sha256=meta["validated_claims_sha256"],
                    )
            # Fail closed before publication (unsupported or hash).
            self.assertIn(
                ctx.exception.details.get("reason_code"),
                {
                    "validated_claims_unsupported_required",
                    "validated_claims_citation_missing",
                    "validated_claims_hash_mismatch",
                },
            )

    def test_benchmark_mismatch_blocks(self) -> None:
        with self.assertRaises(GEN.GenerationError) as ctx:
            GEN.load_and_verify_validated_claims(
                Path("/nonexistent"),
                expected_sha256="a" * 64,
                benchmark_id="Case-00-Triborough",
                question_id="Q2",
                acceptance_contract_object_key="k",
                acceptance_contract_content_sha256="a" * 64,
            )
        self.assertEqual(
            ctx.exception.details.get("reason_code"),
            "validated_claims_path_missing",
        )

    def test_identity_mismatch_blocks(self) -> None:
        replay = _replay()
        doc = _claims_doc(replay)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "claims.json"
            meta = PRE.write_validated_claims_artifact(doc, path)
            with self.assertRaises(GEN.GenerationError) as ctx:
                GEN.load_and_verify_validated_claims(
                    path,
                    expected_sha256=meta["validated_claims_sha256"],
                    benchmark_id="Other-Benchmark",
                    question_id="Q2",
                    acceptance_contract_object_key=doc[
                        "acceptance_contract_object_key"
                    ],
                    acceptance_contract_content_sha256=doc[
                        "acceptance_contract_content_sha256"
                    ],
                )
            self.assertEqual(
                ctx.exception.details.get("reason_code"),
                "validated_claims_benchmark_mismatch",
            )


# ---------------------------------------------------------------------------
# 5. JSON/Markdown parity + all four Q2 criteria
# ---------------------------------------------------------------------------


class ParityAndFourCriteriaTests(unittest.TestCase):
    def test_preflight_emits_claims_and_passes_four_criteria(self) -> None:
        replay = _replay()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            replay_path = root / "replay.json"
            replay_path.write_text(
                json.dumps(replay, sort_keys=True), encoding="utf-8"
            )
            claims_out = root / "validated_claims.json"
            contract_cfg = PRE.build_template_acceptance_contract_config(replay)
            payload = PRE.run_preflight(
                replay_path=replay_path,
                validated_claims_out=claims_out,
                handoff_benchmark_id=contract_cfg["benchmark_id"],
                handoff_question_id="Q2",
                handoff_acceptance_contract_object_key=contract_cfg["object_key"],
                handoff_acceptance_contract_content_sha256=contract_cfg[
                    "content_sha256"
                ],
            )
            self.assertTrue(payload["ok"], payload)
            self.assertTrue(payload.get("parity_ok"))
            self.assertEqual(
                payload.get("criterion_ids_passed"),
                [
                    "q2-rescission-void-ab-initio",
                    "q2-no-defense-or-indemnity",
                    "q2-pleaded-relief-not-adjudication",
                    "q2-catch-all-relief",
                ],
            )
            self.assertTrue(claims_out.is_file())
            loaded = json.loads(claims_out.read_text(encoding="utf-8"))
            rebuilt = GEN.build_validated_structured_claims(
                benchmark_id=loaded["benchmark_id"],
                question_id=loaded["question_id"],
                acceptance_contract_object_key=loaded[
                    "acceptance_contract_object_key"
                ],
                acceptance_contract_content_sha256=loaded[
                    "acceptance_contract_content_sha256"
                ],
                claims=loaded["claims"],
                schema_version=loaded["schema_version"],
            )
            self.assertEqual(
                payload.get("validated_claims_sha256"),
                GEN.validated_claims_sha256(rebuilt),
            )


# ---------------------------------------------------------------------------
# 5b. Regression: run 31638756328 — exact validated supported_needs_paraphrase
# claim for q2-no-defense-or-indemnity must survive generation via safe
# paraphrase (production evidence phrasing) without quoting unreadable OCR.
# ---------------------------------------------------------------------------

_Q2_31638756328_PAGE_ID = "nyscef-001-page-0025"
_Q2_31638756328_OCR_RESCISSION = (
    "25\n\n"
    "183. Upon information and belief, Tri borough has been licensed.\n"
    "184. On the basis of the material misrepresentations and non-disclos ures "
    "Underwriters are entitled to void the Policies ab initio and for "
    "rescission of the same.\n"
    "185. Underwriters have no adequate remedy at law."
)
_Q2_31638756328_CLEAN_CATCH = (
    "for such other and further relief as the Court deems just and proper"
)
_Q2_31638756328_BANNED_OCR = (
    "Tri borough",
    "non-disclos ures",
    "COUNT II",
    "indemni fy",
    "Def en dants",
)


class RetainValidatedNeedsParaphraseNoDefenseTests(unittest.TestCase):
    """Exact q2_validated_structured_claims.v1 object → safe paraphrase."""

    def _production_shaped_contract_cfg(self) -> dict:
        """Live-shaped evidence phrases (duty clause) + presence stock phrasing."""
        import acceptance_contract as ac

        ident = _identity()
        contract = ac.build_synthetic_contract(
            contract_id="contract-31638756328-paraphrase",
            version="1.0.0",
            benchmark_id=ident["benchmark_id"],
            question_id="Q2",
            object_key=ident["object_key"],
            required_criterion_ids=[
                "q2-rescission-void-ab-initio",
                "q2-no-defense-or-indemnity",
                "q2-pleaded-relief-not-adjudication",
                "q2-catch-all-relief",
            ],
            criteria=[
                {
                    "id": "q2-rescission-void-ab-initio",
                    "presence_phrases": ["void ab initio"],
                    "evidence_phrases": ["void ab initio"],
                    "semantic_required_phrases": [],
                    "semantic_forbidden_phrases": [],
                    "fallback_text": "",
                    "category": "relief",
                },
                {
                    "id": "q2-no-defense-or-indemnity",
                    "presence_phrases": ["no defense or indemnity"],
                    "evidence_phrases": [
                        "no duty to defend or indemnify Defendants"
                    ],
                    "semantic_required_phrases": [],
                    "semantic_forbidden_phrases": [],
                    "fallback_text": (
                        "Fallback no defense or indemnity framing with "
                        "no duty to defend or indemnify Defendants."
                    ),
                    "category": "relief",
                },
                {
                    "id": "q2-pleaded-relief-not-adjudication",
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
                    "id": "q2-catch-all-relief",
                    "presence_phrases": ["catch-all requested relief"],
                    "evidence_phrases": [_Q2_31638756328_CLEAN_CATCH],
                    "semantic_required_phrases": [],
                    "semantic_forbidden_phrases": [],
                    "fallback_text": "",
                    "category": "relief",
                },
            ],
        )
        raw = json.dumps(contract, sort_keys=True).encode("utf-8")
        return {
            "object_key": contract["object_key"],
            "benchmark_id": ident["benchmark_id"],
            "question_id": "Q2",
            "content_sha256": contract["content_sha256"],
            "raw_bytes": raw,
            "_contract": contract,
        }

    def _quote_gap_answer(self) -> str:
        # Rescission OCR dump + clean catch-all; no-defense absent from quotes
        # (mirrors clean_excerpt_available=false / quote handoff gap).
        return (
            "This answer describes pleaded requested relief in the complaint, "
            "not a judicial determination. The complaint requests a declaration "
            "that coverage is void ab initio based on alleged material "
            "misrepresentations and non-disclosures, as reflected in the cited "
            f'pleading language: "{_Q2_31638756328_OCR_RESCISSION}" '
            f"(page_id {_Q2_31638756328_PAGE_ID}). The complaint also includes "
            "catch-all requested relief, as reflected in the cited pleading "
            f'language: "{_Q2_31638756328_CLEAN_CATCH}" '
            f"(page_id {_Q2_31638756328_PAGE_ID})."
        )

    def _validated_claims_doc(self, contract_cfg: dict) -> dict:
        # Exact privacy-safe object: supported_needs_paraphrase, no snippets.
        return GEN.build_validated_structured_claims(
            benchmark_id=contract_cfg["benchmark_id"],
            question_id="Q2",
            acceptance_contract_object_key=contract_cfg["object_key"],
            acceptance_contract_content_sha256=contract_cfg["content_sha256"],
            claims=[
                {
                    "category": "rescission_void_ab_initio",
                    "supported": True,
                    "page_id": _Q2_31638756328_PAGE_ID,
                    "nyscef_document_number": 1,
                    "pdf_page": 25,
                    "selection_reason_code": "supported_with_clean_excerpt",
                },
                {
                    "category": "no_defense_or_indemnity",
                    "supported": True,
                    "page_id": _Q2_31638756328_PAGE_ID,
                    "nyscef_document_number": 1,
                    "pdf_page": 25,
                    "selection_reason_code": "supported_needs_paraphrase",
                },
                {
                    "category": "catch_all_relief",
                    "supported": True,
                    "page_id": _Q2_31638756328_PAGE_ID,
                    "nyscef_document_number": 1,
                    "pdf_page": 25,
                    "selection_reason_code": "supported_with_clean_excerpt",
                },
            ],
        )

    def test_fixed_paraphrase_carries_presence_and_duty_evidence(self) -> None:
        claim = {
            "category": "no_defense_or_indemnity",
            "supported": True,
            "page_id": _Q2_31638756328_PAGE_ID,
            "nyscef_document_number": 1,
            "pdf_page": 25,
            "evidence_snippet": "",
            "selection_reason_code": "supported_needs_paraphrase",
        }
        para = de.render_fixed_paraphrase_for_supported_needs_paraphrase(claim)
        self.assertIn("no defense or indemnity", para.lower())
        self.assertIn("no duty to defend or indemnify Defendants", para)
        self.assertIn(f"page_id {_Q2_31638756328_PAGE_ID}", para)
        self.assertIn("originating source page", para.lower())
        for banned in _Q2_31638756328_BANNED_OCR:
            self.assertNotIn(banned, para)

    def test_exact_validated_object_retains_no_defense_without_ocr_or_rebuild(
        self,
    ) -> None:
        import acceptance_contract as ac

        contract_cfg = self._production_shaped_contract_cfg()
        doc = self._validated_claims_doc(contract_cfg)
        exact_claims = GEN.verified_relief_claims_from_validated(doc)
        no_def = next(
            c for c in exact_claims if c["category"] == "no_defense_or_indemnity"
        )
        self.assertTrue(no_def["supported"])
        self.assertEqual(
            no_def["selection_reason_code"], "supported_needs_paraphrase"
        )
        self.assertEqual(no_def.get("evidence_snippet"), "")

        gap = self._quote_gap_answer()
        self.assertNotIn("no defense or indemnity", gap.lower())

        loaded = ac.load_acceptance_contract_from_bytes(
            contract_cfg["raw_bytes"],
            object_key=contract_cfg["object_key"],
            expected_identity=ac.ContractIdentity(
                benchmark_id=contract_cfg["benchmark_id"],
                question_id="Q2",
            ),
            expected_content_sha256=contract_cfg["content_sha256"],
        )
        self.assertTrue(loaded.ok and loaded.evaluation is not None)
        view = loaded.evaluation

        # Consume the exact validated rows — do not rebuild from a packet.
        canonical, validation = GEN.finalize_canonical_answer_against_contract(
            gap,
            view,
            verified_relief_claims=exact_claims,
            validated_claims=doc,
        )
        self.assertTrue(validation.ok, validation.diagnostics)
        by_id = {c.criterion_id: c for c in validation.criterion_results}
        no_def_row = by_id["q2-no-defense-or-indemnity"]
        self.assertEqual(no_def_row.presence, ac.PRESENCE_PRESENT)
        self.assertEqual(no_def_row.evidence, ac.EVIDENCE_SUPPORTED)
        self.assertEqual(no_def_row.result_code, ac.CRIT_PASS)
        self.assertIn("no defense or indemnity", canonical.lower())
        self.assertIn(
            "no duty to defend or indemnify Defendants", canonical
        )
        self.assertIn(f"page_id {_Q2_31638756328_PAGE_ID}", canonical)
        for banned in _Q2_31638756328_BANNED_OCR:
            self.assertNotIn(banned, canonical)

        # Full generation path: packet extract would fail closed; handoff wins.
        replay = _replay()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            claims_path = root / "claims.json"
            meta = PRE.write_validated_claims_artifact(doc, claims_path)
            case_root = root / "case"
            case_root.mkdir()
            inventory = PRE.seed_minimal_case_root(case_root, replay)
            out_root = root / "out"
            out_root.mkdir()
            reasoner = {
                "status": de.STATUS_READY,
                "proposed_answer": gap,
                "propositions": [],
                "supporting_evidence": [],
                "contrary_evidence": [],
                "unresolved_questions": [],
                "documents_pages_reviewed": [],
                "attorney_review": {"requires_attorney_review": True},
                "audit": {
                    "model": "synth",
                    "provider": "synth",
                    "verified_relief_claims": PRE._stale_audit_claims(replay),
                },
                "confidence": 0.5,
            }
            empty_packet = {
                "question": "relief?",
                "retrieval_hit_count": 0,
                "retrieval_hits": [],
            }
            unsupported = {
                "rescission_void_ab_initio": {"supported": False},
                "no_defense_or_indemnity": {"supported": False},
                "catch_all_relief": {"supported": False},
            }
            with mock.patch.object(
                de, "answer_attorney_record_question", return_value=reasoner
            ), mock.patch.object(
                de, "build_evidence_packet", return_value=empty_packet
            ), mock.patch.object(
                de,
                "extract_supported_complaint_relief",
                return_value=unsupported,
            ), mock.patch.object(
                GEN,
                "audit_serialized_model_input",
                return_value={
                    "audit": {"retrieval_hit_count": 0, "relief_intent": True},
                    "evidence_packet": empty_packet,
                },
            ), mock.patch.object(
                GEN, "run_production_retrieval", return_value={"results": []}
            ):
                result = GEN.run_generation(
                    case_root=case_root,
                    question_id="Q2",
                    required_commit="c" * 40,
                    candidate_output_root=out_root,
                    authorization_acknowledgement=GEN.AUTHORIZATION_ACK,
                    generation_only=True,
                    inventory_path=inventory,
                    skip_commit_check=True,
                    acceptance_contract_config=contract_cfg,
                    model_call=lambda _s, _u: {},
                    validated_claims_path=claims_path,
                    validated_claims_sha256=meta["validated_claims_sha256"],
                )

            self.assertTrue(result["ok"])
            self.assertTrue(result.get("validated_claims_handoff_applied"))
            # Authoritative audit list is the exact validated object (packet
            # extract returns unsupported and must not win).
            candidate = json.loads(
                Path(result["files"]["Q2_candidate_answer.json"]).read_text(
                    encoding="utf-8"
                )
            )
            proposed = candidate["proposed_answer"]
            audit_claims = (candidate.get("audit") or {}).get(
                "verified_relief_claims"
            ) or []
            self.assertEqual(audit_claims, exact_claims)
            self.assertIn("no defense or indemnity", proposed.lower())
            self.assertIn(
                "no duty to defend or indemnify Defendants", proposed
            )
            for banned in _Q2_31638756328_BANNED_OCR:
                self.assertNotIn(banned, proposed)


# ---------------------------------------------------------------------------
# 5c. Regression: run 31641606686 at bc537d2 — generation retained the safe
# paraphrase (830-char production-shaped answer) but final acceptance still
# reported presence=absent / evidence_unsupported / fallback_skipped_unsupported
# because OCR-derived contract phrases (indemnification, Count II) diverged
# from the shared semantic paraphrase. One evaluator must serve preflight and
# final acceptance using exact q2_validated_structured_claims.v1 authority.
# ---------------------------------------------------------------------------

_Q2_31641606686_PAGE_ID = "nyscef-001-page-0025"
_Q2_31641606686_BANNED_OCR = (
    "Count II",
    "Tri borough",
    "non-disclos ures",
    "indemni fy",
    "Def en dants",
)
# Exact 830-character production-shaped continuous answer (privacy-safe public
# phrasing only). Contains the fixed no-defense paraphrase with no duty /
# defend-or-indemnify / Defendants / page citation, and deliberately omits
# OCR-derived contract tokens (indemnification, Count II).
_Q2_31641606686_ANSWER_830 = (
    "This answer describes pleaded requested relief in the complaint, "
    "not a judicial determination. The complaint requests a declaration "
    "that coverage is void ab initio based on alleged material "
    "misrepresentations and non-disclosures, as reflected in the cited "
    'pleading language: "void the Policies ab initio and for rescission of the same" '
    f"(page_id {_Q2_31641606686_PAGE_ID}). The complaint also still includes "
    "catch-all requested relief, as reflected in the cited pleading "
    'language: "for such other and further relief as the Court deems just and proper" '
    f"(page_id {_Q2_31641606686_PAGE_ID}). "
    "The complaint further seeks relief that there is no defense or "
    "indemnity obligation and declaring that there is no duty to defend "
    "or indemnify Defendants, as reflected in the cited pleading on the "
    f"originating source page (page_id {_Q2_31641606686_PAGE_ID})."
)


class UnifyQ2NoDefenseSemanticValidation31641606686Tests(unittest.TestCase):
    """Shared semantic evaluator closes run 31641606686 acceptance gap."""

    def setUp(self) -> None:
        self.assertEqual(len(_Q2_31641606686_ANSWER_830), 830)

    def _production_ocr_phrase_contract_cfg(self) -> dict:
        """Mirrors live Q2 contract phrase shape that rejects the paraphrase."""
        import acceptance_contract as ac

        ident = _identity()
        contract = ac.build_synthetic_contract(
            contract_id="contract-31641606686-semantic",
            version="1.0.0",
            benchmark_id=ident["benchmark_id"],
            question_id="Q2",
            object_key=ident["object_key"],
            required_criterion_ids=[
                "q2-rescission-void-ab-initio",
                "q2-no-defense-or-indemnity",
                "q2-pleaded-relief-not-adjudication",
                "q2-catch-all-relief",
            ],
            criteria=[
                {
                    "id": "q2-rescission-void-ab-initio",
                    "presence_phrases": ["void ab initio"],
                    "evidence_phrases": ["void ab initio"],
                    "semantic_required_phrases": [],
                    "semantic_forbidden_phrases": [],
                    "fallback_text": "",
                    "category": "relief",
                },
                {
                    "id": "q2-no-defense-or-indemnity",
                    # Production-shaped OCR/heading tokens — not the safe paraphrase.
                    "presence_phrases": ["defense", "indemnification"],
                    "evidence_phrases": ["Count II"],
                    "semantic_required_phrases": ["no obligation"],
                    "semantic_forbidden_phrases": ["court held no coverage"],
                    "fallback_text": (
                        "Fallback no defense or indemnity framing with "
                        "Count II indemnification wording."
                    ),
                    "category": "relief",
                },
                {
                    "id": "q2-pleaded-relief-not-adjudication",
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
                    "id": "q2-catch-all-relief",
                    "presence_phrases": ["catch-all requested relief"],
                    "evidence_phrases": [
                        "for such other and further relief as the Court "
                        "deems just and proper"
                    ],
                    "semantic_required_phrases": [],
                    "semantic_forbidden_phrases": [],
                    "fallback_text": "",
                    "category": "relief",
                },
            ],
        )
        raw = json.dumps(contract, sort_keys=True).encode("utf-8")
        return {
            "object_key": contract["object_key"],
            "benchmark_id": ident["benchmark_id"],
            "question_id": "Q2",
            "content_sha256": contract["content_sha256"],
            "raw_bytes": raw,
            "_contract": contract,
        }

    def _validated_claims_doc(self, contract_cfg: dict) -> dict:
        return GEN.build_validated_structured_claims(
            benchmark_id=contract_cfg["benchmark_id"],
            question_id="Q2",
            acceptance_contract_object_key=contract_cfg["object_key"],
            acceptance_contract_content_sha256=contract_cfg["content_sha256"],
            claims=[
                {
                    "category": "rescission_void_ab_initio",
                    "supported": True,
                    "page_id": _Q2_31641606686_PAGE_ID,
                    "nyscef_document_number": 1,
                    "pdf_page": 25,
                    "selection_reason_code": "supported_with_clean_excerpt",
                },
                {
                    "category": "no_defense_or_indemnity",
                    "supported": True,
                    "page_id": _Q2_31641606686_PAGE_ID,
                    "nyscef_document_number": 1,
                    "pdf_page": 25,
                    "selection_reason_code": "supported_needs_paraphrase",
                },
                {
                    "category": "catch_all_relief",
                    "supported": True,
                    "page_id": _Q2_31641606686_PAGE_ID,
                    "nyscef_document_number": 1,
                    "pdf_page": 25,
                    "selection_reason_code": "supported_with_clean_excerpt",
                },
            ],
        )

    def _load_view(self, contract_cfg: dict):
        import acceptance_contract as ac

        loaded = ac.load_acceptance_contract_from_bytes(
            contract_cfg["raw_bytes"],
            object_key=contract_cfg["object_key"],
            expected_identity=ac.ContractIdentity(
                benchmark_id=contract_cfg["benchmark_id"],
                question_id="Q2",
            ),
            expected_content_sha256=contract_cfg["content_sha256"],
        )
        self.assertTrue(loaded.ok and loaded.evaluation is not None)
        return loaded.evaluation

    def test_phrase_matching_alone_reproduces_31641606686_failure(self) -> None:
        import acceptance_contract as ac

        view = self._load_view(self._production_ocr_phrase_contract_cfg())
        result = ac.validate_final_answer_against_contract(
            _Q2_31641606686_ANSWER_830,
            view,
            apply_fallback=True,
            apply_duplication_repair=False,
            # No validated claims → OCR phrase path (the production defect).
        )
        by_id = {c.criterion_id: c for c in result.criterion_results}
        no_def = by_id["q2-no-defense-or-indemnity"]
        self.assertEqual(no_def.presence, ac.PRESENCE_ABSENT)
        self.assertEqual(no_def.evidence, ac.EVIDENCE_UNSUPPORTED)
        self.assertIn(
            "fallback_skipped_unsupported:q2-no-defense-or-indemnity",
            result.diagnostics,
        )
        self.assertNotEqual(no_def.result_code, ac.CRIT_PASS)

    def test_shared_evaluator_passes_830_char_production_shaped_answer(self) -> None:
        import acceptance_contract as ac
        from acceptance_contract.validate import evaluate_q2_no_defense_or_indemnity

        contract_cfg = self._production_ocr_phrase_contract_cfg()
        doc = self._validated_claims_doc(contract_cfg)
        view = self._load_view(contract_cfg)

        shared = evaluate_q2_no_defense_or_indemnity(
            _Q2_31641606686_ANSWER_830, doc
        )
        self.assertEqual(shared.result_code, ac.CRIT_PASS)
        self.assertEqual(shared.presence, ac.PRESENCE_PRESENT)
        self.assertEqual(shared.evidence, ac.EVIDENCE_SUPPORTED)

        result = ac.validate_final_answer_against_contract(
            _Q2_31641606686_ANSWER_830,
            view,
            apply_fallback=True,
            apply_duplication_repair=False,
            validated_claims=doc,
        )
        self.assertTrue(result.ok, result.diagnostics)
        by_id = {c.criterion_id: c for c in result.criterion_results}
        no_def = by_id["q2-no-defense-or-indemnity"]
        self.assertEqual(no_def.result_code, ac.CRIT_PASS)
        self.assertEqual(no_def.presence, ac.PRESENCE_PRESENT)
        self.assertEqual(no_def.evidence, ac.EVIDENCE_SUPPORTED)
        self.assertNotIn(
            "fallback_skipped_unsupported:q2-no-defense-or-indemnity",
            result.diagnostics,
        )
        for banned in _Q2_31641606686_BANNED_OCR:
            self.assertNotIn(banned, _Q2_31641606686_ANSWER_830)
        self.assertNotIn("indemnification", _Q2_31641606686_ANSWER_830.lower())

        # Preflight consumes the identical shared evaluator.
        preflight_eval = evaluate_q2_no_defense_or_indemnity(
            _Q2_31641606686_ANSWER_830, doc
        )
        self.assertEqual(preflight_eval.as_safe_dict(), shared.as_safe_dict())

    def test_near_miss_answers_fail_shared_evaluator(self) -> None:
        import acceptance_contract as ac
        from acceptance_contract.validate import evaluate_q2_no_defense_or_indemnity

        contract_cfg = self._production_ocr_phrase_contract_cfg()
        doc = self._validated_claims_doc(contract_cfg)
        page = _Q2_31641606686_PAGE_ID
        base_tail = (
            f"as reflected in the cited pleading on the originating source "
            f"page (page_id {page})."
        )
        near_misses = {
            "missing_no_duty": (
                "The complaint further seeks relief that there is defense or "
                "indemnity obligation and declaring a duty to defend or "
                f"indemnify Defendants, {base_tail}"
            ),
            "missing_defend_or_indemnify": (
                "The complaint further seeks relief that there is no duty owed "
                f"to Defendants, {base_tail}"
            ),
            "missing_defendants": (
                "The complaint further seeks relief that there is no defense or "
                "indemnity obligation and declaring that there is no duty to "
                f"defend or indemnify, {base_tail}"
            ),
            "missing_page_citation": (
                "The complaint further seeks relief that there is no defense or "
                "indemnity obligation and declaring that there is no duty to "
                "defend or indemnify Defendants, as reflected in the cited "
                "pleading on the originating source page."
            ),
        }
        for label, answer in near_misses.items():
            with self.subTest(label=label):
                result = evaluate_q2_no_defense_or_indemnity(answer, doc)
                self.assertNotEqual(
                    result.result_code,
                    ac.CRIT_PASS,
                    msg=f"{label} unexpectedly passed: {result.diagnostics}",
                )

        unsupported = GEN.build_validated_structured_claims(
            benchmark_id=contract_cfg["benchmark_id"],
            question_id="Q2",
            acceptance_contract_object_key=contract_cfg["object_key"],
            acceptance_contract_content_sha256=contract_cfg["content_sha256"],
            claims=[
                {
                    "category": "no_defense_or_indemnity",
                    "supported": False,
                    "page_id": page,
                    "nyscef_document_number": 1,
                    "pdf_page": 25,
                    "selection_reason_code": "unsupported",
                }
            ],
        )
        bad = evaluate_q2_no_defense_or_indemnity(
            _Q2_31641606686_ANSWER_830, unsupported
        )
        self.assertNotEqual(bad.result_code, ac.CRIT_PASS)
        self.assertIn("q2_no_defense_claim_unsupported", bad.diagnostics)


# ---------------------------------------------------------------------------
# 6. No secret / private text leakage
# ---------------------------------------------------------------------------


class NoPrivateTextLeakageTests(unittest.TestCase):
    def test_validated_claims_and_provenance_omit_secrets(self) -> None:
        replay = _replay()
        doc = _claims_doc(replay)
        blob = json.dumps(doc)
        self.assertNotIn(_SECRET, blob)
        self.assertNotIn(_SECRET_NAME, blob)
        self.assertNotIn("evidence_snippet", blob)
        self.assertNotIn("page_text", blob)
        self.assertNotIn("proposed_answer", blob)

        prov = GEN.validated_claims_safe_provenance(doc)
        prov_blob = json.dumps(prov)
        self.assertNotIn(_SECRET, prov_blob)
        self.assertIn("validated_claims_sha256", prov)
        self.assertEqual(len(prov["validated_claims_sha256"]), 64)

        with tempfile.TemporaryDirectory() as tmp:
            replay_path = Path(tmp) / "replay.json"
            replay_path.write_text(
                json.dumps(replay, sort_keys=True), encoding="utf-8"
            )
            claims_out = Path(tmp) / "claims.json"
            contract_cfg = PRE.build_template_acceptance_contract_config(replay)
            payload = PRE.run_preflight(
                replay_path=replay_path,
                validated_claims_out=claims_out,
                handoff_benchmark_id=contract_cfg["benchmark_id"],
                handoff_question_id="Q2",
                handoff_acceptance_contract_object_key=contract_cfg["object_key"],
                handoff_acceptance_contract_content_sha256=contract_cfg[
                    "content_sha256"
                ],
            )
            out_blob = json.dumps(payload) + claims_out.read_text(encoding="utf-8")
            self.assertNotIn(_SECRET, out_blob)
            self.assertNotIn(_SECRET_NAME, out_blob)
            self.assertNotIn("alice.example", out_blob.lower())
            self.assertTrue(payload.get("ok"), payload)


# ---------------------------------------------------------------------------
# 7. Q2 cause-of-action completeness: Count I + Count II routing + omission gate
# ---------------------------------------------------------------------------


_Q2_COMPLETENESS_QUESTION = (
    "What declarations, causes of action, and other relief does the complaint "
    "request?"
)


def _count_completeness_documents(*, include_count_i_page: bool = True) -> list:
    pages = []
    if include_count_i_page:
        pages.append(
            {
                "nyscef_document_number": 1,
                "page_number": 24,
                "page_id": "nyscef-001-page-0024",
                "text": (
                    "COUNT I\n"
                    "180. Plaintiff seeks rescission of the Policies and "
                    "declares coverage void ab initio under the Policies.\n"
                ),
                "document_type": "complaint",
                "document_classification": "complaint",
                "source_filename": "synth_complaint.pdf",
            }
        )
    pages.append(
        {
            "nyscef_document_number": 1,
            "page_number": 25,
            "page_id": "nyscef-001-page-0025",
            "text": (
                "25\n\n"
                "183. Upon information and belief the Named Insured continues.\n"
                "184. On the basis of the material misrepresentations the "
                "Insurer is entitled to void the Policies ab initio and for "
                "rescission of the same.\n"
                "COUNT II Have No Obligations to Provide Defense\n"
                "186. Declaring that there is no duty to defend or indemnify "
                "Defendants under the Policies. OCR noise: indemni fy "
                "Def en dants.\n"
                "187. WHEREFORE the Insurer demands judgment for such other "
                "and further relief as the Court deems just and proper."
            ),
            "document_type": "complaint",
            "document_classification": "complaint",
            "source_filename": "synth_complaint.pdf",
        }
    )
    return [
        {
            "filename": "synth_complaint.pdf",
            "nyscef_document_number": 1,
            "type": "complaint",
            "document_type": "complaint",
            "pages": pages,
        }
    ]


def _source_counts_with_substance() -> list:
    """Verified Count I/II rows with source-grounded substance + page_id."""
    return [
        {
            "ordinal": "I",
            "label": "Count I",
            "observed_marker": "COUNT I",
            "title": None,
            "substantive_excerpt": (
                "Plaintiff seeks rescission of the Policies and declares "
                "coverage void ab initio under the Policies."
            ),
            "substance_phrases": ["rescission", "void ab initio", "declaration"],
            "page_id": "nyscef-001-page-0024",
        },
        {
            "ordinal": "II",
            "label": "Count II",
            "observed_marker": "COUNT II",
            "title": "Have No Obligations to Provide Defense",
            "substantive_excerpt": (
                "Declaring that there is no duty to defend or indemnify "
                "Defendants under the Policies."
            ),
            "substance_phrases": [
                "Have No Obligations to Provide Defense",
                "no duty to defend",
                "indemnify",
            ],
            "page_id": "nyscef-001-page-0025",
        },
    ]


class Q2CauseOfActionCompletenessTests(unittest.TestCase):
    """Count I omission fails/repairs; complete Count I+II passes."""

    def test_missing_count_i_packet_routes_preceding_page_or_flags(self) -> None:
        import complaint_structure as cs

        documents = _count_completeness_documents(include_count_i_page=True)
        pages = documents[0]["pages"]
        structure_map = cs.build_complaint_structure_map({"pages": pages})
        relief_ids = cs.collect_complaint_relief_page_ids(structure_map)
        # WHEREFORE page only from structure; Count I arrives via lookback routing.
        self.assertIn("nyscef-001-page-0025", relief_ids)
        self.assertNotIn("nyscef-001-page-0024", relief_ids)
        counts = cs.enumerate_source_identified_pleaded_counts(
            structure_map,
            page_texts=[
                {
                    "page_id": p["page_id"],
                    "page_number": p["page_number"],
                    "text": p["text"],
                }
                for p in pages
            ],
        )
        labels = [c["label"] for c in counts]
        self.assertEqual(labels, ["Count I", "Count II"])
        by_label = {c["label"]: c for c in counts}
        # Verified substance / title preserved (not nullified).
        self.assertTrue(
            by_label["Count I"].get("substantive_excerpt")
            or by_label["Count I"].get("substance_phrases")
        )
        self.assertTrue(
            by_label["Count II"].get("title")
            or by_label["Count II"].get("substantive_excerpt")
        )
        self.assertIn("void ab initio", " ".join(
            by_label["Count I"].get("substance_phrases") or []
        ).lower())

        # Ordinary retrieval only saw page 25 (Count I heading omitted).
        retrieval = {
            "query": _Q2_COMPLETENESS_QUESTION,
            "results": [
                {
                    "result_id": "hit-25",
                    "page_id": "nyscef-001-page-0025",
                    "nyscef_document_number": 1,
                    "pdf_page": 25,
                    "document_type": "complaint",
                    "excerpt": pages[-1]["text"][:120],
                    "page_text": pages[-1]["text"],
                    "classifications": ["legal_position"],
                    "score": 0.9,
                }
            ],
            "complaint_structure_map": structure_map,
        }
        routed = de.route_complaint_relief_evidence(
            retrieval,
            question=_Q2_COMPLETENESS_QUESTION,
            documents=documents,
            complaint_structure_map=structure_map,
        )
        routed_ids = [h.get("page_id") for h in (routed.get("results") or [])]
        self.assertIn("nyscef-001-page-0024", routed_ids)
        self.assertIn("nyscef-001-page-0025", routed_ids)
        routing = routed.get("complaint_relief_routing") or {}
        self.assertIn(
            "Count I",
            routing.get("source_identified_pleaded_count_labels") or [],
        )
        self.assertIn(
            "Count II",
            routing.get("source_identified_pleaded_count_labels") or [],
        )
        self.assertTrue(routing.get("pleaded_count_completeness_ok"))
        # Packet must preserve source-grounded substance (not nullify title/excerpt).
        packet_counts = routed.get("source_identified_pleaded_counts") or []
        packet_by_label = {c.get("label"): c for c in packet_counts}
        self.assertTrue(
            packet_by_label.get("Count I", {}).get("substantive_excerpt")
            or packet_by_label.get("Count I", {}).get("substance_phrases")
        )

    def test_complete_count_i_and_ii_synthesis_and_acceptance(self) -> None:
        import acceptance_contract as ac
        import complaint_structure as cs

        documents = _count_completeness_documents(include_count_i_page=True)
        pages = documents[0]["pages"]
        structure_map = cs.build_complaint_structure_map({"pages": pages})
        retrieval = {
            "query": _Q2_COMPLETENESS_QUESTION,
            "results": [],
            "complaint_structure_map": structure_map,
        }
        packet = de.build_evidence_packet(
            _Q2_COMPLETENESS_QUESTION,
            retrieval,
            complaint_structure_map=structure_map,
            documents=documents,
        )
        self.assertTrue(packet.get("source_identified_pleaded_counts"))
        assembled = de.apply_evidence_grounded_relief_synthesis(
            {
                "proposed_answer": "Draft omitting counts.",
                "propositions": [],
                "unresolved_questions": ["Count I title is unknown"],
                "audit": {},
            },
            packet,
        )
        answer = assembled["proposed_answer"]
        self.assertIn("Count I", answer)
        self.assertIn("Count II", answer)
        self.assertIn("void ab initio", answer.lower())
        self.assertIn("no defense or indemnity", answer.lower())
        self.assertIn("catch-all", answer.lower())
        # Truncated / mashed OCR dumps must not appear as display quotes.
        self.assertNotIn("indemni fy", answer)
        self.assertNotIn("Def en dants", answer)
        unresolved = assembled.get("unresolved_questions") or []
        self.assertFalse(
            any(
                "count i" in str(q).lower() and "unknown" in str(q).lower()
                for q in unresolved
            )
        )
        audit = assembled.get("audit") or {}
        audit_rows = audit.get("source_identified_pleaded_counts") or []
        audit_labels = [r.get("label") for r in audit_rows]
        self.assertEqual(audit_labels, ["Count I", "Count II"])
        # Verified substance must not be nullified in audit handoff.
        for row in audit_rows:
            self.assertTrue(
                row.get("title")
                or row.get("substantive_excerpt")
                or row.get("substance_phrases"),
                row,
            )

        ident = _identity()
        contract = ac.build_synthetic_contract(
            contract_id="contract-q2-completeness",
            version="1.0.2",
            benchmark_id=ident["benchmark_id"],
            question_id="Q2",
            object_key=ident["object_key"],
            required_criterion_ids=[
                "q2-rescission-void-ab-initio",
                "q2-no-defense-or-indemnity",
                "q2-pleaded-relief-not-adjudication",
                "q2-catch-all-relief",
            ],
            criteria=[
                {
                    "id": "q2-rescission-void-ab-initio",
                    "presence_phrases": ["void ab initio"],
                    "evidence_phrases": ["void ab initio"],
                    "semantic_required_phrases": [],
                    "semantic_forbidden_phrases": [],
                    "fallback_text": "",
                    "category": "relief",
                },
                {
                    "id": "q2-no-defense-or-indemnity",
                    "presence_phrases": ["no defense or indemnity"],
                    "evidence_phrases": ["no defense or indemnity"],
                    "semantic_required_phrases": [],
                    "semantic_forbidden_phrases": [],
                    "fallback_text": "",
                    "category": "relief",
                },
                {
                    "id": "q2-pleaded-relief-not-adjudication",
                    "presence_phrases": [
                        "pleaded requested relief",
                        "not a judicial determination",
                    ],
                    "evidence_phrases": [],
                    "semantic_required_phrases": ["pleaded"],
                    "semantic_forbidden_phrases": ["court has ruled"],
                    "fallback_text": (
                        "This answer describes pleaded requested relief in the "
                        "complaint, not a judicial determination."
                    ),
                    "category": "caveat",
                },
                {
                    "id": "q2-catch-all-relief",
                    "presence_phrases": ["catch-all requested relief"],
                    "evidence_phrases": ["such other and further relief"],
                    "semantic_required_phrases": [],
                    "semantic_forbidden_phrases": [],
                    "fallback_text": "",
                    "category": "relief",
                },
            ],
        )
        loaded = ac.load_acceptance_contract_from_bytes(
            json.dumps(contract, sort_keys=True).encode("utf-8"),
            object_key=contract["object_key"],
            expected_identity=ac.ContractIdentity(
                benchmark_id=ident["benchmark_id"], question_id="Q2"
            ),
            expected_content_sha256=contract["content_sha256"],
        )
        self.assertTrue(loaded.ok)
        source_counts = packet.get("source_identified_pleaded_counts") or []
        validated = {
            "schema_version": "q2_validated_structured_claims.v1",
            "benchmark_id": ident["benchmark_id"],
            "question_id": "Q2",
            "acceptance_contract_object_key": ident["object_key"],
            "acceptance_contract_content_sha256": contract["content_sha256"],
            "claims": assembled["audit"]["verified_relief_claims"],
            "source_identified_pleaded_counts": source_counts,
        }
        # Strip evidence snippets for validated shape (privacy-safe).
        for row in validated["claims"]:
            row["evidence_snippet"] = ""
        result = ac.validate_final_answer_against_contract(
            answer,
            loaded.evaluation,
            apply_fallback=True,
            validated_claims=validated,
            source_identified_counts=source_counts,
        )
        self.assertTrue(result.ok, result.as_safe_dict())
        self.assertIn("Count I", result.final_answer)
        self.assertIn("Count II", result.final_answer)
        self.assertIn("void ab initio", result.final_answer.lower())
        self.assertIn("no defense or indemnity", result.final_answer.lower())

    def test_bare_labels_without_count_i_substance_fail(self) -> None:
        """Negative: both labels present but Count I substance omitted fails."""
        import acceptance_contract as ac

        ident = _identity()
        contract = ac.build_synthetic_contract(
            contract_id="contract-q2-bare-labels",
            version="1.0.2",
            benchmark_id=ident["benchmark_id"],
            question_id="Q2",
            object_key=ident["object_key"],
            required_criterion_ids=["q2-pleaded-relief-not-adjudication"],
            criteria=[
                {
                    "id": "q2-pleaded-relief-not-adjudication",
                    "presence_phrases": [
                        "pleaded requested relief",
                        "not a judicial determination",
                    ],
                    "evidence_phrases": [],
                    "semantic_required_phrases": ["pleaded"],
                    "semantic_forbidden_phrases": [],
                    "fallback_text": (
                        "This answer describes pleaded requested relief in the "
                        "complaint, not a judicial determination."
                    ),
                    "category": "caveat",
                }
            ],
        )
        loaded = ac.load_acceptance_contract_from_bytes(
            json.dumps(contract, sort_keys=True).encode("utf-8"),
            object_key=contract["object_key"],
            expected_identity=ac.ContractIdentity(
                benchmark_id=ident["benchmark_id"], question_id="Q2"
            ),
            expected_content_sha256=contract["content_sha256"],
        )
        self.assertTrue(loaded.ok)
        # Both labels present; Count II substance ok; Count I substance omitted.
        answer = (
            "This answer describes pleaded requested relief in the complaint, "
            "not a judicial determination. Count I. Count II seeks no defense "
            "or indemnity and no duty to defend."
        )
        source_counts = _source_counts_with_substance()
        fail_closed = ac.validate_final_answer_against_contract(
            answer,
            loaded.evaluation,
            apply_fallback=False,
            source_identified_counts=source_counts,
        )
        self.assertFalse(fail_closed.ok)
        self.assertTrue(
            any(
                "material_omission_source_count_substance_missing:Count_I" in d
                for d in fail_closed.diagnostics
            ),
            fail_closed.diagnostics,
        )

    def test_omitted_count_i_fails_material_omission_without_repair(self) -> None:
        import acceptance_contract as ac

        ident = _identity()
        contract = ac.build_synthetic_contract(
            contract_id="contract-q2-omission",
            version="1.0.2",
            benchmark_id=ident["benchmark_id"],
            question_id="Q2",
            object_key=ident["object_key"],
            required_criterion_ids=["q2-pleaded-relief-not-adjudication"],
            criteria=[
                {
                    "id": "q2-pleaded-relief-not-adjudication",
                    "presence_phrases": [
                        "pleaded requested relief",
                        "not a judicial determination",
                    ],
                    "evidence_phrases": [],
                    "semantic_required_phrases": ["pleaded"],
                    "semantic_forbidden_phrases": [],
                    "fallback_text": (
                        "This answer describes pleaded requested relief in the "
                        "complaint, not a judicial determination."
                    ),
                    "category": "caveat",
                }
            ],
        )
        loaded = ac.load_acceptance_contract_from_bytes(
            json.dumps(contract, sort_keys=True).encode("utf-8"),
            object_key=contract["object_key"],
            expected_identity=ac.ContractIdentity(
                benchmark_id=ident["benchmark_id"], question_id="Q2"
            ),
            expected_content_sha256=contract["content_sha256"],
        )
        self.assertTrue(loaded.ok)
        # Answer covers categories but omits source-identified Count I.
        answer = (
            "This answer describes pleaded requested relief in the complaint, "
            "not a judicial determination. Count II seeks no defense or indemnity "
            "and no duty to defend."
        )
        source_counts = _source_counts_with_substance()
        fail_closed = ac.validate_final_answer_against_contract(
            answer,
            loaded.evaluation,
            apply_fallback=False,
            source_identified_counts=source_counts,
        )
        self.assertFalse(fail_closed.ok)
        self.assertTrue(
            any(
                "material_omission_source_count_missing:Count_I" in d
                or "material_omission_source_count_substance_missing:Count_I" in d
                for d in fail_closed.diagnostics
            ),
            fail_closed.diagnostics,
        )

        # Bare-label-only rows cannot be repaired (fail closed).
        bare_only = [
            {
                "ordinal": "I",
                "label": "Count I",
                "observed_marker": "COUNT I",
                "title": None,
                "page_id": "nyscef-001-page-0024",
            },
            {
                "ordinal": "II",
                "label": "Count II",
                "observed_marker": "COUNT II",
                "title": None,
                "page_id": "nyscef-001-page-0025",
            },
        ]
        bare_repair = ac.validate_final_answer_against_contract(
            answer,
            loaded.evaluation,
            apply_fallback=True,
            source_identified_counts=bare_only,
        )
        self.assertFalse(bare_repair.ok)

        repaired = ac.validate_final_answer_against_contract(
            answer,
            loaded.evaluation,
            apply_fallback=True,
            source_identified_counts=source_counts,
        )
        self.assertTrue(repaired.ok, repaired.as_safe_dict())
        self.assertIn("Count I", repaired.final_answer)
        self.assertIn("void ab initio", repaired.final_answer.lower())
        self.assertIn("page_id nyscef-001-page-0024", repaired.final_answer)
        self.assertTrue(
            any(
                "material_omission_source_count_repaired:Count_I" in d
                for d in repaired.diagnostics
            ),
            repaired.diagnostics,
        )

    def test_existing_q2_relief_criteria_and_q1_unaffected(self) -> None:
        """Regression: live-shaped Q2 packet without counts still validates."""
        import acceptance_contract as ac
        from acceptance_contract.validate import evaluate_q2_no_defense_or_indemnity

        supported = de.extract_supported_complaint_relief(_live_packet())
        self.assertTrue(supported["rescission_void_ab_initio"]["supported"])
        self.assertTrue(supported["no_defense_or_indemnity"]["supported"])
        self.assertTrue(supported["catch_all_relief"]["supported"])

        # Shared no-defense evaluator still passes without Count labels.
        claims = de.structured_verified_relief_claims_from_supported(supported)
        for row in claims:
            row["evidence_snippet"] = ""
        validated = {
            "schema_version": "q2_validated_structured_claims.v1",
            "benchmark_id": _identity()["benchmark_id"],
            "question_id": "Q2",
            "acceptance_contract_object_key": _identity()["object_key"],
            "acceptance_contract_content_sha256": "a" * 64,
            "claims": claims,
        }
        para = de._build_no_defense_relief_paragraph(
            supported["no_defense_or_indemnity"]
        )
        result = evaluate_q2_no_defense_or_indemnity(para, validated)
        self.assertEqual(result.result_code, ac.CRIT_PASS)

        # Q1 party-role detection must not treat relief routing as party-role.
        self.assertFalse(
            de.detect_party_role_question_intent(_Q2_COMPLETENESS_QUESTION)
        )
        self.assertTrue(de.detect_relief_question_intent(_Q2_COMPLETENESS_QUESTION))
        self.assertEqual(
            _Q2_COMPLETENESS_QUESTION,
            "What declarations, causes of action, and other relief does the "
            "complaint request?",
        )


if __name__ == "__main__":
    unittest.main()
