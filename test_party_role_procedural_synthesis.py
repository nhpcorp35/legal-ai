"""Synthetic regressions for party-role procedural-synthesis validation.

Covers evidence-supported procedural bearing, notice-defendant/no-wrongdoing
reasoning, rescission effect, complaint roadmap preservation, targeted
synthesis-patch repair (compliant, blocked, oscillation-preserving), response
schema rejection, merge placement, and refusal to require unsupported
inferences. Uses only synthetic party names — no Case-00 identities, gold
answers, attorney feedback, or benchmark prose.
"""

from __future__ import annotations

import json
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


def _synthetic_payload(answer: str, hit: dict) -> dict:
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


def _complete_synthesis_answer(expected, synthesis) -> str:
    answer = _roster_only_answer(expected)
    categories = {item.get("category") for item in synthesis}
    if "complaint_roadmap" in categories:
        roadmap = next(
            item for item in synthesis if item["category"] == "complaint_roadmap"
        )
        nums = list(roadmap.get("paragraph_numbers") or [])
        headings = list(roadmap.get("section_headings") or [])
        if nums:
            answer += (
                f" The complaint parties roadmap appears at paragraphs "
                f"{nums[0]} through {nums[-1]}."
            )
        if headings:
            answer += f" Section organization includes {headings[0]}."
    if "procedural_bearing" in categories:
        answer += (
            " As procedural relevance only, pleaded identity/role, entity form, "
            "and residence or principal place of business can bear on service, "
            "jurisdiction as applicable, and venue; they are not conclusively "
            "established by those allegations."
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
    return answer


def _patch_paragraphs_for_categories(categories, synthesis) -> dict:
    """Build valid patch section text for the requested synthesis categories."""
    wanted = set(categories)
    patch = {}
    if "complaint_roadmap" in wanted:
        roadmap = next(
            item for item in synthesis if item["category"] == "complaint_roadmap"
        )
        nums = list(roadmap.get("paragraph_numbers") or [])
        headings = list(roadmap.get("section_headings") or [])
        text = ""
        if nums:
            text = (
                f"The complaint parties roadmap appears at paragraphs "
                f"{nums[0]} through {nums[-1]}."
            )
        if headings:
            text = (
                f"{text} Section organization includes {headings[0]}."
            ).strip()
        patch["complaint_roadmap"] = text
    if "procedural_bearing" in wanted:
        patch["procedural_bearing"] = (
            "As procedural relevance only, pleaded identity/role, entity form, "
            "and residence or principal place of business can bear on service, "
            "jurisdiction as applicable, and venue; they are not conclusively "
            "established by those allegations."
        )
    if "notice_defendant_explanation" in wanted:
        patch["notice_defendant_explanation"] = (
            "Notice-defendant joinder reflects the potential effect of "
            "requested declaratory relief and does not itself allege "
            "wrongdoing."
        )
    if "rescission_effect" in wanted:
        patch["rescission_effect"] = (
            "The requested rescission or void ab initio treatment may "
            "negatively affect those asserted rights, as alleged."
        )
    return patch


def _notice_and_rescission_prefix(expected) -> str:
    return (
        _roster_only_answer(expected)
        + " Notice-defendant joinder reflects the potential effect of "
        "requested declaratory relief and does not itself allege "
        "wrongdoing."
        + " The requested rescission or void ab initio treatment may "
        "negatively affect those asserted rights, as alleged."
    )


def _procedural_and_roadmap_prefix(expected, synthesis) -> str:
    answer = _roster_only_answer(expected)
    roadmap = next(
        item for item in synthesis if item["category"] == "complaint_roadmap"
    )
    nums = list(roadmap.get("paragraph_numbers") or [])
    answer += (
        f" The complaint parties roadmap appears at paragraphs "
        f"{nums[0]} through {nums[-1]}."
    )
    answer += (
        " As procedural relevance only, pleaded identity/role, entity form, "
        "and residence or principal place of business can bear on service, "
        "jurisdiction as applicable, and venue; they are not conclusively "
        "established by those allegations."
    )
    return answer


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

NO_ROADMAP_SYNTHETIC = (
    "North Quay Logistics LLC against Pier Gate Depot Inc. "
    "Plaintiff North Quay Logistics LLC is a domestic limited liability "
    "company with its principal place of business in Albany County. "
    "Defendant Pier Gate Depot Inc. is a domestic corporation with its "
    "principal place of business in Kings County."
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
        self.assertEqual(
            roadmap.get("exact_paragraph_range"),
            {
                "start": min(roadmap["paragraph_numbers"]),
                "end": max(roadmap["paragraph_numbers"]),
            },
        )

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
        self.assertNotIn("complaint_roadmap", categories)

    def test_no_roadmap_evidence_does_not_require_roadmap(self):
        packet = {
            "question": (
                "Who are the parties and what are their roles in this action?"
            ),
            "retrieval_hits": [
                {
                    "excerpt": NO_ROADMAP_SYNTHETIC,
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
        self.assertNotIn("complaint_roadmap", categories)
        self.assertIn("procedural_bearing", categories)
        roster = _roster_only_answer(expected) + (
            " As procedural relevance only, pleaded identity/role, entity form, "
            "and residence or principal place of business can bear on service, "
            "jurisdiction as applicable, and venue."
        )
        missing = de.find_missing_party_role_synthesis(
            {"proposed_answer": roster, "propositions": []},
            synthesis,
        )
        self.assertNotIn(
            "complaint_roadmap",
            {item["category"] for item in missing},
        )


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
        bearing = next(
            item for item in missing if item["category"] == "procedural_bearing"
        )
        self.assertIn("evidence_facts", bearing)
        self.assertTrue(
            bearing["evidence_facts"][
                "parties_with_identity_role_entity_and_residence_or_ppb"
            ]
        )
        roadmap = next(
            item for item in missing if item["category"] == "complaint_roadmap"
        )
        self.assertIn(1, roadmap["paragraph_numbers"])
        self.assertIn("parties", roadmap["section_headings"])
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

    def test_exact_roadmap_preservation_and_invented_ranges_rejected(self):
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


class PartyRoleSynthesisPatchUnitTests(unittest.TestCase):
    def test_strict_patch_schema_accepts_exact_allowed_categories(self):
        packet = _packet(FULL_SYNTHETIC_COMPLAINT)
        synthesis = de.extract_party_role_expected_synthesis(packet)
        allowed = ["procedural_bearing", "complaint_roadmap"]
        sections = _patch_paragraphs_for_categories(allowed, synthesis)
        parsed = de.parse_party_role_synthesis_patch(
            {"synthesis_patch": sections},
            allowed_categories=allowed,
            original_answer="Roster only.",
            expected_synthesis=synthesis,
        )
        self.assertEqual(set(parsed.keys()), set(allowed))

    def test_unknown_category_rejection(self):
        packet = _packet(FULL_SYNTHETIC_COMPLAINT)
        synthesis = de.extract_party_role_expected_synthesis(packet)
        allowed = ["procedural_bearing"]
        sections = _patch_paragraphs_for_categories(allowed, synthesis)
        sections["not_a_real_category"] = "Invented category text."
        parsed = de.parse_party_role_synthesis_patch(
            {"synthesis_patch": sections},
            allowed_categories=allowed,
            original_answer="Roster only.",
            expected_synthesis=synthesis,
        )
        self.assertIsNone(parsed)

    def test_commentary_and_full_answer_rewrite_rejected(self):
        packet = _packet(FULL_SYNTHETIC_COMPLAINT)
        synthesis = de.extract_party_role_expected_synthesis(packet)
        allowed = ["procedural_bearing"]
        sections = _patch_paragraphs_for_categories(allowed, synthesis)
        wrapped = (
            "Here is commentary that must be rejected.\n"
            + json.dumps({"synthesis_patch": sections})
        )
        self.assertIsNone(
            de.parse_party_role_synthesis_patch(
                wrapped,
                allowed_categories=allowed,
                original_answer="Roster only.",
                expected_synthesis=synthesis,
            )
        )
        self.assertIsNone(
            de.parse_party_role_synthesis_patch(
                {
                    "proposed_answer": "full rewrite",
                    "propositions": [],
                    "synthesis_patch": sections,
                },
                allowed_categories=allowed,
                original_answer="Roster only.",
                expected_synthesis=synthesis,
            )
        )

    def test_duplicate_roster_and_duplicate_paragraph_prevention(self):
        packet = _packet(FULL_SYNTHETIC_COMPLAINT)
        expected = de.extract_party_role_expected_attributes(packet)
        synthesis = de.extract_party_role_expected_synthesis(packet, expected)
        roster = _roster_only_answer(expected)
        allowed = ["procedural_bearing"]
        self.assertIsNone(
            de.parse_party_role_synthesis_patch(
                {"synthesis_patch": {"procedural_bearing": roster}},
                allowed_categories=allowed,
                original_answer=roster,
                expected_synthesis=synthesis,
            )
        )
        sections = _patch_paragraphs_for_categories(allowed, synthesis)
        draft = {
            "proposed_answer": roster + " " + sections["procedural_bearing"],
            "propositions": [
                {
                    "proposition_id": "P1",
                    "text": roster + " " + sections["procedural_bearing"],
                }
            ],
        }
        merged = de.merge_party_role_synthesis_patch(draft, sections)
        self.assertIsNotNone(merged)
        # Already-present paragraph is not duplicated.
        self.assertEqual(
            merged["proposed_answer"].lower().count("can bear on service"),
            1,
        )

    def test_merge_placement_preserves_roster_and_appends_synthesis(self):
        packet = _packet(FULL_SYNTHETIC_COMPLAINT)
        expected = de.extract_party_role_expected_attributes(packet)
        synthesis = de.extract_party_role_expected_synthesis(packet, expected)
        roster = _roster_only_answer(expected)
        notice = (
            "Notice-defendant joinder reflects the potential effect of "
            "requested declaratory relief and does not itself allege "
            "wrongdoing."
        )
        original = f"{roster} {notice}"
        draft = {
            "proposed_answer": original,
            "propositions": [{"proposition_id": "P1", "text": original}],
        }
        sections = _patch_paragraphs_for_categories(
            ["procedural_bearing", "complaint_roadmap"],
            synthesis,
        )
        merged = de.merge_party_role_synthesis_patch(draft, sections)
        self.assertIsNotNone(merged)
        answer = merged["proposed_answer"]
        self.assertTrue(answer.startswith(roster))
        self.assertIn(notice, answer)
        self.assertIn("can bear on service", answer.lower())
        self.assertIn("paragraphs", answer.lower())
        self.assertEqual(merged["propositions"][0]["text"], answer)


class PartyRoleProceduralSynthesisRepairPathTests(unittest.TestCase):
    def test_roster_only_triggers_patch_repair_then_passes_with_synthesis(self):
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
            synthesis = de.extract_party_role_expected_synthesis(packet, expected)
            hit = packet["retrieval_hits"][0]
            if len(calls) == 1:
                return _synthetic_payload(_roster_only_answer(expected), hit)
            missing = de.find_missing_party_role_synthesis(
                {"proposed_answer": _roster_only_answer(expected)},
                synthesis,
            )
            categories = [item["category"] for item in missing]
            return {
                "synthesis_patch": _patch_paragraphs_for_categories(
                    categories, synthesis
                )
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
        self.assertIn("synthesis patch", repair)
        self.assertIn("exact allowed missing categories", repair)
        self.assertIn("evidence_facts", repair)
        self.assertIn("procedural_bearing", repair)
        self.assertIn("notice_defendant_explanation", repair)
        self.assertIn("rescission_effect", repair)
        self.assertIn("complaint_roadmap", repair)
        self.assertIn("paragraph_numbers", repair)
        self.assertIn("can bear on service", repair)
        self.assertNotIn("complete revised answer", repair)
        self.assertNotIn("current draft", repair)
        self.assertNotIn("provisional_should_not_appear", repair)
        self.assertNotIn("gold_should_not_appear", repair)
        self.assertNotIn("feedback_should_not_appear", repair)
        self.assertNotIn("attorney_feedback", repair)
        lowered = result["proposed_answer"].lower()
        self.assertIn("can bear on service", lowered)
        self.assertIn("does not itself allege wrongdoing", lowered)
        self.assertIn("void ab initio", lowered)
        self.assertIn("paragraphs 1 through 4", lowered)

    def test_oscillation_patch_procedural_roadmap_preserves_notice(self):
        """Live oscillation shape: procedural+roadmap repair must keep notice."""
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
            synthesis = de.extract_party_role_expected_synthesis(packet, expected)
            hit = packet["retrieval_hits"][0]
            if len(calls) == 1:
                return _synthetic_payload(
                    _notice_and_rescission_prefix(expected),
                    hit,
                )
            # Provider returns only the missing categories — no notice rewrite.
            return {
                "synthesis_patch": _patch_paragraphs_for_categories(
                    ["procedural_bearing", "complaint_roadmap"],
                    synthesis,
                )
            }

        result = de.answer_attorney_record_question(
            question,
            retrieval,
            model_call=_model,
        )
        self.assertEqual(result["status"], de.STATUS_READY)
        self.assertEqual(len(calls), 2)
        lowered = result["proposed_answer"].lower()
        self.assertIn("does not itself allege wrongdoing", lowered)
        self.assertIn("negatively affect", lowered)
        self.assertIn("can bear on service", lowered)
        self.assertIn("paragraphs 1 through 4", lowered)
        # Original notice text preserved (not dropped by rewrite).
        self.assertIn(
            "notice-defendant joinder reflects the potential effect",
            lowered,
        )

    def test_oscillation_patch_notice_preserves_procedural_roadmap(self):
        """Inverse oscillation: notice repair must keep procedural+roadmap."""
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
            synthesis = de.extract_party_role_expected_synthesis(packet, expected)
            hit = packet["retrieval_hits"][0]
            if len(calls) == 1:
                prefix = _procedural_and_roadmap_prefix(expected, synthesis)
                # Missing notice + rescission only.
                return _synthetic_payload(prefix, hit)
            return {
                "synthesis_patch": _patch_paragraphs_for_categories(
                    ["notice_defendant_explanation", "rescission_effect"],
                    synthesis,
                )
            }

        result = de.answer_attorney_record_question(
            question,
            retrieval,
            model_call=_model,
        )
        self.assertEqual(result["status"], de.STATUS_READY)
        self.assertEqual(len(calls), 2)
        lowered = result["proposed_answer"].lower()
        self.assertIn("can bear on service", lowered)
        self.assertIn("paragraphs 1 through 4", lowered)
        self.assertIn("does not itself allege wrongdoing", lowered)
        self.assertIn("negatively affect", lowered)

    def test_noncompliant_patch_remains_blocked_without_second_retry(self):
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
            hit = packet["retrieval_hits"][0]
            if len(calls) == 1:
                return _synthetic_payload(
                    _notice_and_rescission_prefix(expected),
                    hit,
                )
            # Incomplete patch: omits complaint_roadmap (failure shape).
            return {
                "synthesis_patch": {
                    "procedural_bearing": (
                        "As procedural relevance only, pleaded identity/role, "
                        "entity form, and residence or principal place of "
                        "business can bear on service, jurisdiction as "
                        "applicable, and venue."
                    )
                }
            }

        result = de.answer_attorney_record_question(
            question,
            retrieval,
            model_call=_model,
        )
        self.assertEqual(result["status"], de.STATUS_NOT_READY)
        self.assertEqual(len(calls), 2)
        self.assertTrue(result["audit"].get("party_role_completeness_failed"))
        self.assertTrue(result["audit"].get("party_role_repair_attempted"))
        self.assertEqual(result["audit"].get("party_role_provider_calls"), 2)

    def test_failed_patch_blocking_and_one_call_maximum(self):
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
            hit = packet["retrieval_hits"][0]
            if len(calls) == 1:
                return _synthetic_payload(_roster_only_answer(expected), hit)
            # Full-answer rewrite attempt must be rejected (fail closed).
            return _synthetic_payload(
                _complete_synthesis_answer(
                    expected,
                    de.extract_party_role_expected_synthesis(packet, expected),
                ),
                hit,
            )

        result = de.answer_attorney_record_question(
            question,
            retrieval,
            model_call=_model,
        )
        self.assertEqual(result["status"], de.STATUS_NOT_READY)
        self.assertEqual(len(calls), 2)
        self.assertTrue(result["audit"].get("party_role_completeness_failed"))
        self.assertEqual(result["audit"].get("party_role_provider_calls"), 2)

    def test_patch_prompt_is_evidence_grounded_and_omits_draft_rewrite(self):
        question = "Who are the parties and what are their roles in this action?"
        packet = _packet(FULL_SYNTHETIC_COMPLAINT)
        expected = de.extract_party_role_expected_attributes(packet)
        synthesis = de.extract_party_role_expected_synthesis(packet, expected)
        roster = _notice_and_rescission_prefix(expected)
        missing = de.find_missing_party_role_requirements(
            {"proposed_answer": roster, "propositions": []},
            expected,
            synthesis,
        )
        _attrs, synthesis_gaps = de.partition_party_role_missing_requirements(missing)
        prompt = de.build_party_role_synthesis_patch_prompt(
            question=question,
            missing_synthesis=synthesis_gaps,
        )
        lowered = prompt.lower()
        self.assertIn("exact allowed missing categories", lowered)
        self.assertIn("procedural_bearing", lowered)
        self.assertIn("complaint_roadmap", lowered)
        self.assertIn("evidence_facts", lowered)
        self.assertIn("paragraph_numbers", lowered)
        self.assertIn("synthesis_patch", lowered)
        self.assertNotIn("complete revised answer", lowered)
        self.assertNotIn("current draft", lowered)
        self.assertRegex(prompt, r'"paragraph_numbers":\s*\[[^\]]*\d')

    def test_no_roadmap_behavior_excludes_roadmap_from_patch_prompt(self):
        question = "Who are the parties and what are their roles in this action?"
        retrieval = {
            "query": question,
            "results": [_hit(NO_ROADMAP_SYNTHETIC)],
            "provisional_answer": "PROVISIONAL_SHOULD_NOT_APPEAR",
            "gold_answer": "GOLD_SHOULD_NOT_APPEAR",
            "attorney_feedback": "FEEDBACK_SHOULD_NOT_APPEAR",
        }
        calls = []

        def _model(_system, user_prompt):
            calls.append(user_prompt)
            packet = de.build_evidence_packet(question, retrieval)
            expected = de.extract_party_role_expected_attributes(packet)
            synthesis = de.extract_party_role_expected_synthesis(packet, expected)
            hit = packet["retrieval_hits"][0]
            if len(calls) == 1:
                return _synthetic_payload(_roster_only_answer(expected), hit)
            missing = de.find_missing_party_role_synthesis(
                {"proposed_answer": _roster_only_answer(expected)},
                synthesis,
            )
            categories = [item["category"] for item in missing]
            self.assertNotIn("complaint_roadmap", categories)
            return {
                "synthesis_patch": _patch_paragraphs_for_categories(
                    categories, synthesis
                )
            }

        result = de.answer_attorney_record_question(
            question,
            retrieval,
            model_call=_model,
        )
        self.assertEqual(result["status"], de.STATUS_READY)
        self.assertEqual(len(calls), 2)
        repair = calls[1].lower()
        self.assertNotIn("complaint_roadmap", repair)
        self.assertIn("procedural_bearing", repair)
        self.assertNotIn("paragraphs ", result["proposed_answer"].lower())

    def test_full_revalidation_after_merge_fails_closed_if_still_incomplete(self):
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
            synthesis = de.extract_party_role_expected_synthesis(packet, expected)
            hit = packet["retrieval_hits"][0]
            if len(calls) == 1:
                return _synthetic_payload(_roster_only_answer(expected), hit)
            # Valid schema covering only a subset of required categories is
            # rejected at parse (exact key set), failing closed.
            return {
                "synthesis_patch": _patch_paragraphs_for_categories(
                    ["procedural_bearing"],
                    synthesis,
                )
            }

        result = de.answer_attorney_record_question(
            question,
            retrieval,
            model_call=_model,
        )
        self.assertEqual(result["status"], de.STATUS_NOT_READY)
        self.assertEqual(len(calls), 2)
        self.assertTrue(result["audit"].get("party_role_completeness_failed"))

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
            self.assertNotIn("attorney_feedback", lowered)
            packet = de.build_evidence_packet(question, retrieval)
            expected = de.extract_party_role_expected_attributes(packet)
            synthesis = de.extract_party_role_expected_synthesis(packet, expected)
            hit = packet["retrieval_hits"][0]
            return _synthetic_payload(
                _complete_synthesis_answer(expected, synthesis),
                hit,
            )

        result = de.answer_attorney_record_question(
            question,
            retrieval,
            model_call=_model,
        )
        self.assertEqual(result["status"], de.STATUS_READY)
        self.assertFalse(result["audit"].get("party_role_repair_attempted"))


if __name__ == "__main__":
    unittest.main()
