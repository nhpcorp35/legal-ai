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


if __name__ == "__main__":
    unittest.main()
