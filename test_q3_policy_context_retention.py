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


if __name__ == "__main__":
    unittest.main()
