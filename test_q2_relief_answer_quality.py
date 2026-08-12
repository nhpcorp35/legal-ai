"""Focused Q2 final-prose quality + citation fidelity regressions.

Synthetic fixtures only — no private Case-00 / complaint text.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

import acceptance_contract as ac


def _load_gen_cli():
    path = (
        Path(__file__).resolve().parent
        / "scripts"
        / "generate_attorney_feedback_candidate.py"
    )
    spec = importlib.util.spec_from_file_location(
        "generate_attorney_feedback_candidate_q2_quality", path
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


GEN = _load_gen_cli()

_Q2_CRIT_RESCISSION = "q2-rescission-void-ab-initio"
_Q2_CRIT_NO_DEFENSE = "q2-no-defense-or-indemnity"
_Q2_CRIT_PLEADED = "q2-pleaded-relief-not-adjudication"
_Q2_CRIT_CATCH_ALL = "q2-catch-all-relief"

_Q2_QUESTION = (
    "What relief does the complaint request in the WHEREFORE / "
    "requested-relief section?"
)

_CLEAN_WHEREFORE = (
    "WHEREFORE Plaintiff demands judgment declaring the policy void ab initio "
    "and for rescission of the same; declaring that there is no duty to defend "
    "or indemnify Defendants; and for such other and further relief as the "
    "Court deems just and proper."
)


def _q2_shaped_contract(
    *,
    rescission_evidence: str = "synth wherefore void ab initio excerpt",
    no_defense_evidence: str = "synth no duty to defend or indemnify excerpt",
    catch_all_evidence: str = "synth such other and further relief excerpt",
) -> dict[str, Any]:
    return ac.build_synthetic_contract(
        contract_id="contract-synth-q2-quality",
        version="1.0.0",
        benchmark_id="synth-benchmark-q2-quality",
        question_id="Q2",
        object_key="Contracts/synthetic/q2/Q2.quality.acceptance_contract.json",
        required_criterion_ids=[
            _Q2_CRIT_RESCISSION,
            _Q2_CRIT_NO_DEFENSE,
            _Q2_CRIT_PLEADED,
            _Q2_CRIT_CATCH_ALL,
        ],
        criteria=[
            {
                "id": _Q2_CRIT_RESCISSION,
                "presence_phrases": ["rescission", "void ab initio"],
                "evidence_phrases": [rescission_evidence],
                "semantic_required_phrases": [],
                "semantic_forbidden_phrases": [],
                "fallback_text": (
                    "Fallback rescission and void ab initio framing with "
                    f"{rescission_evidence}."
                ),
                "category": "relief",
            },
            {
                "id": _Q2_CRIT_NO_DEFENSE,
                "presence_phrases": ["no defense or indemnity"],
                "evidence_phrases": [no_defense_evidence],
                "semantic_required_phrases": [],
                "semantic_forbidden_phrases": [],
                "fallback_text": (
                    "Fallback no defense or indemnity framing with "
                    f"{no_defense_evidence}."
                ),
                "category": "relief",
            },
            {
                "id": _Q2_CRIT_PLEADED,
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
                "id": _Q2_CRIT_CATCH_ALL,
                "presence_phrases": ["such other and further relief"],
                "evidence_phrases": [catch_all_evidence],
                "semantic_required_phrases": [],
                "semantic_forbidden_phrases": [],
                "fallback_text": (
                    "Fallback catch-all framing with "
                    f"{catch_all_evidence}."
                ),
                "category": "relief",
            },
        ],
    )


def _q2_view(doc: dict[str, Any] | None = None) -> ac.ContractEvaluationView:
    contract = doc or _q2_shaped_contract()
    raw = json.dumps(contract, sort_keys=True).encode("utf-8")
    loaded = ac.load_acceptance_contract_from_bytes(
        raw,
        object_key=contract["object_key"],
        expected_identity=ac.ContractIdentity(
            benchmark_id="synth-benchmark-q2-quality",
            question_id="Q2",
        ),
        expected_content_sha256=contract["content_sha256"],
    )
    assert loaded.ok and loaded.evaluation is not None
    return loaded.evaluation


def _hit(
    *,
    page_id: str,
    excerpt: str,
    nyscef: int = 900,
    pdf_page: int = 1,
) -> dict[str, Any]:
    return {
        "result_id": f"hit-{page_id}",
        "page_id": page_id,
        "nyscef_document_number": nyscef,
        "pdf_page": pdf_page,
        "document_type": "complaint",
        "excerpt": excerpt,
        "page_text": excerpt,
        "classifications": ["legal_position"],
    }


def _packet(
    hits: list[dict[str, Any]],
    question: str = _Q2_QUESTION,
) -> dict[str, Any]:
    return {
        "question": question,
        "retrieval_hit_count": len(hits),
        "retrieval_hits": hits,
    }


def _assemble(
    packet: dict[str, Any],
    draft: str = "Long prior draft synthesis.",
) -> dict:
    from engines import drafting_engine as de

    return de.apply_evidence_grounded_relief_synthesis(
        {
            "proposed_answer": draft,
            "propositions": [],
            "audit": {},
        },
        packet,
    )


class Q2OcrFragmentationDisplayGateTests(unittest.TestCase):
    def test_gate_rejects_mid_word_ocr_fragments(self) -> None:
        from engines import drafting_engine as de

        clean = "declaring the policy void ab initio and for rescission"
        garbled = (
            "declaring the pol icy void ab initio and for rescission of the "
            "same; judg ment for Def en dants"
        )
        self.assertFalse(de.displayed_quote_fails_readability_gate(clean))
        self.assertTrue(de.displayed_quote_fails_readability_gate(garbled))
        self.assertTrue(
            de.displayed_quote_fails_readability_gate("v o i d ab initio coverage")
        )

    def test_synthesis_paraphrases_ocr_garbled_quotes_keeps_internal_evidence(
        self,
    ) -> None:
        from engines import drafting_engine as de

        # Keep pattern-matchable phrases intact; fragment surrounding tokens.
        garbled = (
            "WHEREFORE Plaintiff demands judg ment declaring the pol icy "
            "void ab initio and for rescission of the same; declaring that "
            "there is no duty to defend or indemnify Def en dants; and for "
            "such other and further relief as the Court deems just and proper."
        )
        page_id = "nyscef-901-page-0002"
        packet = _packet([_hit(page_id=page_id, excerpt=garbled, pdf_page=2)])
        supported = de.extract_supported_complaint_relief(packet)
        self.assertTrue(supported["rescission_void_ab_initio"]["supported"])
        snippet = supported["rescission_void_ab_initio"]["evidence_snippet"]
        self.assertTrue(de.displayed_quote_fails_readability_gate(snippet))

        assembled = _assemble(packet)
        answer = assembled["proposed_answer"]
        self.assertNotIn("pol icy", answer)
        self.assertNotIn("judg ment", answer)
        self.assertNotIn("Def en dants", answer)
        self.assertIn(f"page_id {page_id}", answer)
        self.assertIn("originating source page", answer.lower())
        # Structured internal evidence remains the observed snippet.
        props = {
            p["proposition_id"]: p
            for p in assembled["propositions"]
            if isinstance(p, dict)
        }
        rescission_prop = props["relief-rescission-void-ab-initio"]
        self.assertIn("pol icy", rescission_prop["source_excerpt"])
        self.assertEqual(rescission_prop["page_id"], page_id)


class Q2NoDuplicateSynthesisTests(unittest.TestCase):
    def test_final_prose_replaces_draft_instead_of_appending_tail(self) -> None:
        draft = (
            "LONG SYNTHESIS TAIL MARKER. The complaint requests various relief "
            "items in expansive narrative form repeating pleaded requested relief "
            "themes without grounded excerpts."
        )
        packet = _packet(
            [_hit(page_id="nyscef-902-page-0001", excerpt=_CLEAN_WHEREFORE)]
        )
        assembled = _assemble(packet, draft=draft)
        answer = assembled["proposed_answer"]
        self.assertNotIn("LONG SYNTHESIS TAIL MARKER", answer)
        self.assertEqual(answer.lower().count("pleaded requested relief"), 1)
        self.assertEqual(answer.lower().count("not a judicial determination"), 1)
        self.assertEqual(answer.lower().count("catch-all requested relief"), 1)
        self.assertIn("void ab initio", answer.lower())
        self.assertIn("no defense or indemnity", answer.lower())


class Q2PageFaithfulAttributionTests(unittest.TestCase):
    def test_each_displayed_citation_uses_only_originating_page_id(self) -> None:
        from engines import drafting_engine as de

        page_a = "nyscef-903-page-0001"
        page_b = "nyscef-903-page-0002"
        prior = (
            "Count II further seeks a declaration that Plaintiff owes neither "
            "a duty to defend nor a duty to indemnify the named defendants."
        )
        wherefore = (
            "WHEREFORE Plaintiff demands judgment declaring coverage void ab "
            "initio and for rescission of the same, and awarding such other and "
            "further relief as the Court deems just and proper."
        )
        packet = _packet(
            [
                _hit(page_id=page_a, excerpt=prior, pdf_page=1),
                _hit(page_id=page_b, excerpt=wherefore, pdf_page=2),
            ]
        )
        supported = de.extract_supported_complaint_relief(packet)
        self.assertEqual(supported["no_defense_or_indemnity"]["page_id"], page_a)
        self.assertEqual(supported["rescission_void_ab_initio"]["page_id"], page_b)
        self.assertEqual(supported["catch_all_relief"]["page_id"], page_b)

        assembled = _assemble(packet)
        answer = assembled["proposed_answer"]
        self.assertIn(f"page_id {page_a}", answer)
        self.assertIn(f"page_id {page_b}", answer)
        # No combined multi-page attribution under one cite.
        self.assertNotIn(f"page_id {page_a},{page_b}", answer)
        self.assertNotIn(f"page_id {page_a} and {page_b}", answer)
        self.assertNotIn("pages ", answer.lower())

        props = {
            p["proposition_id"]: p
            for p in assembled["propositions"]
            if isinstance(p, dict)
        }
        self.assertEqual(props["relief-no-defense-or-indemnity"]["page_id"], page_a)
        self.assertEqual(props["relief-rescission-void-ab-initio"]["page_id"], page_b)
        self.assertEqual(props["relief-catch-all"]["page_id"], page_b)
        indemnity_text = props["relief-no-defense-or-indemnity"]["text"]
        self.assertIn(page_a, indemnity_text)
        self.assertNotIn(page_b, indemnity_text)


class Q2NoUnsupportedGlossTests(unittest.TestCase):
    def test_removes_unsupported_rescission_and_or_gloss(self) -> None:
        void_only = (
            "WHEREFORE Plaintiff demands judgment declaring the policy void ab "
            "initio; and for such other and further relief as the Court deems "
            "just and proper."
        )
        packet = _packet([_hit(page_id="nyscef-904-page-0001", excerpt=void_only)])
        assembled = _assemble(packet)
        answer = assembled["proposed_answer"]
        self.assertNotIn("and/or", answer)
        self.assertNotIn("rescission and/or", answer.lower())
        self.assertIn("void ab initio", answer.lower())
        # Void-only source must not invent a rescission presence claim.
        self.assertNotIn("requests rescission", answer.lower())

    def test_both_rescission_and_void_use_conjunction_not_and_or(self) -> None:
        packet = _packet(
            [
                _hit(
                    page_id="nyscef-904-page-0002",
                    excerpt=_CLEAN_WHEREFORE,
                    pdf_page=2,
                )
            ]
        )
        assembled = _assemble(packet)
        answer = assembled["proposed_answer"]
        self.assertNotIn("and/or", answer)
        self.assertIn(
            "rescission and a declaration that coverage is void ab initio",
            answer,
        )


class Q2FourAcceptancePassesTests(unittest.TestCase):
    def test_four_q2_acceptance_criteria_pass(self) -> None:
        from engines import drafting_engine as de

        doc = _q2_shaped_contract(
            rescission_evidence="void ab initio and for rescission of the same",
            no_defense_evidence="no duty to defend or indemnify Defendants",
            catch_all_evidence=(
                "such other and further relief as the Court deems just and proper"
            ),
        )
        view = _q2_view(doc)
        packet = _packet(
            [_hit(page_id="nyscef-905-page-0001", excerpt=_CLEAN_WHEREFORE)]
        )
        assembled = _assemble(
            packet, draft="Draft omitting grounded relief citations."
        )
        result = ac.validate_final_answer_against_contract(
            assembled["proposed_answer"], view, apply_fallback=True
        )
        by_result = {row.criterion_id: row for row in result.criterion_results}
        for crit_id in (
            _Q2_CRIT_RESCISSION,
            _Q2_CRIT_NO_DEFENSE,
            _Q2_CRIT_PLEADED,
            _Q2_CRIT_CATCH_ALL,
        ):
            self.assertEqual(
                by_result[crit_id].result_code,
                ac.CRIT_PASS,
                msg=f"{crit_id} -> {by_result[crit_id].result_code}",
            )
        self.assertTrue(result.ok)
        self.assertTrue(de.detect_relief_question_intent(_Q2_QUESTION))


class Q1RegressionTests(unittest.TestCase):
    def test_party_role_intent_not_treated_as_relief_synthesis(self) -> None:
        from engines import drafting_engine as de

        q1 = "Who are the parties and what roles do they hold in this action?"
        self.assertTrue(de.detect_party_role_question_intent(q1))
        self.assertFalse(de.detect_relief_question_intent(q1))

        packet = _packet(
            [
                _hit(
                    page_id="nyscef-906-page-0001",
                    excerpt=(
                        "Plaintiff Synthetic Carrier LLC is a corporation. "
                        "Defendant Harbor Logistics Inc. is a limited liability "
                        "company."
                    ),
                )
            ],
            question=q1,
        )
        draft = (
            "Plaintiff Synthetic Carrier LLC is the plaintiff. "
            "Defendant Harbor Logistics Inc. is a defendant."
        )
        assembled = de.apply_evidence_grounded_relief_synthesis(
            {"proposed_answer": draft, "propositions": [], "audit": {}},
            packet,
        )
        self.assertEqual(assembled["proposed_answer"], draft)
        self.assertFalse(assembled["audit"].get("relief_synthesis_applied"))


# ---------------------------------------------------------------------------
# Contract v1.0.2-shaped: semantic retention survives presentation rewrite
# ---------------------------------------------------------------------------

_V102_MISREP_WHEREFORE = (
    "WHEREFORE Plaintiff demands judgment declaring the policy void ab initio "
    "because of material misrepresentations and non-disclosures in the "
    "application and for rescission of the same; declaring that there is no "
    "duty to defend or indemnify Defendants; and for such other and further "
    "relief as the Court deems just and proper."
)

_V102_OCR_MISREP_WHEREFORE = (
    "WHEREFORE Plaintiff demands judg ment declaring the pol icy void ab "
    "initio because of mate rial misrep resentations and non-dis closures "
    "in the application and for rescission of the same; declaring that "
    "there is no duty to defend or indemnify Def en dants; and for such "
    "other and further relief as the Court deems just and proper."
)


def _q2_v102_shaped_contract() -> dict[str, Any]:
    """Synthetic v1.0.2-like Q2 contract — semantic_required on rescission."""
    return ac.build_synthetic_contract(
        contract_id="contract-synth-q2-v102-quality",
        version="1.0.2",
        benchmark_id="synth-benchmark-q2-v102",
        question_id="Q2",
        object_key=(
            "Contracts/synthetic/q2/v1.0.2/Q2.quality.acceptance_contract.json"
        ),
        required_criterion_ids=[
            _Q2_CRIT_RESCISSION,
            _Q2_CRIT_NO_DEFENSE,
            _Q2_CRIT_PLEADED,
            _Q2_CRIT_CATCH_ALL,
        ],
        criteria=[
            {
                "id": _Q2_CRIT_RESCISSION,
                "presence_phrases": ["rescission", "void ab initio"],
                "evidence_phrases": [
                    "void ab initio because of material misrepresentations"
                ],
                "semantic_required_phrases": ["alleged material misrepresentations"],
                "semantic_forbidden_phrases": [
                    "court has ruled the policy void",
                    "established entitlement to rescission",
                ],
                "fallback_text": (
                    "Fallback rescission and void ab initio framing with "
                    "void ab initio because of material misrepresentations."
                ),
                "category": "relief",
            },
            {
                "id": _Q2_CRIT_NO_DEFENSE,
                "presence_phrases": ["no defense or indemnity"],
                "evidence_phrases": ["no duty to defend or indemnify Defendants"],
                "semantic_required_phrases": [],
                "semantic_forbidden_phrases": [],
                "fallback_text": (
                    "Fallback no defense or indemnity framing with "
                    "no duty to defend or indemnify Defendants."
                ),
                "category": "relief",
            },
            {
                "id": _Q2_CRIT_PLEADED,
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
                "id": _Q2_CRIT_CATCH_ALL,
                "presence_phrases": ["such other and further relief"],
                "evidence_phrases": [
                    "such other and further relief as the Court deems just "
                    "and proper"
                ],
                "semantic_required_phrases": [],
                "semantic_forbidden_phrases": [],
                "fallback_text": (
                    "Fallback catch-all framing with such other and further "
                    "relief as the Court deems just and proper."
                ),
                "category": "relief",
            },
        ],
    )


def _q2_v102_view() -> ac.ContractEvaluationView:
    contract = _q2_v102_shaped_contract()
    raw = json.dumps(contract, sort_keys=True).encode("utf-8")
    loaded = ac.load_acceptance_contract_from_bytes(
        raw,
        object_key=contract["object_key"],
        expected_identity=ac.ContractIdentity(
            benchmark_id="synth-benchmark-q2-v102",
            question_id="Q2",
        ),
        expected_content_sha256=contract["content_sha256"],
    )
    assert loaded.ok and loaded.evaluation is not None
    return loaded.evaluation


class Q2V102SemanticRetentionAndCanonicalGateTests(unittest.TestCase):
    """Production-shaped v1.0.2 regressions (synthetic criteria only)."""

    def test_concise_prose_retains_alleged_material_misrepresentations(self) -> None:
        from engines import drafting_engine as de

        # OCR-garbled display path forces concise paraphrase (no quote dump).
        packet = _packet(
            [
                _hit(
                    page_id="nyscef-912-page-0001",
                    excerpt=_V102_OCR_MISREP_WHEREFORE,
                )
            ]
        )
        supported = de.extract_supported_complaint_relief(packet)
        self.assertTrue(supported["rescission_void_ab_initio"]["supported"])
        snippet = supported["rescission_void_ab_initio"]["evidence_snippet"]
        self.assertTrue(de.displayed_quote_fails_readability_gate(snippet))

        assembled = _assemble(packet)
        answer = assembled["proposed_answer"]
        answer_l = answer.lower()
        self.assertIn("alleged material misrepresentations", answer_l)
        self.assertIn("non-disclosures", answer_l)
        self.assertIn("void ab initio", answer_l)
        self.assertIn("rescission", answer_l)
        self.assertNotIn("and/or", answer_l)
        # No OCR dump / mid-word fragments in displayed prose.
        self.assertNotIn("misrep resentations", answer_l)
        self.assertNotIn("mate rial", answer_l)
        self.assertNotIn("Def en dants", answer)

    def test_presentation_rewrite_cannot_drop_passing_semantic_criterion(self) -> None:
        view = _q2_v102_view()
        packet = _packet(
            [_hit(page_id="nyscef-913-page-0001", excerpt=_V102_MISREP_WHEREFORE)]
        )
        assembled = _assemble(packet)
        # Honest canonicalize path retains semantic wording.
        canonical, validation = GEN.finalize_canonical_answer_against_contract(
            assembled["proposed_answer"], view
        )
        self.assertTrue(validation.ok, validation.as_safe_dict())
        by_id = {c.criterion_id: c for c in validation.criterion_results}
        for cid in (
            _Q2_CRIT_RESCISSION,
            _Q2_CRIT_NO_DEFENSE,
            _Q2_CRIT_PLEADED,
            _Q2_CRIT_CATCH_ALL,
        ):
            self.assertEqual(by_id[cid].result_code, ac.CRIT_PASS)
        self.assertEqual(by_id[_Q2_CRIT_RESCISSION].semantic, ac.SEMANTIC_PRESERVED)
        self.assertIn("alleged material misrepresentations", canonical.lower())

        # Hostile presentation rewrite drops the required semantic phrase.
        def _drop_semantic(text: str) -> str:
            cleaned = (
                str(text or "")
                .replace("alleged material misrepresentations and non-disclosures", "")
                .replace("alleged material misrepresentations", "")
            )
            return GEN.canonical_proposed_answer(cleaned)

        _dropped, dropped_validation = GEN.finalize_canonical_answer_against_contract(
            assembled["proposed_answer"],
            view,
            canonicalize=_drop_semantic,
        )
        self.assertFalse(dropped_validation.ok)
        drop_by_id = {
            c.criterion_id: c for c in dropped_validation.criterion_results
        }
        self.assertEqual(
            drop_by_id[_Q2_CRIT_RESCISSION].result_code, ac.CRIT_FAIL_SEMANTIC
        )
        self.assertTrue(
            any(
                d.startswith("presentation_rewrite_lost_criterion:")
                for d in dropped_validation.diagnostics
            )
        )
        # Safe diagnostics: no private complaint / criterion prose leakage.
        blob = json.dumps(dropped_validation.as_safe_dict())
        self.assertNotIn(_V102_MISREP_WHEREFORE, blob)
        for spec in view.criteria:
            if spec.fallback_text:
                self.assertNotIn(spec.fallback_text, blob)

    def test_json_markdown_parity_on_validated_canonical_string(self) -> None:
        view = _q2_v102_view()
        packet = _packet(
            [_hit(page_id="nyscef-914-page-0001", excerpt=_V102_MISREP_WHEREFORE)]
        )
        assembled = _assemble(packet)
        canonical, validation = GEN.finalize_canonical_answer_against_contract(
            assembled["proposed_answer"], view
        )
        self.assertTrue(validation.ok)

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "cand"
            files = GEN.write_candidate_artifacts(
                out_dir,
                question_id="Q2",
                question_text=_Q2_QUESTION,
                required_commit="a" * 40,
                reasoner_result={
                    "status": "READY",
                    "proposed_answer": canonical,
                    "propositions": assembled.get("propositions") or [],
                    "supporting_evidence": [],
                    "contrary_evidence": [],
                    "unresolved_questions": [],
                    "documents_pages_reviewed": [],
                    "attorney_review": {"requires_attorney_review": True},
                    "audit": {"model": "synth", "provider": "synth"},
                    "confidence": 0.5,
                },
                model_input_audit={"retrieval_hit_count": 1},
                commit_info={
                    "checkout_commit": "a" * 40,
                    "origin_main_commit": "a" * 40,
                },
                completeness={"ok": True},
            )
            candidate = json.loads(
                Path(files["Q2_candidate_answer.json"]).read_text(encoding="utf-8")
            )
            markdown = Path(files["Q2_candidate_answer.md"]).read_text(
                encoding="utf-8"
            )
            marker = "## Proposed answer\n\n"
            start = markdown.index(marker) + len(marker)
            end = markdown.index("\n## Review limitation", start)
            md_proposed = markdown[start:end].strip("\n")
            self.assertEqual(candidate["proposed_answer"], canonical)
            self.assertEqual(md_proposed, canonical)
            self.assertEqual(
                GEN.normalize_proposed_answer_whitespace(
                    candidate["proposed_answer"]
                ),
                GEN.normalize_proposed_answer_whitespace(md_proposed),
            )

    def test_without_source_misrep_does_not_invent_alleged_basis(self) -> None:
        assembled = _assemble(
            _packet(
                [_hit(page_id="nyscef-915-page-0001", excerpt=_CLEAN_WHEREFORE)]
            )
        )
        answer_l = assembled["proposed_answer"].lower()
        self.assertIn("void ab initio", answer_l)
        self.assertNotIn("alleged material misrepresentations", answer_l)
        self.assertNotIn("and/or", answer_l)

    def test_q1_regression_unchanged_under_v102_helpers(self) -> None:
        from engines import drafting_engine as de

        q1 = "Who are the parties and what roles do they hold in this action?"
        self.assertTrue(de.detect_party_role_question_intent(q1))
        self.assertFalse(de.detect_relief_question_intent(q1))
        draft = "Plaintiff Synth Co. is the plaintiff."
        assembled = de.apply_evidence_grounded_relief_synthesis(
            {"proposed_answer": draft, "propositions": [], "audit": {}},
            _packet(
                [
                    _hit(
                        page_id="nyscef-916-page-0001",
                        excerpt="Plaintiff Synth Co. is a corporation.",
                    )
                ],
                question=q1,
            ),
        )
        self.assertEqual(assembled["proposed_answer"], draft)


# ---------------------------------------------------------------------------
# Regression: q2-candidate-20260812T175821Z OCR-dump pattern (synthetic)
# ---------------------------------------------------------------------------

_Q2_175821Z_OCR_DUMP = (
    "25\n\n"
    "183. Upon information and belief, Tri borough has been licensed with the "
    "DOB under the names of various entities and/or individuals.\n"
    "184. On the basis of the material misrepresentations and non-disclos ures "
    "made by Triborough in their application to obtain the Policies, "
    "Underwriters are entitled to void the Policies ab initio.\n"
    "185. Underwriters have no adequate remedy at law. COUNT II Underwriters "
    "Have No Obligations to Provide Defense or Indemnification to Triborough "
    "or Any Other Entity, As the Policies Were Obtained as a Result of "
    "Triborough's Material Misrepresentations And Are Void Ab Initio 186."
)

_Q2_175821Z_CLEAN_CATCH = (
    "and C. For any other relief that this Court deems just and equitable."
)

_Q2_175821Z_NO_DEFENSE = (
    "Declaring that there is no duty to defend or indemnify Defendants."
)


class Q2Candidate175821ZOcrDumpRegressionTests(unittest.TestCase):
    """Synthetic fixture modeled on verified failed artifact pattern."""

    def test_gate_rejects_175821z_ocr_dump_markers(self) -> None:
        from engines import drafting_engine as de

        self.assertTrue(de.displayed_quote_fails_readability_gate(_Q2_175821Z_OCR_DUMP))
        self.assertTrue(de.displayed_quote_fails_readability_gate("Tri borough"))
        self.assertTrue(de.displayed_quote_fails_readability_gate("non-disclos ures"))
        self.assertTrue(
            de.displayed_quote_fails_readability_gate("25 183. Upon information")
        )
        self.assertFalse(
            de.displayed_quote_fails_readability_gate(_Q2_175821Z_CLEAN_CATCH)
        )

    def test_synthesis_paraphrases_dump_retains_q2_semantics_and_citations(
        self,
    ) -> None:
        page_id = "nyscef-001-page-0025"
        corpus = (
            f"{_Q2_175821Z_OCR_DUMP} {_Q2_175821Z_NO_DEFENSE} "
            f"{_Q2_175821Z_CLEAN_CATCH}"
        )
        assembled = _assemble(
            _packet([_hit(page_id=page_id, excerpt=corpus, pdf_page=25)])
        )
        answer = assembled["proposed_answer"]
        answer_l = answer.lower()

        # No raw OCR dump markers in final prose.
        for banned in (
            "Tri borough",
            "non-disclos ures",
            "COUNT II",
            "186.",
            "183.",
            "184.",
            "\n25",
            '"25',
        ):
            self.assertNotIn(banned, answer)

        # Q2 acceptance semantics retained.
        self.assertIn("alleged material misrepresentations", answer_l)
        self.assertIn("non-disclosures", answer_l)
        self.assertIn("void ab initio", answer_l)
        self.assertIn("no defense or indemnity", answer_l)
        self.assertIn("pleaded requested relief", answer_l)
        self.assertIn("not a judicial determination", answer_l)
        self.assertIn("catch-all requested relief", answer_l)
        self.assertIn("just and equitable", answer_l)
        self.assertNotIn("and/or", answer_l)

        # Exact citation id preserved; prefer clean excerpts over paraphrase
        # when the verified claim is readable after claim capture.
        self.assertIn(f"page_id {page_id}", answer)
        self.assertIn("cited pleading language", answer_l)
        self.assertIn("just and equitable", answer)
        self.assertIn("no duty to defend or indemnify", answer_l)
        self.assertNotIn("originating source page", answer_l)

    def test_serializer_scrubs_175821z_pattern_with_json_md_parity(self) -> None:
        """Final serializer rejects embedded OCR dumps; JSON/MD stay aligned."""
        failed_shaped = (
            "This answer describes pleaded requested relief in the complaint, "
            "not a judicial determination. The complaint requests a declaration "
            "that coverage is void ab initio based on alleged material "
            "misrepresentations and non-disclosures, as reflected in the cited "
            f'pleading language: "{_Q2_175821Z_OCR_DUMP}" '
            "(page_id nyscef-001-page-0025). The complaint further seeks relief "
            "that there is no defense or indemnity obligation, as reflected in "
            "the cited pleading on the originating source page "
            "(page_id nyscef-001-page-0025). The complaint also includes "
            "catch-all requested relief, as reflected in the cited pleading "
            f'language: "{_Q2_175821Z_CLEAN_CATCH}" '
            "(page_id nyscef-001-page-0026)."
        )
        canonical = GEN.canonical_proposed_answer(failed_shaped)
        for banned in (
            "Tri borough",
            "non-disclos ures",
            "COUNT II",
            "186.",
            "183.",
        ):
            self.assertNotIn(banned, canonical)
        self.assertIn("originating source page", canonical.lower())
        self.assertIn("page_id nyscef-001-page-0025", canonical)
        self.assertIn("page_id nyscef-001-page-0026", canonical)
        self.assertIn("alleged material misrepresentations", canonical.lower())
        self.assertIn("non-disclosures", canonical.lower())
        self.assertIn("just and equitable", canonical.lower())
        # Clean catch-all excerpt retained; OCR dump quote removed.
        self.assertIn("just and equitable", canonical)
        self.assertNotIn("Tri borough", canonical)

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "cand-175821z"
            files = GEN.write_candidate_artifacts(
                out_dir,
                question_id="Q2",
                question_text=_Q2_QUESTION,
                required_commit="b" * 40,
                reasoner_result={
                    "status": "READY",
                    "proposed_answer": canonical,
                    "propositions": [],
                    "supporting_evidence": [],
                    "contrary_evidence": [],
                    "unresolved_questions": [],
                    "documents_pages_reviewed": [],
                    "attorney_review": {"requires_attorney_review": True},
                    "audit": {"model": "synth", "provider": "synth"},
                    "confidence": 0.5,
                },
                model_input_audit={"retrieval_hit_count": 1},
                commit_info={
                    "checkout_commit": "b" * 40,
                    "origin_main_commit": "b" * 40,
                },
                completeness={"ok": True},
            )
            candidate = json.loads(
                Path(files["Q2_candidate_answer.json"]).read_text(encoding="utf-8")
            )
            markdown = Path(files["Q2_candidate_answer.md"]).read_text(
                encoding="utf-8"
            )
            marker = "## Proposed answer\n\n"
            start = markdown.index(marker) + len(marker)
            end = markdown.index("\n## Review limitation", start)
            md_proposed = markdown[start:end].strip("\n")
            self.assertEqual(candidate["proposed_answer"], canonical)
            self.assertEqual(md_proposed, canonical)
            self.assertEqual(
                GEN.normalize_proposed_answer_whitespace(
                    candidate["proposed_answer"]
                ),
                GEN.normalize_proposed_answer_whitespace(md_proposed),
            )
            for banned in ("Tri borough", "non-disclos ures", "COUNT II", "186."):
                self.assertNotIn(banned, candidate["proposed_answer"])
                self.assertNotIn(banned, md_proposed)


# ---------------------------------------------------------------------------
# Regression: production run 31626668919 — OCR scrub dropped no-defense
# (criterion_fail_missing + fallback_skipped_unsupported). Synthetic only.
# ---------------------------------------------------------------------------

_Q2_31626668919_OCR_QUOTE = (
    "25\n\n"
    "183. Upon information and belief, Tri borough has been licensed with the "
    "DOB under the names of various entities and/or individuals.\n"
    "184. On the basis of the material misrepresentations and non-disclos ures "
    "made by Triborough in their application to obtain the Policies, "
    "Underwriters are entitled to void the Policies ab initio.\n"
    "185. Underwriters have no adequate remedy at law. COUNT II Underwriters "
    "Have No Obligations to Provide Defense or Indemnification to Triborough "
    "or Any Other Entity, As the Policies Were Obtained as a Result of "
    "Triborough's Material Misrepresentations And Are Void Ab Initio 186. "
    "Declaring that there is no duty to defend or indemnify Defendants."
)

_Q2_31626668919_CLEAN_CATCH = (
    "for such other and further relief as the Court deems just and proper"
)


class Q2Production31626668919OcrHandoffRegressionTests(unittest.TestCase):
    """OCR quote rejection must hand off verified no-defense evidence."""

    def _failed_shaped_answer(self) -> str:
        # Production-shaped: void lead + OCR dump carrying verified no-defense
        # evidence; no separate no-defense stock paragraph yet.
        return (
            "This answer describes pleaded requested relief in the complaint, "
            "not a judicial determination. The complaint requests a declaration "
            "that coverage is void ab initio based on alleged material "
            "misrepresentations and non-disclosures, as reflected in the cited "
            f'pleading language: "{_Q2_31626668919_OCR_QUOTE}" '
            "(page_id nyscef-001-page-0025). The complaint also includes "
            "catch-all requested relief, as reflected in the cited pleading "
            f'language: "{_Q2_31626668919_CLEAN_CATCH}" '
            "(page_id nyscef-001-page-0026)."
        )

    def _contract_view(self) -> ac.ContractEvaluationView:
        contract = _q2_shaped_contract(
            rescission_evidence="void the Policies ab initio",
            no_defense_evidence="no duty to defend or indemnify Defendants",
            catch_all_evidence=_Q2_31626668919_CLEAN_CATCH,
        )
        raw = json.dumps(contract, sort_keys=True).encode("utf-8")
        loaded = ac.load_acceptance_contract_from_bytes(
            raw,
            object_key=contract["object_key"],
            expected_identity=ac.ContractIdentity(
                benchmark_id="synth-benchmark-q2-quality",
                question_id="Q2",
            ),
            expected_content_sha256=contract["content_sha256"],
        )
        assert loaded.ok and loaded.evaluation is not None
        return loaded.evaluation

    def test_scrub_handoff_retains_no_defense_clean_excerpt_and_citation(
        self,
    ) -> None:
        from engines import drafting_engine as de

        self.assertTrue(
            de.displayed_quote_fails_readability_gate(_Q2_31626668919_OCR_QUOTE)
        )
        verified = de.extract_verified_relief_support_from_text(
            _Q2_31626668919_OCR_QUOTE,
            page_id="nyscef-001-page-0025",
        )
        self.assertTrue(verified["no_defense_or_indemnity"]["supported"])
        self.assertTrue(verified["rescission_void_ab_initio"]["supported"])

        scrubbed = GEN.scrub_unreadable_quoted_excerpts(self._failed_shaped_answer())
        scrubbed_l = scrubbed.lower()
        for banned in ("Tri borough", "non-disclos ures", "COUNT II"):
            self.assertNotIn(banned, scrubbed)
        self.assertIn("no defense or indemnity", scrubbed_l)
        self.assertIn(
            "no duty to defend or indemnify Defendants",
            scrubbed,
        )
        self.assertIn("page_id nyscef-001-page-0025", scrubbed)
        self.assertIn("void ab initio", scrubbed_l)

    def test_post_scrub_contract_avoids_missing_and_fallback_skipped_unsupported(
        self,
    ) -> None:
        view = self._contract_view()
        canonical = GEN.canonical_proposed_answer(self._failed_shaped_answer())
        result = ac.validate_final_answer_against_contract(
            canonical,
            view,
            apply_fallback=True,
            apply_duplication_repair=True,
        )
        by_id = {c.criterion_id: c for c in result.criterion_results}
        no_def = by_id[_Q2_CRIT_NO_DEFENSE]
        self.assertEqual(no_def.result_code, ac.CRIT_PASS)
        self.assertNotEqual(no_def.result_code, ac.CRIT_FAIL_MISSING)
        self.assertNotIn(
            f"fallback_skipped_unsupported:{_Q2_CRIT_NO_DEFENSE}",
            result.diagnostics,
        )
        self.assertNotEqual(
            (result.fallback_actions or {}).get(_Q2_CRIT_NO_DEFENSE),
            ac.FALLBACK_SKIPPED_UNSUPPORTED,
        )
        self.assertIn("no defense or indemnity", result.final_answer.lower())
        self.assertIn(
            "no duty to defend or indemnify Defendants",
            result.final_answer,
        )
        for banned in ("Tri borough", "non-disclos ures", "COUNT II"):
            self.assertNotIn(banned, result.final_answer)

    def test_handoff_fail_closed_without_verified_no_defense_evidence(self) -> None:
        from engines import drafting_engine as de

        ocr_no_indemnity = (
            "25\n\n183. Tri borough licensed.\n"
            "184. On the basis of material misrep resentations Underwriters "
            "are entitled to void the Policies ab initio."
        )
        shaped = (
            "This answer describes pleaded requested relief in the complaint, "
            "not a judicial determination. The complaint requests a declaration "
            "that coverage is void ab initio based on alleged material "
            "misrepresentations and non-disclosures, as reflected in the cited "
            f'pleading language: "{ocr_no_indemnity}" '
            "(page_id nyscef-001-page-0099)."
        )
        verified = de.extract_verified_relief_support_from_text(ocr_no_indemnity)
        self.assertFalse(verified["no_defense_or_indemnity"]["supported"])
        scrubbed = GEN.scrub_unreadable_quoted_excerpts(shaped)
        self.assertNotIn("no defense or indemnity", scrubbed.lower())
        self.assertNotIn("Tri borough", scrubbed)
        self.assertIn("page_id nyscef-001-page-0099", scrubbed)


# ---------------------------------------------------------------------------
# Regression: production run 31627595953 at d70994d — prior quote-string
# scrub fixture did not mirror restored-cache evidence object shape
# (truncated excerpt + full page_text). Glued OCR ``186.`` truncated the
# verified no-defense clause before display scrub, so synthesis paraphrased
# without evidence_phrases → criterion failure / fallback_skipped_unsupported.
# ---------------------------------------------------------------------------

_Q2_31627595953_PAGE_ID = "nyscef-001-page-0025"

# Privacy-safe multi-paragraph OCR dump: same nesting/categories/page identity
# shape as production restored-cache records (not private Case-00 prose).
_Q2_31627595953_PAGE_TEXT = (
    "25\n\n"
    "183. Upon information and belief, Tri borough has been licensed with the "
    "DOB under the names of various entities and/or individuals.\n"
    "184. On the basis of the material misrepresentations and non-disclos ures "
    "made by Triborough in their application to obtain the Policies, "
    "Underwriters are entitled to void the Policies ab initio and for "
    "rescission of the same.\n"
    "185. Underwriters have no adequate remedy at law. COUNT II Underwriters "
    "Have No Obligations to Provide Defense or Indemnification to Triborough "
    "or Any Other Entity, As the Policies Were Obtained as a Result of "
    "Triborough's Material Misrepresentations And Are Void Ab Initio 186. "
    "Declaring that there is no duty to defend or indemnify Defendants.\n"
    "187. WHEREFORE Underwriters demand judgment for such other and further "
    "relief as the Court deems just and proper."
)

# Production retrieval often ships a truncated excerpt that omits no-defense /
# catch-all; restored page_text carries the full folio.
_Q2_31627595953_EXCERPT = (
    "183. Upon information and belief, Tri borough has been licensed.\n"
    "184. On the basis of the material misrepresentations and non-disclos ures "
    "Underwriters are entitled to void the Policies ab initio and for "
    "rescission of the same."
)

_Q2_31627595953_NO_DEFENSE_EVIDENCE = (
    "no duty to defend or indemnify Defendants"
)
_Q2_31627595953_RESCISSION_EVIDENCE = "void the Policies ab initio"
_Q2_31627595953_CATCH_ALL_EVIDENCE = (
    "for such other and further relief as the Court deems just and proper"
)


class Q2Production31627595953CacheShapeHandoffTests(unittest.TestCase):
    """Production restored-cache evidence object → synthesis → canonical."""

    def _packet(self) -> dict[str, Any]:
        return {
            "question": _Q2_QUESTION,
            "retrieval_hit_count": 1,
            "retrieval_hits": [
                {
                    "result_id": "hit-synth-31627595953",
                    "page_id": _Q2_31627595953_PAGE_ID,
                    "nyscef_document_number": 1,
                    "pdf_page": 25,
                    "document_type": "complaint",
                    "excerpt": _Q2_31627595953_EXCERPT,
                    "page_text": _Q2_31627595953_PAGE_TEXT,
                    "classifications": ["legal_position"],
                    "score": 0.91,
                }
            ],
        }

    def _contract_view(self) -> ac.ContractEvaluationView:
        contract = _q2_shaped_contract(
            rescission_evidence=_Q2_31627595953_RESCISSION_EVIDENCE,
            no_defense_evidence=_Q2_31627595953_NO_DEFENSE_EVIDENCE,
            catch_all_evidence=_Q2_31627595953_CATCH_ALL_EVIDENCE,
        )
        raw = json.dumps(contract, sort_keys=True).encode("utf-8")
        loaded = ac.load_acceptance_contract_from_bytes(
            raw,
            object_key=contract["object_key"],
            expected_identity=ac.ContractIdentity(
                benchmark_id="synth-benchmark-q2-quality",
                question_id="Q2",
            ),
            expected_content_sha256=contract["content_sha256"],
        )
        assert loaded.ok and loaded.evaluation is not None
        return loaded.evaluation

    def test_production_cache_shape_captures_claims_before_display_scrub(
        self,
    ) -> None:
        from engines import drafting_engine as de

        packet = self._packet()
        hit = packet["retrieval_hits"][0]
        # Mirror production restored-cache keys/nesting.
        for key in (
            "page_id",
            "excerpt",
            "page_text",
            "nyscef_document_number",
            "pdf_page",
            "document_type",
        ):
            self.assertIn(key, hit)
        self.assertNotEqual(hit["excerpt"], hit["page_text"])
        self.assertIn("non-disclos ures", hit["page_text"])
        self.assertIn("COUNT II", hit["page_text"])
        self.assertIn(
            _Q2_31627595953_NO_DEFENSE_EVIDENCE, hit["page_text"]
        )

        supported = de.extract_supported_complaint_relief(packet)
        for key in (
            "rescission_void_ab_initio",
            "no_defense_or_indemnity",
            "catch_all_relief",
        ):
            meta = supported[key]
            self.assertTrue(meta["supported"], msg=key)
            self.assertEqual(meta["page_id"], _Q2_31627595953_PAGE_ID)
            self.assertEqual(meta["nyscef_document_number"], 1)
            self.assertEqual(meta["pdf_page"], 25)
            self.assertTrue(meta["evidence_snippet"])

        no_def = supported["no_defense_or_indemnity"]
        # Glued ``186.`` must not truncate the clean declaration clause.
        self.assertIn(
            _Q2_31627595953_NO_DEFENSE_EVIDENCE, no_def["evidence_snippet"]
        )
        self.assertTrue(
            de.displayed_quote_fails_readability_gate(no_def["evidence_snippet"])
        )
        clean = de.prefer_clean_relief_display_excerpt(
            no_def["evidence_snippet"],
            category="no_defense_or_indemnity",
        )
        self.assertIn(_Q2_31627595953_NO_DEFENSE_EVIDENCE, clean)
        self.assertFalse(de.displayed_quote_fails_readability_gate(clean))

    def test_synthesis_canonical_passes_all_four_with_clean_prose_and_parity(
        self,
    ) -> None:
        from engines import drafting_engine as de

        packet = self._packet()
        assembled = de.apply_evidence_grounded_relief_synthesis(
            {
                "proposed_answer": "Long prior draft synthesis.",
                "propositions": [],
                "audit": {},
            },
            packet,
        )
        answer = assembled["proposed_answer"]
        self.assertTrue(assembled["audit"].get("relief_synthesis_applied"))
        cats = set(assembled["audit"].get("relief_supported_categories") or [])
        self.assertEqual(
            cats,
            {
                "rescission_void_ab_initio",
                "no_defense_or_indemnity",
                "catch_all_relief",
            },
        )
        # Citation identity retained; OCR artifacts never displayed.
        self.assertIn(f"page_id {_Q2_31627595953_PAGE_ID}", answer)
        self.assertIn(_Q2_31627595953_NO_DEFENSE_EVIDENCE, answer)
        self.assertIn("no defense or indemnity", answer.lower())
        for banned in ("Tri borough", "non-disclos ures", "COUNT II"):
            self.assertNotIn(banned, answer)

        view = self._contract_view()
        canonical, validation = GEN.finalize_canonical_answer_against_contract(
            answer, view
        )
        self.assertTrue(validation.ok)
        by_id = {c.criterion_id: c for c in validation.criterion_results}
        for crit_id in (
            _Q2_CRIT_RESCISSION,
            _Q2_CRIT_NO_DEFENSE,
            _Q2_CRIT_PLEADED,
            _Q2_CRIT_CATCH_ALL,
        ):
            row = by_id[crit_id]
            self.assertEqual(row.result_code, ac.CRIT_PASS, msg=crit_id)
            self.assertEqual(row.presence, ac.PRESENCE_PRESENT, msg=crit_id)
            self.assertEqual(
                row.evidence, ac.EVIDENCE_SUPPORTED, msg=crit_id
            )
        no_def = by_id[_Q2_CRIT_NO_DEFENSE]
        self.assertNotEqual(no_def.result_code, ac.CRIT_FAIL_MISSING)
        self.assertNotIn(
            f"fallback_skipped_unsupported:{_Q2_CRIT_NO_DEFENSE}",
            validation.diagnostics,
        )
        for banned in ("Tri borough", "non-disclos ures", "COUNT II"):
            self.assertNotIn(banned, canonical)
        # Concise prose: canonical list form, not a raw OCR dump.
        self.assertLess(len(canonical), 1200)
        self.assertNotIn("\n\n\n", canonical)

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "cand"
            files = GEN.write_candidate_artifacts(
                out_dir,
                question_id="Q2",
                question_text=_Q2_QUESTION,
                required_commit="b" * 40,
                reasoner_result={
                    "status": "READY",
                    "proposed_answer": canonical,
                    "propositions": assembled.get("propositions") or [],
                    "supporting_evidence": [],
                    "contrary_evidence": [],
                    "unresolved_questions": [],
                    "documents_pages_reviewed": [],
                    "attorney_review": {"requires_attorney_review": True},
                    "audit": {"model": "synth", "provider": "synth"},
                    "confidence": 0.5,
                },
                model_input_audit={"retrieval_hit_count": 1},
                commit_info={
                    "checkout_commit": "b" * 40,
                    "origin_main_commit": "b" * 40,
                },
                completeness={"ok": True},
            )
            candidate = json.loads(
                Path(files["Q2_candidate_answer.json"]).read_text(
                    encoding="utf-8"
                )
            )
            markdown = Path(files["Q2_candidate_answer.md"]).read_text(
                encoding="utf-8"
            )
            marker = "## Proposed answer\n\n"
            start = markdown.index(marker) + len(marker)
            end = markdown.index("\n## Review limitation", start)
            md_proposed = markdown[start:end].strip("\n")
            self.assertEqual(candidate["proposed_answer"], canonical)
            self.assertEqual(md_proposed, canonical)
            self.assertEqual(
                GEN.normalize_proposed_answer_whitespace(
                    candidate["proposed_answer"]
                ),
                GEN.normalize_proposed_answer_whitespace(md_proposed),
            )

    def test_unsupported_no_defense_remains_fail_closed(self) -> None:
        from engines import drafting_engine as de

        # Same cache shape, but page_text has no verified no-defense language.
        page = (
            "25\n\n"
            "184. Underwriters are entitled to void the Policies ab initio "
            "and for rescission of the same.\n"
            "187. WHEREFORE for such other and further relief as the Court "
            "deems just and proper."
        )
        packet = {
            "question": _Q2_QUESTION,
            "retrieval_hit_count": 1,
            "retrieval_hits": [
                {
                    "result_id": "hit-synth-no-indemnity",
                    "page_id": "nyscef-001-page-0099",
                    "nyscef_document_number": 1,
                    "pdf_page": 99,
                    "document_type": "complaint",
                    "excerpt": page[:80],
                    "page_text": page,
                    "classifications": ["legal_position"],
                }
            ],
        }
        supported = de.extract_supported_complaint_relief(packet)
        self.assertFalse(supported["no_defense_or_indemnity"]["supported"])
        assembled = de.apply_evidence_grounded_relief_synthesis(
            {
                "proposed_answer": "Draft.",
                "propositions": [],
                "audit": {},
            },
            packet,
        )
        answer = assembled["proposed_answer"]
        self.assertNotIn("no defense or indemnity", answer.lower())
        self.assertNotIn(
            _Q2_31627595953_NO_DEFENSE_EVIDENCE, answer
        )

        view = self._contract_view()
        canonical = GEN.canonical_proposed_answer(answer)
        result = ac.validate_final_answer_against_contract(
            canonical,
            view,
            apply_fallback=True,
            apply_duplication_repair=True,
        )
        by_id = {c.criterion_id: c for c in result.criterion_results}
        no_def = by_id[_Q2_CRIT_NO_DEFENSE]
        self.assertIn(
            no_def.result_code,
            {ac.CRIT_FAIL_MISSING, ac.CRIT_FAIL_UNSUPPORTED},
        )
        self.assertNotEqual(no_def.result_code, ac.CRIT_PASS)
        self.assertNotEqual(no_def.evidence, ac.EVIDENCE_SUPPORTED)
        actions = result.fallback_actions or {}
        if _Q2_CRIT_NO_DEFENSE in actions:
            self.assertEqual(
                actions[_Q2_CRIT_NO_DEFENSE],
                ac.FALLBACK_SKIPPED_UNSUPPORTED,
            )


# ---------------------------------------------------------------------------
# Regression: production diagnostic run 31629603939 at 97a08ee — synthesis
# marks no_defense supported=true on page_id nyscef-001-page-0025 with
# clean_excerpt_available=false / selection_reason_code
# supported_needs_paraphrase; displayed quote handoff lacks that category;
# structured verified_relief_claims restore a concise cited pleaded
# no-defense/no-indemnification paraphrase (never raw OCR).
# ---------------------------------------------------------------------------

_Q2_31629603939_PAGE_ID = "nyscef-001-page-0025"

# Privacy-safe folio: rescission + catch-all remain excerptable; no-defense is
# mashed into a COUNT heading / glued para / OCR splits so clean excerpt is
# unavailable and selection_reason_code becomes supported_needs_paraphrase.
_Q2_31629603939_PAGE_TEXT = (
    "25\n\n"
    "184. On the basis of the material misrepresentations Underwriters are "
    "entitled to void the Policies ab initio and for rescission of the same.\n"
    "COUNT II Have No Obligations to Provide Defense or Indemnification "
    "to Tri borough or Any Other Entity Void Ab Initio 186. Declaring that "
    "there is no duty to defend or indemni fy Def en dants under the Policies.\n"
    "187. WHEREFORE Underwriters demand judgment for such other and further "
    "relief as the Court deems just and proper."
)

_Q2_31629603939_EXCERPT = (
    "184. On the basis of the material misrepresentations Underwriters are "
    "entitled to void the Policies ab initio and for rescission of the same."
)

# Displayed quote body mirrors production handoff gap: rescission OCR dump
# without recoverable no-defense language (quote scrub alone cannot restore it).
_Q2_31629603939_OCR_RESCISSION_QUOTE = (
    "25\n\n"
    "183. Upon information and belief, Tri borough has been licensed.\n"
    "184. On the basis of the material misrepresentations and non-disclos ures "
    "Underwriters are entitled to void the Policies ab initio and for "
    "rescission of the same.\n"
    "185. Underwriters have no adequate remedy at law."
)

_Q2_31629603939_CLEAN_CATCH = (
    "for such other and further relief as the Court deems just and proper"
)

_Q2_31629603939_BANNED_OCR = (
    "Tri borough",
    "non-disclos ures",
    "COUNT II",
    "indemni fy",
    "Def en dants",
)


class Q2Production31629603939StructuredClaimHandoffTests(unittest.TestCase):
    """structured verified_relief_claims restore paraphrase when quotes lack it."""

    def _packet(self) -> dict[str, Any]:
        return {
            "question": _Q2_QUESTION,
            "retrieval_hit_count": 1,
            "retrieval_hits": [
                {
                    "result_id": "hit-synth-31629603939",
                    "page_id": _Q2_31629603939_PAGE_ID,
                    "nyscef_document_number": 1,
                    "pdf_page": 25,
                    "document_type": "complaint",
                    "excerpt": _Q2_31629603939_EXCERPT,
                    "page_text": _Q2_31629603939_PAGE_TEXT,
                    "classifications": ["legal_position"],
                    "score": 0.91,
                }
            ],
        }

    def _quote_gap_answer(self) -> str:
        return (
            "This answer describes pleaded requested relief in the complaint, "
            "not a judicial determination. The complaint requests a declaration "
            "that coverage is void ab initio based on alleged material "
            "misrepresentations and non-disclosures, as reflected in the cited "
            f'pleading language: "{_Q2_31629603939_OCR_RESCISSION_QUOTE}" '
            f"(page_id {_Q2_31629603939_PAGE_ID}). The complaint also includes "
            "catch-all requested relief, as reflected in the cited pleading "
            f'language: "{_Q2_31629603939_CLEAN_CATCH}" '
            f"(page_id {_Q2_31629603939_PAGE_ID})."
        )

    def _contract_view(self) -> ac.ContractEvaluationView:
        # Evidence for no-defense is the pleaded paraphrase language retained
        # when clean_excerpt_available=false (never the OCR duty clause).
        contract = _q2_shaped_contract(
            rescission_evidence="void the Policies ab initio",
            no_defense_evidence="no defense or indemnity",
            catch_all_evidence=_Q2_31629603939_CLEAN_CATCH,
        )
        raw = json.dumps(contract, sort_keys=True).encode("utf-8")
        loaded = ac.load_acceptance_contract_from_bytes(
            raw,
            object_key=contract["object_key"],
            expected_identity=ac.ContractIdentity(
                benchmark_id="synth-benchmark-q2-quality",
                question_id="Q2",
            ),
            expected_content_sha256=contract["content_sha256"],
        )
        assert loaded.ok and loaded.evaluation is not None
        return loaded.evaluation

    def test_synthesis_marks_no_defense_supported_needs_paraphrase(self) -> None:
        from engines import drafting_engine as de
        from engines import q2_production_evidence_diagnostics as q2diag

        packet = self._packet()
        supported = de.extract_supported_complaint_relief(packet)
        no_def = supported["no_defense_or_indemnity"]
        self.assertTrue(no_def["supported"])
        self.assertEqual(no_def["page_id"], _Q2_31629603939_PAGE_ID)
        self.assertTrue(de.readability_gate_reason_codes(no_def["evidence_snippet"]))
        clean = de.prefer_clean_relief_display_excerpt(
            no_def["evidence_snippet"],
            category="no_defense_or_indemnity",
        )
        self.assertEqual(clean, "")
        self.assertEqual(
            de.relief_selection_reason_code("no_defense_or_indemnity", no_def),
            "supported_needs_paraphrase",
        )

        assembled = de.apply_evidence_grounded_relief_synthesis(
            {"proposed_answer": "Draft.", "propositions": [], "audit": {}},
            packet,
        )
        claims = assembled["audit"].get("verified_relief_claims") or []
        by_cat = {c["category"]: c for c in claims}
        claim = by_cat["no_defense_or_indemnity"]
        self.assertTrue(claim["supported"])
        self.assertEqual(claim["page_id"], _Q2_31629603939_PAGE_ID)
        self.assertEqual(
            claim["selection_reason_code"], "supported_needs_paraphrase"
        )

        relief = q2diag.diagnose_relief_synthesis(packet, assembled)
        diag_no_def = relief["categories"]["no_defense_or_indemnity"]
        self.assertTrue(diag_no_def["supported"])
        self.assertEqual(diag_no_def["page_id"], _Q2_31629603939_PAGE_ID)
        self.assertFalse(diag_no_def["clean_excerpt_available"])
        self.assertEqual(
            diag_no_def["selection_reason_code"], "supported_needs_paraphrase"
        )

    def test_quote_handoff_lacks_no_defense_until_structured_claims_merge(
        self,
    ) -> None:
        from engines import drafting_engine as de

        gap = self._quote_gap_answer()
        quote_verified = de.extract_verified_relief_support_from_text(
            _Q2_31629603939_OCR_RESCISSION_QUOTE,
            page_id=_Q2_31629603939_PAGE_ID,
        )
        self.assertFalse(quote_verified["no_defense_or_indemnity"]["supported"])
        self.assertTrue(quote_verified["rescission_void_ab_initio"]["supported"])

        scrubbed_gap = GEN.scrub_unreadable_quoted_excerpts(gap)
        self.assertNotIn("no defense or indemnity", scrubbed_gap.lower())
        for banned in _Q2_31629603939_BANNED_OCR:
            self.assertNotIn(banned, scrubbed_gap)

        packet = self._packet()
        assembled = de.apply_evidence_grounded_relief_synthesis(
            {"proposed_answer": "Draft.", "propositions": [], "audit": {}},
            packet,
        )
        claims = assembled["audit"]["verified_relief_claims"]
        restored = GEN.scrub_unreadable_quoted_excerpts(
            gap, verified_relief_claims=claims
        )
        self.assertIn("no defense or indemnity", restored.lower())
        self.assertIn(f"page_id {_Q2_31629603939_PAGE_ID}", restored)
        self.assertIn("originating source page", restored.lower())
        for banned in _Q2_31629603939_BANNED_OCR:
            self.assertNotIn(banned, restored)
        # Concise paraphrase — not a long OCR dump.
        self.assertLess(len(restored), 1600)
        self.assertNotIn(_Q2_31629603939_PAGE_TEXT, restored)

    def test_four_criteria_pass_with_parity_and_fail_closed_unsupported(
        self,
    ) -> None:
        from engines import drafting_engine as de

        packet = self._packet()
        assembled = de.apply_evidence_grounded_relief_synthesis(
            {"proposed_answer": "Draft.", "propositions": [], "audit": {}},
            packet,
        )
        claims = assembled["audit"]["verified_relief_claims"]
        # Start from the quote-gap answer so restoration depends on structured
        # claims (production handoff path), not synthesis-only prose.
        restored = GEN.scrub_unreadable_quoted_excerpts(
            self._quote_gap_answer(), verified_relief_claims=claims
        )
        view = self._contract_view()
        canonical, validation = GEN.finalize_canonical_answer_against_contract(
            restored,
            view,
            verified_relief_claims=claims,
        )
        self.assertTrue(validation.ok)
        by_id = {c.criterion_id: c for c in validation.criterion_results}
        for crit_id in (
            _Q2_CRIT_RESCISSION,
            _Q2_CRIT_NO_DEFENSE,
            _Q2_CRIT_PLEADED,
            _Q2_CRIT_CATCH_ALL,
        ):
            row = by_id[crit_id]
            self.assertEqual(row.result_code, ac.CRIT_PASS, msg=crit_id)
            self.assertEqual(row.presence, ac.PRESENCE_PRESENT, msg=crit_id)
            self.assertEqual(
                row.evidence, ac.EVIDENCE_SUPPORTED, msg=crit_id
            )
        self.assertIn("no defense or indemnity", canonical.lower())
        self.assertIn(f"page_id {_Q2_31629603939_PAGE_ID}", canonical)
        for banned in _Q2_31629603939_BANNED_OCR:
            self.assertNotIn(banned, canonical)
        self.assertLess(len(canonical), 1600)

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "cand"
            files = GEN.write_candidate_artifacts(
                out_dir,
                question_id="Q2",
                question_text=_Q2_QUESTION,
                required_commit="c" * 40,
                reasoner_result={
                    "status": "READY",
                    "proposed_answer": canonical,
                    "propositions": assembled.get("propositions") or [],
                    "supporting_evidence": [],
                    "contrary_evidence": [],
                    "unresolved_questions": [],
                    "documents_pages_reviewed": [],
                    "attorney_review": {"requires_attorney_review": True},
                    "audit": {
                        "model": "synth",
                        "provider": "synth",
                        "verified_relief_claims": claims,
                    },
                    "confidence": 0.5,
                },
                model_input_audit={"retrieval_hit_count": 1},
                commit_info={
                    "checkout_commit": "c" * 40,
                    "origin_main_commit": "c" * 40,
                },
                completeness={"ok": True},
            )
            candidate = json.loads(
                Path(files["Q2_candidate_answer.json"]).read_text(
                    encoding="utf-8"
                )
            )
            markdown = Path(files["Q2_candidate_answer.md"]).read_text(
                encoding="utf-8"
            )
            marker = "## Proposed answer\n\n"
            start = markdown.index(marker) + len(marker)
            end = markdown.index("\n## Review limitation", start)
            md_proposed = markdown[start:end].strip("\n")
            self.assertEqual(candidate["proposed_answer"], canonical)
            self.assertEqual(md_proposed, canonical)
            self.assertEqual(
                GEN.normalize_proposed_answer_whitespace(
                    candidate["proposed_answer"]
                ),
                GEN.normalize_proposed_answer_whitespace(md_proposed),
            )

        # Unsupported / missing-page structured claims stay fail-closed.
        gap = self._quote_gap_answer()
        unsupported_claim = {
            "category": "no_defense_or_indemnity",
            "supported": False,
            "page_id": _Q2_31629603939_PAGE_ID,
            "nyscef_document_number": 1,
            "pdf_page": 25,
            "evidence_snippet": "",
            "selection_reason_code": "unsupported",
        }
        missing_page_claim = {
            "category": "no_defense_or_indemnity",
            "supported": True,
            "page_id": None,
            "nyscef_document_number": 1,
            "pdf_page": 25,
            "evidence_snippet": "mashed OCR no duty clause",
            "selection_reason_code": "supported_needs_paraphrase",
        }
        for bad_claims in ([unsupported_claim], [missing_page_claim]):
            scrubbed = GEN.scrub_unreadable_quoted_excerpts(
                gap, verified_relief_claims=bad_claims
            )
            self.assertNotIn("no defense or indemnity", scrubbed.lower())
            self.assertEqual(
                de.render_fixed_paraphrase_for_supported_needs_paraphrase(
                    bad_claims[0]
                ),
                "",
            )


if __name__ == "__main__":
    unittest.main()
