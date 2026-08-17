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
                        "Synthetic Contractor is the named insured, a defendant "
                        "here, and a third-party plaintiff in the related action."
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
        rendered = CLI.render_q1_validated_party_claims(claims)
        self.assertIn("Validated party/role summary:", rendered)
        self.assertIn("related-action role: third-party plaintiff", rendered)
        self.assertIn("does not establish that this is a complete party roster", rendered)
        self.assertTrue(CLI.q1_rendered_claims_present(rendered, claims))
        self.assertFalse(
            CLI.q1_rendered_claims_present(
                rendered.replace("third-party plaintiff", ""), claims
            )
        )

    def test_restores_typed_summary_after_contract_repair_drops_it(self):
        claims = {
            "schema_version": "q1_validated_party_claims.v1",
            "roster_completeness": "not_established",
            "parties": [
                {
                    "identity": "Synthetic Underwriters",
                    "procedural_roles": ["plaintiff"],
                    "pleaded_role_basis": "insurer",
                    "substantive_role": "insurer",
                    "related_action_roles": ["defendant"],
                }
            ],
        }
        repaired_without_summary = "Attorney analysis retained after contract repair."
        restored = CLI.retain_q1_validated_party_claims(
            repaired_without_summary, claims
        )
        self.assertTrue(CLI.q1_rendered_claims_present(restored, claims))
        self.assertEqual(restored.count("Validated party/role summary:"), 1)
        self.assertEqual(
            CLI.retain_q1_validated_party_claims(restored, claims), restored
        )

    def test_missing_field_diagnostics_are_privacy_safe(self):
        claims = {
            "schema_version": "q1_validated_party_claims.v1",
            "roster_completeness": "not_established",
            "parties": [
                {
                    "identity": "Synthetic Secret Party",
                    "procedural_roles": ["plaintiff"],
                    "pleaded_role_basis": "secret pleaded basis",
                    "substantive_role": "secret substantive role",
                    "related_action_roles": ["secret related role"],
                }
            ],
        }
        diagnostics = CLI.q1_missing_rendered_claim_fields("plaintiff", claims)
        self.assertEqual(
            diagnostics,
            [
                {"party_index": 0, "field": "identity"},
                {"party_index": 0, "field": "pleaded_role_basis"},
                {"party_index": 0, "field": "substantive_role"},
                {"party_index": 0, "field": "related_action_roles"},
                {"party_index": None, "field": "roster_completeness"},
            ],
        )
        serialized = repr(diagnostics)
        self.assertNotIn("Synthetic Secret Party", serialized)
        self.assertNotIn("secret pleaded basis", serialized)
        self.assertNotIn("secret substantive role", serialized)
        self.assertNotIn("secret related role", serialized)

    def test_empty_inventory_is_valid_and_fails_closed_at_criteria(self):
        claims = CLI.build_q1_validated_party_claims(
            {"propositions": [], "audit": {}, "review_scope": {}}
        )
        self.assertEqual(claims["parties"], [])
        self.assertEqual(claims["roster_completeness"], "not_established")


if __name__ == "__main__":
    unittest.main()
