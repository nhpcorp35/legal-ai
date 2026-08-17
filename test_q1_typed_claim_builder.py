"""Synthetic tests for the Q1 typed-claims generation boundary."""

import importlib.util
import unittest
from pathlib import Path
from unittest import mock


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
                    "text": "Synthetic Contractor is a landlord in model prose.",
                    "source_excerpt": "Synthetic Contractor landlord.",
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
        evidence_packet = {
            "retrieval_hits": [
                {
                    "page_id": "synthetic-page-1",
                    "excerpt": (
                        "Synthetic Contractor is the named insured and a "
                        "defendant here. In the related action, it is a "
                        "third-party plaintiff."
                    ),
                }
            ]
        }
        diagnostics = {}
        claims = CLI.build_q1_validated_party_claims(
            result,
            evidence_packet=evidence_packet,
            diagnostics_out=diagnostics,
        )
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
        self.assertEqual(
            by_name["Synthetic Underwriters"]["substantive_role"],
            "insurer",
        )
        self.assertIn(
            "third-party plaintiff",
            by_name["Synthetic Contractor"]["related_action_roles"],
        )
        self.assertEqual(
            by_name["Synthetic Contractor"]["substantive_role"],
            "named insured",
        )
        self.assertEqual(
            by_name["Synthetic Contractor"]["pleaded_role_basis"],
            "named insured",
        )
        self.assertNotIn(
            "landlord", by_name["Synthetic Contractor"]["substantive_role"]
        )
        self.assertEqual(
            diagnostics,
            {
                "party_count": 2,
                "parties": [
                    {
                        "party_index": 0,
                        "evidence_sentence_match_count": 0,
                        "evidence_field_categories": ["substantive_role"],
                    },
                    {
                        "party_index": 1,
                        "evidence_sentence_match_count": 1,
                        "evidence_field_categories": [
                            "identity",
                            "related_action_roles",
                            "substantive_role",
                        ],
                    },
                ],
                "role_vocabulary_counts": {
                    "substantive_role_terms": {
                        "named_insured": 1,
                        "insured": 1,
                        "contractor": 1,
                    },
                    "related_action_cues": {"related_action": 1},
                    "procedural_role_terms": {
                        "plaintiff": 1,
                        "defendant": 1,
                        "third_party_plaintiff": 1,
                    },
                },
            },
        )
        serialized_diagnostics = repr(diagnostics)
        self.assertNotIn("Synthetic Underwriters", serialized_diagnostics)
        self.assertNotIn("Synthetic Contractor", serialized_diagnostics)
        self.assertNotIn("synthetic-page-1", serialized_diagnostics)
        self.assertNotIn(
            "Synthetic Contractor is the named insured", serialized_diagnostics
        )
        self.assertNotIn("named insured", serialized_diagnostics)
        self.assertNotIn("third-party plaintiff", serialized_diagnostics)
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

    def test_appends_summary_after_lossy_canonicalization(self):
        claims = {
            "schema_version": "q1_validated_party_claims.v1",
            "roster_completeness": "complete",
            "parties": [
                {
                    "identity": "Synthetic Final Party",
                    "procedural_roles": ["defendant"],
                    "pleaded_role_basis": "",
                    "substantive_role": "",
                    "related_action_roles": [],
                }
            ],
        }

        def lossy_canonicalizer(text):
            return str(text).replace("Synthetic Final Party", "").strip()

        restored = CLI.retain_q1_validated_party_claims(
            "Attorney analysis.",
            claims,
            canonicalize=lossy_canonicalizer,
        )

        self.assertIn("Attorney analysis.", restored)
        self.assertIn("Synthetic Final Party", restored)
        self.assertNotIn("\\n", restored)
        self.assertTrue(CLI.q1_rendered_claims_present(restored, claims))

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

    def test_failed_first_contract_pass_revalidates_after_q1_retention(self):
        claims = {
            "schema_version": "q1_validated_party_claims.v1",
            "roster_completeness": "complete",
            "parties": [
                {
                    "identity": "Synthetic Restored Party",
                    "procedural_roles": ["defendant"],
                    "pleaded_role_basis": "named insured",
                    "substantive_role": "named insured",
                    "related_action_roles": ["third-party plaintiff"],
                }
            ],
        }
        first = CLI.ac.AcceptanceValidationResult(
            ok=False,
            final_answer="Attorney analysis after lossy contract repair.",
        )
        second = CLI.ac.AcceptanceValidationResult(
            ok=True,
            final_answer="unused validator copy",
        )
        diagnostics = {}

        with mock.patch.object(
            CLI.ac,
            "validate_final_answer_against_contract",
            side_effect=[first, second],
        ) as validate:
            canonical, validation = (
                CLI.finalize_canonical_answer_against_contract(
                    CLI.render_q1_validated_party_claims(claims),
                    object(),
                    canonicalize=lambda text: text,
                    validated_claims=claims,
                    q1_retention_diagnostics_out=diagnostics,
                )
            )

        self.assertEqual(validate.call_count, 2)
        self.assertTrue(validation.ok)
        self.assertTrue(CLI.q1_rendered_claims_present(canonical, claims))
        by_stage = {
            row["stage"]: row["missing_typed_claim_fields"]
            for row in diagnostics["stages"]
        }
        self.assertEqual(by_stage["pre_contract"], [])
        self.assertEqual(
            by_stage["post_contract_repair"],
            [
                {"party_index": 0, "field": "identity"},
                {"party_index": 0, "field": "procedural_roles"},
                {"party_index": 0, "field": "pleaded_role_basis"},
                {"party_index": 0, "field": "substantive_role"},
                {"party_index": 0, "field": "related_action_roles"},
            ],
        )
        self.assertEqual(by_stage["post_retention"], [])
        self.assertEqual(by_stage["final_validation"], [])

    def test_retention_stage_diagnostics_are_privacy_safe(self):
        claims = {
            "schema_version": "q1_validated_party_claims.v1",
            "roster_completeness": "complete",
            "parties": [
                {
                    "identity": "Synthetic Secret Party",
                    "procedural_roles": ["plaintiff"],
                    "pleaded_role_basis": "",
                    "substantive_role": "",
                    "related_action_roles": [],
                }
            ],
        }
        diagnostics = {"schema_version": "q1_retention_diagnostics.v1"}
        CLI.record_q1_retention_stage(
            diagnostics,
            stage="post_canonicalization",
            answer_text="Attorney analysis without the typed summary.",
            claims=claims,
        )
        self.assertEqual(
            diagnostics,
            {
                "schema_version": "q1_retention_diagnostics.v1",
                "stages": [
                    {
                        "stage": "post_canonicalization",
                        "missing_typed_claim_fields": [
                            {"party_index": 0, "field": "identity"},
                            {"party_index": 0, "field": "procedural_roles"},
                        ],
                    }
                ],
            },
        )
        self.assertNotIn("Synthetic Secret Party", repr(diagnostics))
        self.assertNotIn("plaintiff", repr(diagnostics))

    def test_empty_inventory_is_valid_and_fails_closed_at_criteria(self):
        claims = CLI.build_q1_validated_party_claims(
            {"propositions": [], "audit": {}, "review_scope": {}}
        )
        self.assertEqual(claims["parties"], [])
        self.assertEqual(claims["roster_completeness"], "not_established")


if __name__ == "__main__":
    unittest.main()
