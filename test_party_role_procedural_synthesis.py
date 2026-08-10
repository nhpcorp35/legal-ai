"""Synthetic regressions for party-role procedural-synthesis validation.

Covers evidence-supported procedural bearing, notice-defendant/no-wrongdoing
reasoning, rescission effect, complaint roadmap preservation, and refusal to
require unsupported inferences. Uses only synthetic party names — no Case-00
identities, gold answers, attorney feedback, or benchmark prose.
"""

from __future__ import annotations

import unittest
from typing import Optional

import engines.drafting_engine as de


def _hit(excerpt: str, **overrides) -> dict:
    base = {
        "result_id": "cret-nyscef-501-page-0001",
        "page_id": "nyscef-501-page-0001",
        "nyscef_document_number": 501,
        "pdf_page": 1,
        "source_filename": "nyscef_doc_no_501_complaint.pdf",
        "document_type": "complaint",
        "excerpt": excerpt,
        "classifications": ["party_identity"],
        "assertion_kind": "party_allegation",
        "score": 10.0,
    }
    base.update(overrides)
    return base


def _packet(excerpt: str, question: Optional[str] = None) -> dict:
    q = question or (
        "Who are the parties and what are their roles in this action?"
    )
    return de.build_evidence_packet(
        q,
        {
            "query": q,
            "results": [_hit(excerpt)],
            "provisional_answer": "PROVISIONAL_SHOULD_NOT_APPEAR",
            "gold_answer": "GOLD_SHOULD_NOT_APPEAR",
            "attorney_feedback": "FEEDBACK_SHOULD_NOT_APPEAR",
        },
    )


def _roster_only_answer(expected) -> str:
    bits = []
    for party in expected:
        bit = f"{party.get('procedural_role')} {party.get('identity')}"
        if party.get("entity_type"):
            bit += f" is a {party['entity_type']}"
        if party.get("residence_or_ppb"):
            bit += f"; {party['residence_or_ppb']}"
        if party.get("pleaded_role_basis"):
            bit += f" ({party['pleaded_role_basis']})"
        bits.append(bit + ".")
    return " ".join(bits)


FULL_SYNTHETIC_COMPLAINT = (
    "PARTIES\n"
    "1. Plaintiff North Quay Logistics LLC is a domestic limited liability "
    "company with its principal place of business in Albany County.\n"
    "2. Defendant Pier Gate Depot Inc. is a domestic corporation with its "
    "principal place of business in Kings County.\n"
    "3. Defendant Harbor Mill Carrier LP is a notice defendant because its "
    "rights may be affected by the requested declaratory relief.\n"
    "4. Defendant Harbor Mill Carrier LP is a limited partnership residing in "
    "Erie County.\n"
    "WHEREFORE Plaintiff seeks a declaration that the policy is void ab initio "
    "and for rescission of the same.\n"
)


class PartyRoleProceduralSynthesisExtractionTests(unittest.TestCase):
    def test_extracts_supported_procedural_and_notice_and_rescission_and_roadmap(self):
        packet = _packet(FULL_SYNTHETIC_COMPLAINT)
        expected = de.extract_party_role_expected_attributes(packet)
        synthesis = de.extract_party_role_expected_synthesis(packet, expected)
        categories = {item["category"] for item in synthesis}
        self.assertIn("procedural_bearing", categories)
        self.assertIn("notice_defendant_explanation", categories)
        self.assertIn("rescission_effect", categories)
        self.assertIn("complaint_roadmap", categories)
        notice = next(
            item
            for item in synthesis
            if item["category"] == "notice_defendant_explanation"
        )
        self.assertTrue(notice.get("require_rights_link"))
        roadmap = next(
            item for item in synthesis if item["category"] == "complaint_roadmap"
        )
        self.assertIn(1, roadmap["paragraph_numbers"])
        self.assertIn(3, roadmap["paragraph_numbers"])
        self.assertIn("parties", roadmap["section_headings"])

    def test_absent_evidence_does_not_invent_synthesis_criteria(self):
        # Build a minimal packet directly so materiality/budget cannot empty it.
        excerpt = (
            "Caption only: North Quay Logistics LLC against Pier Gate Depot Inc. "
            "No entity form, residence, notice basis, or relief is pleaded here."
        )
        packet = {
            "question": (
                "Who are the parties and what are their roles in this action?"
            ),
            "retrieval_hits": [
                {
                    "excerpt": excerpt,
                    "page_id": "nyscef-501-page-0001",
                    "nyscef_document_number": 501,
                    "pdf_page": 1,
                }
            ],
            "retrieval_hit_count": 1,
        }
        expected = de.extract_party_role_expected_attributes(packet)
        synthesis = de.extract_party_role_expected_synthesis(packet, expected)
        categories = {item["category"] for item in synthesis}
        self.assertNotIn("procedural_bearing", categories)
        self.assertNotIn("notice_defendant_explanation", categories)
        self.assertNotIn("rescission_effect", categories)


class PartyRoleProceduralSynthesisValidationTests(unittest.TestCase):
    def test_complete_party_list_alone_fails_when_procedural_connections_supported(self):
        packet = _packet(FULL_SYNTHETIC_COMPLAINT)
        expected = de.extract_party_role_expected_attributes(packet)
        synthesis = de.extract_party_role_expected_synthesis(packet, expected)
        roster = _roster_only_answer(expected)
        missing = de.find_missing_party_role_requirements(
            {"proposed_answer": roster, "propositions": []},
            expected,
            synthesis,
        )
        categories = {item["category"] for item in missing}
        self.assertIn("procedural_bearing", categories)
        self.assertIn("notice_defendant_explanation", categories)
        self.assertIn("rescission_effect", categories)
        self.assertIn("complaint_roadmap", categories)
        # Attribute completeness alone is not enough.
        self.assertEqual(
            de.find_missing_party_role_attributes(
                {"proposed_answer": roster, "propositions": []},
                expected,
            ),
            [],
        )

    def test_supported_procedural_bearing_passes_with_hedged_service_jurisdiction_venue(
        self,
    ):
        excerpt = (
            "PARTIES\n"
            "1. Plaintiff North Quay Logistics LLC is a domestic corporation "
            "with its principal place of business in Albany County.\n"
        )
        packet = _packet(excerpt)
        expected = de.extract_party_role_expected_attributes(packet)
        synthesis = de.extract_party_role_expected_synthesis(packet, expected)
        draft = (
            _roster_only_answer(expected)
            + " As procedural relevance only, these allegations can bear on "
            "service, personal or subject-matter jurisdiction as applicable, "
            "and venue."
            + " The complaint parties roadmap appears at paragraphs 1 through 1."
        )
        missing = de.find_missing_party_role_synthesis(
            {"proposed_answer": draft, "propositions": []},
            synthesis,
        )
        self.assertNotIn(
            "procedural_bearing",
            {item["category"] for item in missing},
        )

    def test_notice_defendant_no_wrongdoing_and_rights_link_required(self):
        excerpt = (
            "PARTIES\n"
            "3. Defendant Harbor Mill Carrier LP is a notice defendant because "
            "its rights may be affected by the requested declaratory relief.\n"
        )
        packet = _packet(excerpt)
        expected = de.extract_party_role_expected_attributes(packet)
        synthesis = de.extract_party_role_expected_synthesis(packet, expected)
        self.assertTrue(expected)
        self.assertIn(
            "notice_defendant_explanation",
            {item["category"] for item in synthesis},
        )
        roster = _roster_only_answer(expected)
        caveat_only = (
            roster
            + " Its interest is not specifically described in the pleading."
        )
        missing_caveat = de.find_missing_party_role_synthesis(
            {"proposed_answer": caveat_only, "propositions": []},
            synthesis,
        )
        self.assertIn(
            "notice_defendant_explanation",
            {item["category"] for item in missing_caveat},
        )

        complete = (
            roster
            + " Notice-defendant joinder reflects the potential effect of "
            "requested declaratory relief and does not itself allege "
            "wrongdoing. Its interest is not specifically described."
        )
        missing_ok = de.find_missing_party_role_synthesis(
            {"proposed_answer": complete, "propositions": []},
            synthesis,
        )
        self.assertNotIn(
            "notice_defendant_explanation",
            {item["category"] for item in missing_ok},
        )

    def test_rescission_effect_connection_required_when_relief_supported(self):
        excerpt = (
            "PARTIES\n"
            "3. Defendant Harbor Mill Carrier LP is a notice defendant.\n"
            "WHEREFORE Plaintiff seeks rescission and a declaration that the "
            "policy is void ab initio.\n"
        )
        packet = _packet(excerpt)
        expected = de.extract_party_role_expected_attributes(packet)
        synthesis = de.extract_party_role_expected_synthesis(packet, expected)
        self.assertIn(
            "rescission_effect",
            {item["category"] for item in synthesis},
        )
        roster = _roster_only_answer(expected) + (
            " Joinder does not itself allege wrongdoing."
        )
        missing = de.find_missing_party_role_synthesis(
            {"proposed_answer": roster, "propositions": []},
            synthesis,
        )
        self.assertIn("rescission_effect", {item["category"] for item in missing})

        connected = roster + (
            " The requested rescission or void ab initio treatment may "
            "negatively affect those asserted rights, as alleged."
        )
        missing_ok = de.find_missing_party_role_synthesis(
            {"proposed_answer": connected, "propositions": []},
            synthesis,
        )
        self.assertNotIn(
            "rescission_effect",
            {item["category"] for item in missing_ok},
        )

    def test_paragraph_roadmap_preserved_and_invented_ranges_rejected(self):
        excerpt = (
            "PARTIES\n"
            "1. Plaintiff North Quay Logistics LLC is a domestic corporation.\n"
            "2. Defendant Pier Gate Depot Inc. is a domestic corporation.\n"
        )
        packet = _packet(excerpt)
        expected = de.extract_party_role_expected_attributes(packet)
        synthesis = de.extract_party_role_expected_synthesis(packet, expected)
        roster = _roster_only_answer(expected)

        missing_no_map = de.find_missing_party_role_synthesis(
            {"proposed_answer": roster, "propositions": []},
            synthesis,
        )
        self.assertIn(
            "complaint_roadmap",
            {item["category"] for item in missing_no_map},
        )

        invented = roster + " See paragraphs 40 through 55 of the complaint."
        missing_invented = de.find_missing_party_role_synthesis(
            {"proposed_answer": invented, "propositions": []},
            synthesis,
        )
        self.assertIn(
            "complaint_roadmap",
            {item["category"] for item in missing_invented},
        )

        preserved = roster + (
            " The complaint parties roadmap appears in the PARTIES section at "
            "paragraphs 1 through 2."
        )
        missing_ok = de.find_missing_party_role_synthesis(
            {"proposed_answer": preserved, "propositions": []},
            synthesis,
        )
        self.assertNotIn(
            "complaint_roadmap",
            {item["category"] for item in missing_ok},
        )


class PartyRoleProceduralSynthesisRepairPathTests(unittest.TestCase):
    def test_roster_only_triggers_repair_then_passes_with_synthesis(self):
        question = "Who are the parties and what are their roles in this action?"
        retrieval = {
            "query": question,
            "results": [_hit(FULL_SYNTHETIC_COMPLAINT)],
            "provisional_answer": "PROVISIONAL_SHOULD_NOT_APPEAR",
            "gold_answer": "GOLD_SHOULD_NOT_APPEAR",
            "attorney_feedback": "FEEDBACK_SHOULD_NOT_APPEAR",
        }
        calls = []

        def _model(_system, user_prompt):
            calls.append(user_prompt)
            packet = de.build_evidence_packet(question, retrieval)
            expected = de.extract_party_role_expected_attributes(packet)
            roster = _roster_only_answer(expected)
            hit = packet["retrieval_hits"][0]
            if len(calls) == 1:
                answer = roster
            else:
                answer = (
                    roster
                    + " The complaint parties roadmap appears in the PARTIES "
                    "section at paragraphs 1 through 4."
                    + " As procedural relevance only, entity form and residence "
                    "or principal-place allegations can bear on service, "
                    "personal or subject-matter jurisdiction as applicable, "
                    "and venue."
                    + " Notice-defendant joinder reflects the potential effect "
                    "of requested declaratory relief and does not itself allege "
                    "wrongdoing."
                    + " The requested rescission or void ab initio treatment may "
                    "negatively affect those asserted rights, as alleged."
                )
            return {
                "proposed_answer": answer,
                "propositions": [
                    {
                        "proposition_id": "P1",
                        "text": answer,
                        "classification": "party_allegation",
                        "nyscef_document_number": hit["nyscef_document_number"],
                        "page_id": hit["page_id"],
                        "pdf_page": hit["pdf_page"],
                        "source_excerpt": (
                            "Plaintiff North Quay Logistics LLC is a domestic "
                            "limited liability company"
                        ),
                        "confidence": 0.9,
                        "rationale": "Synthetic party roster.",
                        "polarity": "supporting",
                    }
                ],
                "supporting_evidence": [],
                "contrary_evidence": [],
                "unresolved_questions": [],
                "documents_pages_reviewed": [],
                "confidence": 0.9,
                "attorney_review": {
                    "requires_attorney_review": True,
                    "review_notes": "Synthetic draft.",
                    "legal_conclusions_labeled": True,
                    "coverage_conclusion": None,
                },
                "review_scope": {
                    "completeness": "not_established",
                    "qualification": "Limited to retrieved pleading.",
                },
            }

        result = de.answer_attorney_record_question(
            question,
            retrieval,
            model_call=_model,
        )
        self.assertEqual(result["status"], de.STATUS_READY)
        self.assertEqual(len(calls), 2)
        self.assertTrue(result["audit"].get("party_role_repair_attempted"))
        repair = calls[1].lower()
        self.assertIn("procedural_bearing", repair)
        self.assertIn("notice_defendant_explanation", repair)
        self.assertIn("rescission_effect", repair)
        self.assertIn("complaint_roadmap", repair)
        self.assertNotIn("provisional_should_not_appear", repair)
        self.assertNotIn("gold_should_not_appear", repair)
        self.assertNotIn("feedback_should_not_appear", repair)
        self.assertNotIn("attorney_feedback", repair)
        lowered = result["proposed_answer"].lower()
        self.assertIn("can bear on service", lowered)
        self.assertIn("does not itself allege wrongdoing", lowered)
        self.assertIn("void ab initio", lowered)

    def test_contamination_refs_absent_from_prompts_when_synthesis_required(self):
        question = "Identify the parties and their procedural roles."
        retrieval = {
            "query": question,
            "results": [_hit(FULL_SYNTHETIC_COMPLAINT)],
            "provisional_answer": "PROVISIONAL_SHOULD_NOT_APPEAR",
            "gold_answer": "GOLD_SHOULD_NOT_APPEAR",
            "attorney_feedback": "FEEDBACK_SHOULD_NOT_APPEAR",
        }

        def _model(_system, user_prompt):
            lowered = user_prompt.lower()
            self.assertNotIn("provisional_should_not_appear", lowered)
            self.assertNotIn("gold_should_not_appear", lowered)
            self.assertNotIn("feedback_should_not_appear", lowered)
            packet = de.build_evidence_packet(question, retrieval)
            expected = de.extract_party_role_expected_attributes(packet)
            synthesis = de.extract_party_role_expected_synthesis(packet, expected)
            answer = _roster_only_answer(expected)
            categories = {item.get("category") for item in synthesis}
            if "complaint_roadmap" in categories:
                answer += (
                    " The complaint parties roadmap appears in the PARTIES "
                    "section at paragraphs 1 through 4."
                )
            if "procedural_bearing" in categories:
                answer += (
                    " As procedural relevance only, those allegations can bear "
                    "on service, personal or subject-matter jurisdiction as "
                    "applicable, and venue."
                )
            if "notice_defendant_explanation" in categories:
                answer += (
                    " Notice-defendant joinder reflects the potential effect of "
                    "requested declaratory relief and does not itself allege "
                    "wrongdoing."
                )
            if "rescission_effect" in categories:
                answer += (
                    " The requested rescission or void ab initio treatment may "
                    "negatively affect those asserted rights, as alleged."
                )
            hit = packet["retrieval_hits"][0]
            return {
                "proposed_answer": answer,
                "propositions": [
                    {
                        "proposition_id": "P1",
                        "text": answer,
                        "classification": "party_allegation",
                        "nyscef_document_number": hit["nyscef_document_number"],
                        "page_id": hit["page_id"],
                        "pdf_page": hit["pdf_page"],
                        "source_excerpt": (
                            "Plaintiff North Quay Logistics LLC is a domestic "
                            "limited liability company"
                        ),
                        "confidence": 0.9,
                        "rationale": "Synthetic party roster.",
                        "polarity": "supporting",
                    }
                ],
                "supporting_evidence": [],
                "contrary_evidence": [],
                "unresolved_questions": [],
                "documents_pages_reviewed": [],
                "confidence": 0.9,
                "attorney_review": {"requires_attorney_review": True},
                "review_scope": {"completeness": "not_established"},
            }

        result = de.answer_attorney_record_question(
            question,
            retrieval,
            model_call=_model,
        )
        self.assertEqual(result["status"], de.STATUS_READY)
        self.assertFalse(result["audit"].get("party_role_repair_attempted"))


if __name__ == "__main__":
    unittest.main()
