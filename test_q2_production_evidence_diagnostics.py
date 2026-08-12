"""Privacy-safe Q2 production evidence diagnostics — leak and schema tests.

Injects unmistakable secrets/private strings into evidence packets, OCR quotes,
proposed answers, and hostile diagnostic payloads; asserts they never appear in
stdout JSON, diagnostic serialization, or stage metadata.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any

import acceptance_contract as ac
from engines import drafting_engine as de
from engines import q2_production_evidence_diagnostics as q2diag


_SECRET_EXCERPT = "SECRET_EXCERPT_LEAK_TOKEN_9f3a2c1b_NEVER_EMIT"
_SECRET_PAGE = (
    "SECRET_PAGE_TEXT_LEAK_TOKEN_7c88ee01 Alice Example "
    "alice.example@private.test password=hunter2-private "
    "Bearer sk-live-PRIVATE- creds=ENV_SECRET_VALUE"
)
_SECRET_PROPOSED = (
    'The complaint seeks rescission. as reflected in the cited pleading '
    f'language: "{_SECRET_PAGE}" (page_id nyscef-001-page-0025).'
)
_SECRET_NAME = "TriboroughPrivatePartyNameXYZ"
_SECRET_EMAIL = "counsel.secret@example-private.invalid"


def _packet_with_secrets() -> dict[str, Any]:
    return {
        "question": "What relief does the complaint request?",
        "retrieval_hit_count": 1,
        "retrieval_hits": [
            {
                "result_id": "hit-secret-diag-01",
                "page_id": "nyscef-001-page-0025",
                "nyscef_document_number": 1,
                "pdf_page": 25,
                "document_type": "complaint",
                "excerpt": _SECRET_EXCERPT,
                "page_text": (
                    f"{_SECRET_PAGE} {_SECRET_NAME} {_SECRET_EMAIL} "
                    "Declaring that there is no duty to defend or indemnify "
                    "Defendants. void the Policies ab initio. for such other "
                    "and further relief as the Court deems just and proper."
                ),
                "classifications": ["legal_position"],
                "score": 0.91,
            }
        ],
    }


def _collect_all_strings(obj: Any) -> list[str]:
    found: list[str] = []
    if isinstance(obj, str):
        found.append(obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            found.append(str(k))
            found.extend(_collect_all_strings(v))
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            found.extend(_collect_all_strings(item))
    return found


class Q2ProductionEvidenceDiagnosticsPrivacyTests(unittest.TestCase):
    def test_diagnostic_omits_secrets_from_serialization(self) -> None:
        packet = _packet_with_secrets()
        supported = de.extract_supported_complaint_relief(packet)
        assembled = de.apply_evidence_grounded_relief_synthesis(
            {"proposed_answer": _SECRET_PROPOSED, "propositions": [], "audit": {}},
            packet,
        )
        diag = q2diag.build_q2_production_evidence_diagnostics(
            evidence_packet=packet,
            reasoner_result=assembled,
            proposed_before_canonical=_SECRET_PROPOSED,
            canonical=assembled.get("proposed_answer") or "",
        )
        blob = q2diag.diagnostic_json_bytes(diag).decode("utf-8")
        for forbidden in (
            _SECRET_EXCERPT,
            _SECRET_PAGE,
            _SECRET_PROPOSED,
            _SECRET_NAME,
            _SECRET_EMAIL,
            "alice.example@private.test",
            "hunter2-private",
            "sk-live-PRIVATE",
            "ENV_SECRET_VALUE",
            "password=",
            "Bearer ",
        ):
            self.assertNotIn(forbidden, blob)

        # Structured support still observed via flags / lengths / ids only.
        stages = {s["stage"]: s for s in diag["stages"]}
        cache = stages["restored_derived_cache_evidence"]
        self.assertEqual(cache["hit_record_count"], 1)
        hit = cache["hits"][0]
        self.assertEqual(hit["page_id"], "nyscef-001-page-0025")
        self.assertTrue(hit["excerpt"]["present"])
        self.assertGreater(hit["excerpt"]["char_length"], 0)
        self.assertTrue(hit["page_text"]["present"])
        self.assertNotIn(_SECRET_EXCERPT, json.dumps(hit))

        relief = stages["relief_synthesis"]
        no_def = relief["categories"]["no_defense_or_indemnity"]
        self.assertTrue(no_def["supported"] or supported["no_defense_or_indemnity"]["supported"])
        self.assertEqual(no_def["page_id"], "nyscef-001-page-0025")
        self.assertNotIn("duty to defend", json.dumps(diag))

    def test_sanitizer_strips_hostile_private_payloads(self) -> None:
        hostile = {
            "schema_version": q2diag.DIAGNOSTIC_SCHEMA_VERSION,
            "stages": [
                {
                    "stage": "restored_derived_cache_evidence",
                    "secret_prose": _SECRET_EXCERPT,
                    "proposed_answer": _SECRET_PROPOSED,
                    "page_id": "nyscef-001-page-0099",
                    "hits": [
                        {
                            "page_id": "nyscef-001-page-0099",
                            "excerpt": _SECRET_EXCERPT,
                            "page_text": _SECRET_PAGE,
                            "email": _SECRET_EMAIL,
                            "name": _SECRET_NAME,
                        }
                    ],
                }
            ],
        }
        cleaned = q2diag.sanitize_diagnostic(hostile)
        blob = json.dumps(cleaned)
        for forbidden in (
            _SECRET_EXCERPT,
            _SECRET_PAGE,
            _SECRET_PROPOSED,
            _SECRET_EMAIL,
            _SECRET_NAME,
        ):
            self.assertNotIn(forbidden, blob)
        self.assertEqual(
            cleaned["stages"][0]["page_id"], "nyscef-001-page-0099"
        )

    def test_assert_no_forbidden_substrings_helper(self) -> None:
        packet = _packet_with_secrets()
        diag = q2diag.build_q2_production_evidence_diagnostics(
            evidence_packet=packet,
            proposed_before_canonical=_SECRET_PROPOSED,
        )
        q2diag.assert_no_forbidden_substrings(
            diag,
            [_SECRET_EXCERPT, _SECRET_EMAIL, _SECRET_NAME],
        )
        hostile = {
            "schema_version": q2diag.DIAGNOSTIC_SCHEMA_VERSION,
            "stages": [],
            "raw": _SECRET_EXCERPT,
        }
        # Unsanitized dump would leak; helper serializes via sanitizer.
        self.assertIn(_SECRET_EXCERPT, json.dumps(hostile))
        q2diag.assert_no_forbidden_substrings(hostile, [_SECRET_EXCERPT])
        cleaned = q2diag.sanitize_diagnostic(hostile)
        self.assertNotIn("raw", cleaned)
        self.assertNotIn(_SECRET_EXCERPT, json.dumps(cleaned))


class Q2ProductionEvidenceDiagnosticsSchemaTests(unittest.TestCase):
    def test_stage_schema_and_reason_codes_for_cache_shape(self) -> None:
        # Privacy-safe synthetic OCR folio mirroring production nesting.
        page = (
            "25\n\n"
            "184. entitled to void the Policies ab initio and for rescission.\n"
            "COUNT II Have No Obligations to Provide Defense or Indemnification "
            "Void Ab Initio 186. Declaring that there is no duty to defend or "
            "indemnify Defendants.\n"
            "187. WHEREFORE for such other and further relief as the Court "
            "deems just and proper."
        )
        packet = {
            "question": "What relief is requested?",
            "retrieval_hit_count": 1,
            "retrieval_hits": [
                {
                    "result_id": "hit-schema-01",
                    "page_id": "nyscef-001-page-0025",
                    "nyscef_document_number": 1,
                    "pdf_page": 25,
                    "document_type": "complaint",
                    "excerpt": page[:90],
                    "page_text": page,
                    "classifications": ["legal_position"],
                }
            ],
        }
        assembled = de.apply_evidence_grounded_relief_synthesis(
            {"proposed_answer": "Draft.", "propositions": [], "audit": {}},
            packet,
        )
        answer = assembled["proposed_answer"]
        # Build a minimal acceptance view with the no-defense criterion.
        contract = ac.build_synthetic_contract(
            contract_id="contract-q2-diag-01",
            version="1.0.0",
            benchmark_id="synth-benchmark-q2-diag",
            question_id="Q2",
            object_key="Contracts/synthetic/q2-diag.acceptance_contract.json",
            required_criterion_ids=[
                "q2-no-defense-or-indemnity",
                "q2-pleaded-not-adjudicated",
            ],
            criteria=[
                {
                    "id": "q2-no-defense-or-indemnity",
                    "category": "no_defense_or_indemnity",
                    "presence_phrases": ["no defense or indemnity"],
                    "evidence_phrases": ["no duty to defend or indemnify"],
                    "semantic_required_phrases": [],
                    "semantic_forbidden_phrases": [],
                    "fallback_text": "FALLBACK_PRIVATE_NEVER_EMIT_XYZ",
                },
                {
                    "id": "q2-pleaded-not-adjudicated",
                    "category": "pleaded_relief",
                    "presence_phrases": ["pleaded", "requested relief"],
                    "evidence_phrases": [],
                    "semantic_required_phrases": [],
                    "semantic_forbidden_phrases": ["adjudicated determination"],
                    "fallback_text": "",
                },
            ],
        )
        raw = json.dumps(contract, sort_keys=True).encode("utf-8")
        loaded = ac.load_acceptance_contract_from_bytes(
            raw,
            object_key=contract["object_key"],
            expected_identity=ac.ContractIdentity(
                benchmark_id="synth-benchmark-q2-diag",
                question_id="Q2",
            ),
            expected_content_sha256=contract["content_sha256"],
        )
        self.assertTrue(loaded.ok)
        view = loaded.evaluation
        assert view is not None
        validation = ac.validate_final_answer_against_contract(
            answer,
            view,
            apply_fallback=True,
            apply_duplication_repair=True,
        )
        diag = q2diag.build_q2_production_evidence_diagnostics(
            evidence_packet=packet,
            reasoner_result=assembled,
            proposed_before_canonical=answer,
            canonical=answer,
            validation=validation,
        )
        self.assertEqual(diag["schema_version"], q2diag.DIAGNOSTIC_SCHEMA_VERSION)
        stage_names = [s["stage"] for s in diag["stages"]]
        self.assertEqual(
            stage_names,
            [
                "restored_derived_cache_evidence",
                "relief_synthesis",
                "ocr_readability_scrub_handoff",
                "canonical_proposed_answer_and_acceptance",
            ],
        )
        cache = diag["stages"][0]
        shape_fields = {
            row["field_name"] for row in cache["hits"][0]["field_nesting_shape"]
        }
        self.assertIn("excerpt", shape_fields)
        self.assertIn("page_text", shape_fields)
        self.assertNotEqual(
            cache["hits"][0]["excerpt"]["char_length"],
            cache["hits"][0]["page_text"]["char_length"],
        )
        relief = diag["stages"][1]
        self.assertTrue(
            relief["categories"]["no_defense_or_indemnity"]["supported"]
        )
        # Fallback private text must never appear.
        blob = q2diag.diagnostic_json_bytes(diag).decode("utf-8")
        self.assertNotIn("FALLBACK_PRIVATE_NEVER_EMIT_XYZ", blob)
        self.assertNotIn(page, blob)

    def test_readability_reason_codes_match_gate_boolean(self) -> None:
        clean = "no duty to defend or indemnify Defendants"
        garbled = "Tri borough non-disclos ures COUNT II 25 183. dump"
        self.assertFalse(de.displayed_quote_fails_readability_gate(clean))
        self.assertEqual(de.readability_gate_reason_codes(clean), ())
        self.assertTrue(de.displayed_quote_fails_readability_gate(garbled))
        codes = de.readability_gate_reason_codes(garbled)
        self.assertTrue(codes)
        for code in codes:
            self.assertRegex(code, r"^[a-z0-9_]+$")


class Q2DiagnosticsGeneratorEmissionTests(unittest.TestCase):
    def test_failed_run_json_includes_diagnostics_without_secrets(self) -> None:
        """GenerationError payload retains diagnostics; secrets stay out."""
        import importlib.util

        path = (
            Path(__file__).resolve().parent
            / "scripts"
            / "generate_attorney_feedback_candidate.py"
        )
        spec = importlib.util.spec_from_file_location("gen_diag_emit", path)
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        repo_root = Path(__file__).resolve().parent
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)

        # Force unsupported no-defense by stripping indemnity language from packet.
        thin_page = (
            "184. void the Policies ab initio and for rescission of the same. "
            "187. for such other and further relief as the Court deems just "
            "and proper."
        )
        thin_packet = {
            "question": "What relief does the complaint request?",
            "retrieval_hit_count": 1,
            "retrieval_hits": [
                {
                    "result_id": "hit-thin",
                    "page_id": "nyscef-001-page-0099",
                    "nyscef_document_number": 1,
                    "pdf_page": 99,
                    "document_type": "complaint",
                    "excerpt": thin_page[:60],
                    "page_text": thin_page + " " + _SECRET_EXCERPT,
                    "classifications": ["legal_position"],
                }
            ],
        }
        assembled = de.apply_evidence_grounded_relief_synthesis(
            {"proposed_answer": "Draft.", "propositions": [], "audit": {}},
            thin_packet,
        )
        contract = ac.build_synthetic_contract(
            contract_id="contract-q2-diag-fail",
            version="1.0.0",
            benchmark_id="synth-benchmark-q2-diag-fail",
            question_id="Q2",
            object_key="Contracts/synthetic/q2-diag-fail.acceptance_contract.json",
            required_criterion_ids=["q2-no-defense-or-indemnity"],
            criteria=[
                {
                    "id": "q2-no-defense-or-indemnity",
                    "category": "no_defense_or_indemnity",
                    "presence_phrases": ["no defense or indemnity"],
                    "evidence_phrases": ["no duty to defend or indemnify Defendants"],
                    "semantic_required_phrases": [],
                    "semantic_forbidden_phrases": [],
                    "fallback_text": "SECRET_FALLBACK_TEXT_SHOULD_NOT_APPEAR",
                }
            ],
        )
        raw = json.dumps(contract, sort_keys=True).encode("utf-8")
        loaded = ac.load_acceptance_contract_from_bytes(
            raw,
            object_key=contract["object_key"],
            expected_identity=ac.ContractIdentity(
                benchmark_id="synth-benchmark-q2-diag-fail",
                question_id="Q2",
            ),
            expected_content_sha256=contract["content_sha256"],
        )
        self.assertTrue(loaded.ok and loaded.evaluation is not None)
        proposed = assembled["proposed_answer"]
        canonical, validation = mod.finalize_canonical_answer_against_contract(
            proposed, loaded.evaluation
        )
        diag = q2diag.build_q2_production_evidence_diagnostics(
            evidence_packet=thin_packet,
            reasoner_result=assembled,
            proposed_before_canonical=proposed,
            canonical=canonical,
            validation=validation,
        )
        payload = {
            "ok": False,
            "finalized": False,
            "blocker": "Acceptance-contract validation failed; candidate not finalized",
            q2diag.DIAGNOSTIC_RESULT_KEY: diag,
        }
        stdout_blob = json.dumps(payload, indent=2, ensure_ascii=False)
        for forbidden in (
            _SECRET_EXCERPT,
            "SECRET_FALLBACK_TEXT_SHOULD_NOT_APPEAR",
            "alice.example@private.test",
        ):
            self.assertNotIn(forbidden, stdout_blob)
        self.assertIn(q2diag.DIAGNOSTIC_RESULT_KEY, payload)
        acceptance = diag["stages"][3]
        self.assertIn("q2_no_defense_or_indemnity", acceptance)
        self.assertFalse(validation.ok)
        focus = acceptance.get("q2_no_defense_focus_reason_codes") or []
        self.assertTrue(
            focus,
            msg=f"expected focus reason codes on unsupported no-defense; got {acceptance}",
        )
        # Ensure no private strings in any diagnostic string leaf.
        for s in _collect_all_strings(diag):
            self.assertNotIn(_SECRET_EXCERPT, s)
            self.assertNotIn("SECRET_FALLBACK", s)


if __name__ == "__main__":
    unittest.main()
