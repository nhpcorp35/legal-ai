"""Synthetic tests for the typed Case-00 Q1 acceptance handoff."""

import copy
import unittest

import acceptance_contract as ac


class Q1TypedPartyClaimsTests(unittest.TestCase):
    CRITERION_IDS = (
        "Q1_C1_PLAINTIFF_ROLE",
        "Q1_C2_DEFENDANT_SIDE_PARTIES",
        "Q1_C3_SPECIFIC_DEFENDANT_ROLE_DESIGNATIONS",
        "Q1_C4_LIMITED_SUBSTANTIVE_ROLE_INFORMATION",
        "Q1_C5_DUAL_ROLES_IN_RELATED_ACTION",
        "Q1_C6_INCOMPLETE_PARTY_ROSTER",
    )

    def claims(self):
        return {
            "schema_version": ac.Q1_VALIDATED_PARTY_CLAIMS_SCHEMA_VERSION,
            "roster_completeness": "not_established",
            "parties": [
                {
                    "identity": "Synthetic Underwriters",
                    "procedural_roles": ["plaintiff"],
                    "pleaded_role_basis": "insurer seeking declaratory relief",
                    "substantive_role": "insurer",
                    "related_action_roles": ["defendant"],
                },
                {
                    "identity": "Synthetic Contractor",
                    "procedural_roles": ["defendant"],
                    "pleaded_role_basis": "named insured",
                    "substantive_role": "named insured",
                    "related_action_roles": ["third-party plaintiff"],
                },
                {
                    "identity": "Synthetic Caption Defendant",
                    "procedural_roles": ["defendant"],
                    "pleaded_role_basis": "",
                    "substantive_role": "",
                    "related_action_roles": [],
                },
            ],
        }

    @staticmethod
    def spec(criterion_id):
        return ac.CriterionEvalSpec(
            id=criterion_id,
            presence_phrases=("never-copy-contract-prose",),
            evidence_phrases=("never-copy-evidence-prose",),
            semantic_required_phrases=("never-copy-semantic-prose",),
            semantic_forbidden_phrases=(),
            fallback_text="",
        )

    def evaluate(self, criterion_id, claims):
        return ac.evaluate_criterion(
            "attorney-facing prose with different vocabulary",
            self.spec(criterion_id),
            semantic_preservation={},
            validated_claims=claims,
            validated_evidence_text="validated evidence with different vocabulary",
        )

    def test_all_six_criteria_use_typed_claims_not_contract_wording(self):
        claims = self.claims()
        for criterion_id in self.CRITERION_IDS:
            with self.subTest(criterion_id=criterion_id):
                result = self.evaluate(criterion_id, claims)
                self.assertEqual(result.result_code, ac.CRIT_PASS)
                self.assertEqual(result.presence, ac.PRESENCE_PRESENT)
                self.assertEqual(result.evidence, ac.EVIDENCE_SUPPORTED)
                self.assertEqual(
                    result.phrase_coverage["presence"]["matched_indices"], []
                )

    def test_each_criterion_fails_closed_when_its_claim_is_missing(self):
        for criterion_id in self.CRITERION_IDS:
            claims = copy.deepcopy(self.claims())
            if criterion_id == "Q1_C1_PLAINTIFF_ROLE":
                claims["parties"][0]["procedural_roles"] = []
            elif criterion_id == "Q1_C2_DEFENDANT_SIDE_PARTIES":
                for party in claims["parties"]:
                    party["procedural_roles"] = [
                        role
                        for role in party["procedural_roles"]
                        if "defendant" not in role
                    ]
            elif criterion_id == "Q1_C3_SPECIFIC_DEFENDANT_ROLE_DESIGNATIONS":
                claims["parties"][1]["pleaded_role_basis"] = ""
            elif criterion_id == "Q1_C4_LIMITED_SUBSTANTIVE_ROLE_INFORMATION":
                for party in claims["parties"]:
                    if "defendant" in party["procedural_roles"]:
                        party["substantive_role"] = "named insured"
            elif criterion_id == "Q1_C5_DUAL_ROLES_IN_RELATED_ACTION":
                for party in claims["parties"]:
                    party["related_action_roles"] = []
            elif criterion_id == "Q1_C6_INCOMPLETE_PARTY_ROSTER":
                claims["roster_completeness"] = "complete"
            with self.subTest(criterion_id=criterion_id):
                result = self.evaluate(criterion_id, claims)
                self.assertEqual(result.result_code, ac.CRIT_FAIL_MISSING)

    def test_c3_allows_caption_only_defendant_when_another_is_designated(self):
        claims = self.claims()
        claims["parties"].append(
            {
                "identity": "Synthetic Caption Defendant",
                "procedural_roles": ["defendant"],
                "pleaded_role_basis": "",
                "substantive_role": "",
                "related_action_roles": [],
            }
        )
        result = self.evaluate(
            "Q1_C3_SPECIFIC_DEFENDANT_ROLE_DESIGNATIONS",
            claims,
        )
        self.assertEqual(result.result_code, ac.CRIT_PASS)

    def test_c3_fails_when_all_defendants_are_caption_only(self):
        claims = self.claims()
        for party in claims["parties"]:
            if "defendant" in party["procedural_roles"]:
                party["pleaded_role_basis"] = ""
        result = self.evaluate(
            "Q1_C3_SPECIFIC_DEFENDANT_ROLE_DESIGNATIONS",
            claims,
        )
        self.assertEqual(result.result_code, ac.CRIT_FAIL_MISSING)

    def test_malformed_claims_cannot_bypass_phrase_gate(self):
        claims = self.claims()
        claims["schema_version"] = "wrong"
        result = self.evaluate("Q1_C1_PLAINTIFF_ROLE", claims)
        self.assertEqual(result.result_code, ac.CRIT_FAIL_MISSING)


if __name__ == "__main__":
    unittest.main()
