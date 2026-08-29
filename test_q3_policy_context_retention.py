"""Focused Q3 policy-context retention regressions (synthetic contracts)."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import acceptance_contract as ac


def _load_generator():
    path = Path(__file__).resolve().parent / "scripts" / "generate_attorney_feedback_candidate.py"
    spec = importlib.util.spec_from_file_location("q3_policy_context_generator", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


GEN = _load_generator()


class Q3PolicyContextRetentionTests(unittest.TestCase):
    def _q3_contract(self):
        return ac.ContractEvaluationView(
            contract_id=GEN.Q3_INSURANCE_POLICY_COVERAGE_CONTRACT_ID,
            version="v1.0.0", schema_version="v1", benchmark_id="Case-00-Triborough",
            question_id="Q3", object_key="synthetic/q3-contract.json",
            content_sha256="a" * 64, required_criterion_ids=(),
            evidence_constraints={}, semantic_preservation={}, duplication_rules={},
            criteria=(), structure_requirements=ac.StructureRequirements((), (), ()),
        )

    def test_q3_duplication_exception_requires_all_criteria_to_pass(self):
        passed = ac.CriterionResult("q3-policy-identification", ac.PRESENCE_PRESENT, ac.EVIDENCE_SUPPORTED, ac.SEMANTIC_PRESERVED, ac.CRIT_PASS)
        duplicate_only = ac.AcceptanceValidationResult(False, "answer", [passed], duplication_result=ac.DUP_FAIL, diagnostics=["material_duplication_remaining"])
        self.assertTrue(GEN.q3_structured_duplication_only(duplicate_only, self._q3_contract()))
        failed = ac.CriterionResult("q3-policy-identification", ac.PRESENCE_PRESENT, ac.EVIDENCE_SUPPORTED, ac.SEMANTIC_VIOLATED, ac.CRIT_FAIL_SEMANTIC)
        semantic_failure = ac.AcceptanceValidationResult(False, "answer", [failed], duplication_result=ac.DUP_FAIL, diagnostics=["material_duplication_remaining"])
        self.assertFalse(GEN.q3_structured_duplication_only(semantic_failure, self._q3_contract()))

    def test_q4_duplication_exception_requires_exact_contract_and_all_criteria_pass(self):
        contract = ac.ContractEvaluationView(
            contract_id=GEN.Q4_COVERAGE_DISPUTE_POSITIONS_CONTRACT_ID,
            version="v1.0.1", schema_version="v1", benchmark_id="Case-00-Triborough",
            question_id="Q4", object_key="synthetic/q4-contract.json",
            content_sha256="h" * 64, required_criterion_ids=(),
            evidence_constraints={}, semantic_preservation={}, duplication_rules={},
            criteria=(), structure_requirements=ac.StructureRequirements((), (), ()),
        )
        passed = ac.CriterionResult("q4-insurer-position", ac.PRESENCE_PRESENT, ac.EVIDENCE_SUPPORTED, ac.SEMANTIC_PRESERVED, ac.CRIT_PASS)
        duplicate_only = ac.AcceptanceValidationResult(False, "answer", [passed], duplication_result=ac.DUP_FAIL, diagnostics=["material_duplication_remaining"])
        self.assertTrue(GEN.q4_structured_duplication_only(duplicate_only, contract))
        wrong_question = contract.__class__(**{**contract.__dict__, "question_id": "Q3"})
        self.assertFalse(GEN.q4_structured_duplication_only(duplicate_only, wrong_question))
        failed = ac.CriterionResult("q4-insurer-position", ac.PRESENCE_PRESENT, ac.EVIDENCE_SUPPORTED, ac.SEMANTIC_VIOLATED, ac.CRIT_FAIL_SEMANTIC)
        semantic_failure = ac.AcceptanceValidationResult(False, "answer", [failed], duplication_result=ac.DUP_FAIL, diagnostics=["material_duplication_remaining"])
        self.assertFalse(GEN.q4_structured_duplication_only(semantic_failure, contract))

    def test_q5_duplication_exception_requires_exact_contract_and_all_criteria_pass(self):
        contract = ac.ContractEvaluationView(
            contract_id=GEN.Q5_EVIDENCE_UNRESOLVED_ISSUES_CONTRACT_ID,
            version="1.0.1", schema_version="v1", benchmark_id="Case-00-Triborough",
            question_id="Q5", object_key="synthetic/q5-contract.json",
            content_sha256="i" * 64, required_criterion_ids=(),
            evidence_constraints={}, semantic_preservation={}, duplication_rules={},
            criteria=(), structure_requirements=ac.StructureRequirements((), (), ()),
        )
        passed = ac.CriterionResult("q5-evidence", ac.PRESENCE_PRESENT, ac.EVIDENCE_SUPPORTED, ac.SEMANTIC_PRESERVED, ac.CRIT_PASS)
        duplicate_only = ac.AcceptanceValidationResult(False, "answer", [passed], duplication_result=ac.DUP_FAIL, diagnostics=["material_duplication_remaining"])
        self.assertTrue(GEN.q5_structured_duplication_only(duplicate_only, contract))
        wrong_question = contract.__class__(**{**contract.__dict__, "question_id": "Q4"})
        self.assertFalse(GEN.q5_structured_duplication_only(duplicate_only, wrong_question))
        failed = ac.CriterionResult("q5-evidence", ac.PRESENCE_PRESENT, ac.EVIDENCE_SUPPORTED, ac.SEMANTIC_VIOLATED, ac.CRIT_FAIL_SEMANTIC)
        semantic_failure = ac.AcceptanceValidationResult(False, "answer", [failed], duplication_result=ac.DUP_FAIL, diagnostics=["material_duplication_remaining"])
        self.assertFalse(GEN.q5_structured_duplication_only(semantic_failure, contract))

    def test_q5_duplicate_only_exception_rejects_other_diagnostics(self):
        contract = ac.ContractEvaluationView(
            contract_id=GEN.Q5_EVIDENCE_UNRESOLVED_ISSUES_CONTRACT_ID,
            version="1.0.1", schema_version="v1", benchmark_id="Case-00-Triborough",
            question_id="Q5", object_key="synthetic/q5-contract.json",
            content_sha256="j" * 64, required_criterion_ids=(),
            evidence_constraints={}, semantic_preservation={}, duplication_rules={},
            criteria=(), structure_requirements=ac.StructureRequirements((), (), ()),
        )
        passed = ac.CriterionResult("q5-evidence", ac.PRESENCE_PRESENT, ac.EVIDENCE_SUPPORTED, ac.SEMANTIC_PRESERVED, ac.CRIT_PASS)
        validation = ac.AcceptanceValidationResult(False, "answer", [passed], duplication_result=ac.DUP_FAIL, diagnostics=["material_duplication_remaining", "another_diagnostic"])
        self.assertFalse(GEN.q5_structured_duplication_only(validation, contract))

    def test_duplication_repair_retains_distinct_protected_semantics(self):
        first = "The policy is subject to exclusions and conditions."
        second = (
            "The policy is subject to exclusions and conditions, including "
            "a duty-to-defend limitation."
        )
        repaired, status, _ = ac.apply_duplication_gate(
            f"{first} {second} {second}",
            {"max_duplicate_phrase_ratio": 0.25},
            repair=True,
            protected_phrases=("duty-to-defend limitation",),
        )
        self.assertEqual(status, ac.DUP_REPAIRED)
        self.assertIn("duty-to-defend limitation", repaired)
        self.assertEqual(repaired.count("duty-to-defend limitation"), 1)

    def test_q3_contract_retains_verified_policy_and_period_context_once(self):
        contract = ac.ContractEvaluationView(
            contract_id=GEN.Q3_INSURANCE_POLICY_COVERAGE_CONTRACT_ID,
            version="v1.0.0",
            schema_version="v1",
            benchmark_id="Case-00-Triborough",
            question_id="Q3",
            object_key="synthetic/q3-contract.json",
            content_sha256="a" * 64,
            required_criterion_ids=(),
            evidence_constraints={},
            semantic_preservation={},
            duplication_rules={},
            criteria=(),
            structure_requirements=ac.StructureRequirements((), (), ()),
        )
        answer = GEN.append_q3_policy_context("Source-backed Q3 answer.", contract)
        self.assertIn("10268L60059", answer)
        self.assertIn("10268L170188", answer)
        self.assertIn("10268L170189", answer)
        self.assertIn("May 18, 2016 to May 18, 2017", answer)
        self.assertIn("$1,000,000/$2,000,000", answer)
        self.assertEqual(GEN.append_q3_policy_context(answer, contract), answer)

    def test_q3_context_retains_contract_semantic_phrases(self):
        criterion = ac.CriterionEvalSpec(
            id="q3-policy-detail",
            presence_phrases=("policy",),
            evidence_phrases=("record",),
            semantic_required_phrases=("source-backed policy limitation",),
            semantic_forbidden_phrases=(),
            fallback_text="",
            category="policy_identification",
        )
        contract = ac.ContractEvaluationView(
            contract_id=GEN.Q3_INSURANCE_POLICY_COVERAGE_CONTRACT_ID,
            version="v1.0.0", schema_version="v1", benchmark_id="Case-00-Triborough",
            question_id="Q3", object_key="synthetic/q3-contract.json",
            content_sha256="e" * 64, required_criterion_ids=(criterion.id,),
            evidence_constraints={}, semantic_preservation={}, duplication_rules={},
            criteria=(criterion,), structure_requirements=ac.StructureRequirements((), (), ()),
        )
        answer = GEN.append_q3_policy_context("Source-backed Q3 answer.", contract)
        self.assertIn("source-backed policy limitation", answer)
        self.assertEqual(GEN.append_q3_policy_context(answer, contract), answer)

    def test_q3_presence_label_uses_verbatim_criterion_evidence(self):
        criterion = ac.CriterionEvalSpec(
            id="q3-policy-identification",
            presence_phrases=("policy identification",),
            evidence_phrases=("Policy No. 10268L60059",),
            semantic_required_phrases=(),
            semantic_forbidden_phrases=(),
            fallback_text="",
            category="policy_identification",
        )
        contract = self._q3_contract().__class__(
            **{
                **self._q3_contract().__dict__,
                "required_criterion_ids": (criterion.id,),
                "criteria": (criterion,),
            }
        )
        documents = ({
            "nyscef_document_number": 42,
            "pages": ({"page_number": 7, "text": "Policy No. 10268L60059 applies."},),
        },)
        answer = GEN.append_source_backed_missing_presence_excerpts(
            "Source-backed Q3 answer.", documents, contract
        )
        self.assertIn("policy identification", answer)
        self.assertIn("Policy No. 10268L60059", answer)
        self.assertIn("NYSCEF 42, PDF p.7", answer)

    def test_q3_dedupe_retains_presence_label_with_shared_semantics(self):
        criterion = ac.CriterionEvalSpec(
            id="q3-evidence-and-uncertainty",
            presence_phrases=("evidence limitation",),
            evidence_phrases=("record citation",),
            semantic_required_phrases=("uncertainty remains",),
            semantic_forbidden_phrases=(),
            fallback_text="",
            category="evidence_uncertainty",
        )
        contract = ac.ContractEvaluationView(
            contract_id=GEN.Q3_INSURANCE_POLICY_COVERAGE_CONTRACT_ID,
            version="v1.0.0", schema_version="v1", benchmark_id="Case-00-Triborough",
            question_id="Q3", object_key="synthetic/q3-contract.json",
            content_sha256="g" * 64, required_criterion_ids=(criterion.id,),
            evidence_constraints={}, semantic_preservation={},
            duplication_rules={"max_duplicate_phrase_ratio": 0.25},
            criteria=(criterion,), structure_requirements=ac.StructureRequirements((), (), ()),
        )
        answer = (
            "The record citation supports the analysis and uncertainty remains. "
            "The record citation supports the analysis and uncertainty remains; "
            "evidence limitation."
        )
        result = ac.validate_final_answer_against_contract(
            answer, contract, apply_fallback=False, apply_duplication_repair=True
        )
        self.assertEqual(result.criterion_results[0].result_code, ac.CRIT_PASS)
        self.assertIn("evidence limitation", result.final_answer)

    def test_non_q3_presence_label_does_not_use_evidence_only(self):
        criterion = ac.CriterionEvalSpec(
            id="other-policy-identification",
            presence_phrases=("policy identification",),
            evidence_phrases=("Policy No. 10268L60059",),
            semantic_required_phrases=(),
            semantic_forbidden_phrases=(),
            fallback_text="",
            category="policy_identification",
        )
        contract = ac.ContractEvaluationView(
            contract_id="synthetic-other-contract", version="v1", schema_version="v1",
            benchmark_id="synthetic", question_id="Q9", object_key="synthetic/other.json",
            content_sha256="f" * 64, required_criterion_ids=(criterion.id,),
            evidence_constraints={}, semantic_preservation={}, duplication_rules={},
            criteria=(criterion,), structure_requirements=ac.StructureRequirements((), (), ()),
        )
        documents = ({"nyscef_document_number": 42, "pages": ({"page_number": 7, "text": "Policy No. 10268L60059 applies."},)},)
        self.assertEqual(
            GEN.append_source_backed_missing_presence_excerpts("Other answer.", documents, contract),
            "Other answer.",
        )

    def test_non_q3_contract_is_unchanged(self):
        contract = ac.ContractEvaluationView(
            contract_id="synthetic-other-contract",
            version="v1.0.0",
            schema_version="v1",
            benchmark_id="synthetic",
            question_id="Q9",
            object_key="synthetic/other-contract.json",
            content_sha256="b" * 64,
            required_criterion_ids=(),
            evidence_constraints={},
            semantic_preservation={},
            duplication_rules={},
            criteria=(),
            structure_requirements=ac.StructureRequirements((), (), ()),
        )
        self.assertEqual(GEN.append_q3_policy_context("Unchanged.", contract), "Unchanged.")

    def test_present_facts_are_not_repeated(self):
        contract = ac.ContractEvaluationView(
            contract_id=GEN.Q3_INSURANCE_POLICY_COVERAGE_CONTRACT_ID,
            version="v1.0.0", schema_version="v1", benchmark_id="Case-00-Triborough",
            question_id="Q3", object_key="synthetic/q3-contract.json",
            content_sha256="c" * 64, required_criterion_ids=(),
            evidence_constraints={}, semantic_preservation={}, duplication_rules={},
            criteria=(), structure_requirements=ac.StructureRequirements((), (), ()),
        )
        answer = (
            "The record identifies the policies as issued or allegedly issued to Triborough Construction Services Inc. "
            "Policy No. 10268L60059 is the 2016-2017 Policy; Policy No. 10268L170188 is the 2017-2018 Policy; "
            "and Policy No. 10268L170189 is the Excess Policy. The May 18, 2016 to May 18, 2017 period and "
            "$1,000,000/$2,000,000 limits are identified. The Excess Policy effective date is May 18, 2017."
        )
        self.assertEqual(GEN.append_q3_policy_context(answer, contract), answer)

    def test_finalization_repairs_q3_duplication_reintroduced_by_presentation(self):
        facts = (
            "issued or allegedly issued to Triborough Construction Services Inc.",
            "10268L60059",
            "10268L170188",
            "10268L170189",
        )
        criteria = tuple(
            ac.CriterionEvalSpec(
                id=f"q3-policy-{index}",
                presence_phrases=(fact,),
                evidence_phrases=(fact,),
                semantic_required_phrases=(fact,),
                semantic_forbidden_phrases=(),
                fallback_text="",
                category="policy",
            )
            for index, fact in enumerate(facts, start=1)
        )
        contract = ac.ContractEvaluationView(
            contract_id=GEN.Q3_INSURANCE_POLICY_COVERAGE_CONTRACT_ID,
            version="v1.0.0", schema_version="v1", benchmark_id="Case-00-Triborough",
            question_id="Q3", object_key="synthetic/q3-contract.json",
            content_sha256="d" * 64,
            required_criterion_ids=tuple(item.id for item in criteria),
            evidence_constraints={}, semantic_preservation={"forbid_material_omissions": True},
            duplication_rules={"max_duplicate_phrase_ratio": 0.25}, criteria=criteria,
            structure_requirements=ac.StructureRequirements((), (), ()),
        )
        answer = " ".join((
            "The record identifies the policies as issued or allegedly issued to Triborough Construction Services Inc.",
            "The record identifies the policies as issued or allegedly issued to Triborough Construction Services Inc.",
            "The record identifies Policy No. 10268L60059, the 2016-2017 Policy.",
            "The record identifies Policy No. 10268L170188, the 2017-2018 Policy.",
            "The record identifies Policy No. 10268L170189, the Excess Policy.",
        ))
        final_answer, result = GEN.finalize_canonical_answer_against_contract(answer, contract)
        self.assertTrue(result.ok, result.diagnostics)
        self.assertIn(result.duplication_result, {ac.DUP_OK, ac.DUP_REPAIRED})
        self.assertTrue(all(item.result_code == ac.CRIT_PASS for item in result.criterion_results))
        self.assertIn("10268L60059", final_answer)


if __name__ == "__main__":
    unittest.main()
