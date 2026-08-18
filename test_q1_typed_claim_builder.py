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
    def test_party_role_retrieval_merges_bounded_numbered_action_pass(self):
        primary_hit = {"page_id": "page-primary", "result_id": "primary"}
        duplicate_hit = {"page_id": "page-primary", "result_id": "duplicate"}
        dual_action_hit = {
            "page_id": "page-dual",
            "result_id": "dual",
            "excerpt": "Unrelated query-centered lead.",
        }

        with mock.patch.object(
            CLI.mb,
            "prepare_documents_for_canonical_retrieval",
            return_value=[
                {
                    "nyscef_document_number": 7,
                    "pages": [
                        {
                            "page_id": "page-dual",
                            "text": (
                                "The Underwriters are plaintiffs in Action No. 1 "
                                "and defendants in Action No. 2."
                            ),
                        },
                        {"page_id": "page-other", "text": "Other allegations."},
                    ],
                }
            ],
        ), mock.patch.object(
            CLI.mb,
            "retrieve_canonical_records",
            side_effect=[
                {"query": "primary", "results": [primary_hit], "result_count": 1},
                {
                    "query": "supplemental",
                    "results": [duplicate_hit, dual_action_hit],
                    "result_count": 2,
                },
            ],
        ) as retrieve:
            result = CLI.run_production_retrieval(
                [{"document": True}],
                {"case_map": True},
                "Who are the parties and what are their roles?",
                top_k=30,
            )

        self.assertEqual(retrieve.call_count, 2)
        self.assertEqual(
            retrieve.call_args_list[1].args[1],
            "Action No. 1 Action No. 2 plaintiff defendant related action "
            "party roles",
        )
        self.assertEqual(retrieve.call_args_list[1].kwargs["top_k"], 10)
        self.assertEqual(
            [row["page_id"] for row in result["results"]],
            ["page-primary", "page-dual"],
        )
        self.assertEqual(
            result["results"][1]["excerpt"],
            "The Underwriters are plaintiffs in Action No. 1 and defendants "
            "in Action No. 2.",
        )
        self.assertTrue(
            result["results"][1]["party_role_numbered_action_excerpt"]
        )
        self.assertEqual(
            result["party_role_supplemental_retrieval"],
            {
                "query_kind": "deterministic_numbered_related_action_roles",
                "max_hits": 10,
                "primary_result_count": 1,
                "matched_page_count": 1,
                "matched_page_ids": ["page-dual"],
                "supplemental_added_count": 1,
                "focused_excerpt_count": 1,
            },
        )

        supplemental_documents = retrieve.call_args_list[1].args[0]
        self.assertEqual(
            [page["page_id"] for page in supplemental_documents[0]["pages"]],
            ["page-dual"],
        )

    def test_numbered_action_excerpt_does_not_combine_unrelated_sentences(self):
        text = (
            "Plaintiffs filed Action No. 1. "
            "Defendants later answered in Action No. 2."
        )

        self.assertEqual(CLI._numbered_related_action_excerpt(text), "")

    def test_numbered_action_excerpt_collapses_visual_line_wraps(self):
        text = (
            "Attorneys for the Plaintiff, In Action No.: 1\n"
            "Defendants in Action No.: 2\n"
            "Certain Interested Underwriters At Lloyd's, London.\n"
            "Unrelated filing history follows."
        )

        self.assertEqual(
            CLI._numbered_related_action_excerpt(text),
            "Attorneys for the Plaintiff, In Action No.: 1 Defendants in "
            "Action No.: 2 Certain Interested Underwriters At Lloyd's, London.",
        )

    def test_numbered_action_excerpt_accepts_action_before_role(self):
        text = (
            "In Action No.: 1, the Underwriters are Plaintiffs; "
            "in Action No.: 2, they are Defendants."
        )

        self.assertEqual(CLI._numbered_related_action_excerpt(text), text)

    def test_validated_numbered_action_excerpt_survives_packet_serialization(self):
        excerpt = (
            "In Action No.: 1, the Underwriters are Plaintiffs; "
            "in Action No.: 2, they are Defendants."
        )
        packet = CLI.de.build_evidence_packet(
            "Who are the parties and what are their roles?",
            {
                "results": [
                    {
                        "result_id": "focused-related-action",
                        "page_id": "focused-page",
                        "document_type": "affirmation",
                        "classifications": ["procedural"],
                        "excerpt": excerpt,
                        "party_role_numbered_action_excerpt": True,
                    }
                ]
            },
        )

        self.assertEqual(len(packet["retrieval_hits"]), 1)
        self.assertEqual(packet["retrieval_hits"][0]["excerpt"], excerpt)
        self.assertTrue(
            packet["retrieval_hits"][0][
                "party_role_numbered_action_excerpt"
            ]
        )

    def test_party_role_retrieval_skips_supplemental_without_exact_page(self):
        with mock.patch.object(
            CLI.mb,
            "prepare_documents_for_canonical_retrieval",
            return_value=[
                {
                    "pages": [
                        {
                            "page_id": "page-generic",
                            "text": "Plaintiff and defendant appear in the action.",
                        }
                    ]
                }
            ],
        ), mock.patch.object(
            CLI.mb,
            "retrieve_canonical_records",
            return_value={"results": [], "result_count": 0},
        ) as retrieve:
            result = CLI.run_production_retrieval(
                [],
                {},
                "Who are the parties and what are their roles?",
                top_k=30,
            )

        self.assertEqual(retrieve.call_count, 1)
        self.assertEqual(
            result["party_role_supplemental_retrieval"]["matched_page_count"], 0
        )
        self.assertEqual(
            result["party_role_supplemental_retrieval"]["matched_page_ids"], []
        )

    def test_non_party_role_retrieval_remains_single_pass(self):
        with mock.patch.object(
            CLI.mb,
            "prepare_documents_for_canonical_retrieval",
            return_value=[],
        ), mock.patch.object(
            CLI.mb,
            "retrieve_canonical_records",
            return_value={"results": [], "result_count": 0},
        ) as retrieve:
            result = CLI.run_production_retrieval(
                [],
                {},
                "What relief does the complaint request?",
                top_k=30,
            )

        self.assertEqual(retrieve.call_count, 1)
        self.assertNotIn("party_role_supplemental_retrieval", result)

    def test_failure_diagnostics_expose_only_safe_supplemental_fields(self):
        diagnostics = CLI.safe_party_role_supplemental_diagnostics(
            {
                "audit": {
                    "party_role_supplemental_retrieval": {
                        "query_kind": "deterministic_numbered_related_action_roles",
                        "max_hits": 10,
                        "primary_result_count": 30,
                        "matched_page_count": 1,
                        "matched_page_ids": ["nyscef-7-page-3"],
                        "supplemental_added_count": 1,
                        "focused_excerpt_count": 1,
                        "serialized_numbered_action_hit_count": 1,
                        "private_excerpt": "must not escape",
                    }
                }
            }
        )

        self.assertEqual(
            diagnostics,
            {
                "query_kind": "deterministic_numbered_related_action_roles",
                "max_hits": 10,
                "primary_result_count": 30,
                "matched_page_count": 1,
                "matched_page_ids": ["nyscef-7-page-3"],
                "supplemental_added_count": 1,
                "focused_excerpt_count": 1,
                "serialized_numbered_action_hit_count": 1,
            },
        )

    def test_failure_diagnostics_absent_for_non_party_retrieval(self):
        self.assertIsNone(
            CLI.safe_party_role_supplemental_diagnostics({"audit": {}})
        )

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
                        "substantive_role_term_min_sentence_distance": {},
                    },
                    {
                        "party_index": 1,
                        "evidence_sentence_match_count": 1,
                        "evidence_field_categories": [
                            "identity",
                            "related_action_roles",
                            "substantive_role",
                        ],
                        "substantive_role_term_min_sentence_distance": {
                            "named_insured": 0,
                            "insured": 0,
                        },
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
                "numbered_dual_role_window_count": 0,
                "numbered_dual_role_identity_party_count": 0,
                "related_action_role_party_count": 1,
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

    def test_associates_adjacent_role_without_cross_party_leakage(self):
        result = {
            "review_scope": {"completeness": "not_established"},
            "audit": {
                "party_role_expected_attributes": [
                    {
                        "identity": "Synthetic Alpha",
                        "procedural_role": "defendant",
                        "pleaded_role_basis": "",
                    },
                    {
                        "identity": "Synthetic Beta",
                        "procedural_role": "defendant",
                        "pleaded_role_basis": "",
                    },
                ]
            },
        }
        evidence_packet = {
            "retrieval_hits": [
                {
                    "excerpt": (
                        "Synthetic Alpha appears in this action. "
                        "It is the named insured."
                    )
                },
                {
                    "excerpt": (
                        "Synthetic Alpha and Synthetic Beta are defendants. "
                        "The contractor performed the work."
                    )
                },
                {
                    "excerpt": (
                        "Synthetic Beta appears. "
                        "Synthetic Alpha is the owner."
                    )
                },
                {
                    "excerpt": (
                        "Synthetic Beta appears alone. "
                        "The contractor performed unrelated work."
                    )
                },
            ]
        }

        diagnostics = {}
        claims = CLI.build_q1_validated_party_claims(
            result,
            evidence_packet=evidence_packet,
            diagnostics_out=diagnostics,
        )
        by_name = {party["identity"]: party for party in claims["parties"]}

        self.assertEqual(
            diagnostics["parties"][0][
                "substantive_role_term_min_sentence_distance"
            ],
            {
                "named_insured": 1,
                "insured": 1,
                "owner": 0,
                "contractor": 1,
            },
        )
        self.assertEqual(
            diagnostics["parties"][1][
                "substantive_role_term_min_sentence_distance"
            ],
            {"owner": 1, "contractor": 1},
        )
        serialized_diagnostics = repr(diagnostics)
        self.assertNotIn("Synthetic Alpha", serialized_diagnostics)
        self.assertNotIn("Synthetic Beta", serialized_diagnostics)
        self.assertNotIn("It is the named insured", serialized_diagnostics)

        self.assertEqual(
            by_name["Synthetic Alpha"]["substantive_role"],
            "named insured; owner",
        )
        self.assertEqual(
            by_name["Synthetic Alpha"]["pleaded_role_basis"],
            "named insured; owner",
        )
        self.assertEqual(by_name["Synthetic Beta"]["substantive_role"], "")
        self.assertEqual(by_name["Synthetic Beta"]["pleaded_role_basis"], "")
        self.assertNotIn(
            "contractor",
            by_name["Synthetic Alpha"]["substantive_role"],
        )

    def test_renders_and_retains_substantive_role_limitation(self):
        claims = {
            "schema_version": "q1_validated_party_claims.v1",
            "roster_completeness": "complete",
            "parties": [
                {
                    "identity": "Synthetic Party",
                    "procedural_roles": ["defendant"],
                    "pleaded_role_basis": "",
                    "substantive_role": "",
                    "entity_type": "",
                    "residence_or_ppb": "",
                    "related_action_roles": [],
                }
            ],
        }

        rendered = CLI.render_q1_validated_party_claims(claims)
        limitation = CLI._Q1_SUBSTANTIVE_ROLE_LIMITATION
        self.assertIn(
            "do not establish the substantive role allegedly played",
            rendered,
        )
        self.assertIn("claimant, or injured person", rendered)
        self.assertIn(limitation, rendered)
        self.assertTrue(CLI.q1_rendered_claims_present(rendered, claims))

        without_limitation = rendered.replace(limitation, "")
        self.assertFalse(
            CLI.q1_rendered_claims_present(without_limitation, claims)
        )
        restored = CLI.retain_q1_validated_party_claims(
            without_limitation,
            claims,
        )
        self.assertIn(limitation, restored)
        self.assertEqual(restored.count(limitation), 1)

    def test_limitation_remains_when_only_some_defendant_roles_are_known(self):
        claims = {
            "schema_version": "q1_validated_party_claims.v1",
            "roster_completeness": "complete",
            "parties": [
                {
                    "identity": "Synthetic Known Defendant",
                    "procedural_roles": ["defendant"],
                    "pleaded_role_basis": "named insured",
                    "substantive_role": "named insured",
                    "related_action_roles": [],
                },
                {
                    "identity": "Synthetic Unknown Defendant",
                    "procedural_roles": ["defendant"],
                    "pleaded_role_basis": "",
                    "substantive_role": "",
                    "related_action_roles": [],
                },
            ],
        }

        rendered = CLI.render_q1_validated_party_claims(claims)
        self.assertIn(CLI._Q1_SUBSTANTIVE_ROLE_LIMITATION, rendered)
        self.assertTrue(CLI.q1_rendered_claims_present(rendered, claims))

    def test_extracts_and_renders_numbered_underwriter_dual_role(self):
        result = {
            "review_scope": {"completeness": "not_established"},
            "audit": {
                "party_role_expected_attributes": [
                    {
                        "identity": "Certain Interested Underwriters At Lloyd's, London",
                        "procedural_role": "plaintiff",
                        "pleaded_role_basis": "",
                    }
                ]
            },
        }
        packet = {
            "retrieval_hits": [
                {
                    "excerpt": (
                        "Attorneys for the Plaintiff, In Action No.: 1 "
                        "Defendants in Action No.: 2 Certain Interested "
                        "Underwriters At Lloyd's, London."
                    )
                }
            ]
        }

        diagnostics = {}
        claims = CLI.build_q1_validated_party_claims(
            result,
            evidence_packet=packet,
            diagnostics_out=diagnostics,
        )
        party = claims["parties"][0]
        self.assertIn(
            "defendant in Action No. 2",
            party["related_action_roles"],
        )
        self.assertEqual(diagnostics["numbered_dual_role_window_count"], 1)
        self.assertEqual(
            diagnostics["numbered_dual_role_identity_party_count"], 1
        )
        self.assertEqual(diagnostics["related_action_role_party_count"], 1)
        rendered = CLI.render_q1_validated_party_claims(claims)
        self.assertIn(
            "A later filing describes the Underwriters as plaintiff in "
            "Action No. 1 and defendants in Action No. 2.",
            rendered,
        )
        self.assertTrue(CLI.q1_rendered_claims_present(rendered, claims))

    def test_typed_claim_window_does_not_split_action_no_abbreviation(self):
        result = {
            "review_scope": {"completeness": "not_established"},
            "audit": {
                "party_role_expected_attributes": [
                    {
                        "identity": "Synthetic Underwriters",
                        "procedural_role": "plaintiff",
                        "pleaded_role_basis": "",
                    }
                ]
            },
        }
        packet = {
            "retrieval_hits": [
                {
                    "excerpt": (
                        "Action No. 1 lists Synthetic Underwriters as Plaintiffs; "
                        "Action No. 2 lists them as Defendants."
                    )
                }
            ]
        }

        diagnostics = {}
        CLI.build_q1_validated_party_claims(
            result,
            evidence_packet=packet,
            diagnostics_out=diagnostics,
        )

        self.assertEqual(diagnostics["numbered_dual_role_window_count"], 1)
        self.assertEqual(
            diagnostics["numbered_dual_role_identity_party_count"], 1
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
            final_answer=CLI.render_q1_validated_party_claims(claims),
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

    def test_q1_final_validation_uses_safe_deduplicated_answer(self):
        claims = {
            "schema_version": "q1_validated_party_claims.v1",
            "roster_completeness": "complete",
            "parties": [
                {
                    "identity": "Synthetic Deduped Party",
                    "procedural_roles": ["defendant"],
                    "pleaded_role_basis": "named insured",
                    "substantive_role": "named insured",
                    "related_action_roles": [],
                }
            ],
        }
        summary = CLI.render_q1_validated_party_claims(claims)
        first = CLI.ac.AcceptanceValidationResult(
            ok=False,
            final_answer="Duplicative attorney analysis.",
        )
        second = CLI.ac.AcceptanceValidationResult(
            ok=True,
            final_answer=summary,
            duplication_result=CLI.ac.DUP_REPAIRED,
        )

        with mock.patch.object(
            CLI.ac,
            "validate_final_answer_against_contract",
            side_effect=[first, second],
        ) as validate:
            canonical, validation = CLI.finalize_canonical_answer_against_contract(
                summary,
                object(),
                canonicalize=lambda text: text,
                validated_claims=claims,
            )

        self.assertEqual(canonical, summary)
        self.assertEqual(validation.final_answer, summary)
        self.assertTrue(CLI.q1_rendered_claims_present(canonical, claims))
        self.assertTrue(
            validate.call_args_list[1].kwargs["apply_duplication_repair"]
        )

    def test_q1_retention_places_authoritative_summary_before_model_prose(self):
        claims = {
            "schema_version": "q1_validated_party_claims.v1",
            "roster_completeness": "complete",
            "parties": [
                {
                    "identity": "Synthetic Priority Party",
                    "procedural_roles": ["defendant"],
                    "pleaded_role_basis": "named insured",
                    "substantive_role": "named insured",
                    "related_action_roles": ["defendant in Action No. 2"],
                }
            ],
        }
        model_prose = "Synthetic Priority Party is a defendant."

        retained = CLI.retain_q1_validated_party_claims(model_prose, claims)

        self.assertTrue(
            retained.startswith("Validated party/role summary:")
        )
        self.assertTrue(CLI.q1_rendered_claims_present(retained, claims))
        self.assertGreater(retained.find(model_prose), retained.find("related-action role:"))

    def test_dedupe_preserves_distinct_validated_high_overlap_identities(self):
        first = (
            "Alpha Holdings Insurance Company — current role: defendant; "
            "pleaded designation: named insured."
        )
        second = (
            "Alpha Holdings Insurance Company of New York — current role: "
            "defendant; pleaded designation: named insured."
        )

        repaired, result, _diagnostics = CLI.ac.apply_duplication_gate(
            f"{first} {second}",
            {"max_duplicate_phrase_ratio": 0.25},
            validated_identities=[
                "Alpha Holdings Insurance Company",
                "Alpha Holdings Insurance Company of New York",
            ],
        )

        self.assertEqual(result, CLI.ac.DUP_OK)
        self.assertIn(first, repaired)
        self.assertIn(second, repaired)

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
