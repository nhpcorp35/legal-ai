"""Synthetic tests for the Q1 typed-claims generation boundary."""

import importlib.util
import unittest
from pathlib import Path


def load_cli():
    path = Path(__file__).parent / "scripts" / "generate_attorney_feedback_candidate.py"
    spec = importlib.util.spec_from_file_location("q1_typed_claim_builder", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


CLI = load_cli()


class Q1TypedClaimBuilderTests(unittest.TestCase):
    def test_builds_party_roles_related_roles_and_incomplete_scope(self):
        result = {
            "propositions": [
                {
                    "text": (
                        "Synthetic Contractor is a defendant here and a "
                        "third-party plaintiff in the related action."
                    ),
                    "source_excerpt": "Synthetic Contractor third-party plaintiff.",
                }
            ],
            "review_scope": {"completeness": "not_established"},
            "audit": {
                "party_role_expected_attributes": [
                    {
                        "identity": "Synthetic Underwriters",
                        "procedural_role": "plaintiff",
                        "pleaded_role_basis": "insurer",
                    },
                    {
                        "identity": "Synthetic Contractor",
                        "procedural_role": "defendant",
                        "pleaded_role_basis": "named insured",
                    },
                ]
            },
        }
        claims = CLI.build_q1_validated_party_claims(result)
        self.assertEqual(
            claims["schema_version"],
            "q1_validated_party_claims.v1",
        )
        self.assertEqual(claims["roster_completeness"], "not_established")
        by_name = {party["identity"]: party for party in claims["parties"]}
        self.assertEqual(
            by_name["Synthetic Underwriters"]["procedural_roles"],
            ["plaintiff"],
        )
        self.assertIn(
            "third-party plaintiff",
            by_name["Synthetic Contractor"]["related_action_roles"],
        )
        self.assertEqual(
            by_name["Synthetic Contractor"]["substantive_role"],
            "named insured",
        )

    def test_empty_inventory_is_valid_and_fails_closed_at_criteria(self):
        claims = CLI.build_q1_validated_party_claims(
            {"propositions": [], "audit": {}, "review_scope": {}}
        )
        self.assertEqual(claims["parties"], [])
        self.assertEqual(claims["roster_completeness"], "not_established")


if __name__ == "__main__":
    unittest.main()
