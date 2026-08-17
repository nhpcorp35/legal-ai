"""Synthetic regressions for party-role procedural-synthesis validation.

Covers evidence-supported procedural bearing, notice-defendant/no-wrongdoing
reasoning, rescission effect, complaint roadmap preservation, targeted
synthesis-patch repair (compliant, blocked, oscillation-preserving), response
schema rejection (omit/duplicate/unknown/empty with audit reasons), merge
preservation, semantic procedural-bearing acceptance/rejection (including
merits-determination rejection and partial doctrine omission), deterministic
procedural_bearing fallback after repair omission, category lifecycle
diagnostics, and refusal to require unsupported inferences. Uses only
synthetic party names — no Case-00 identities, gold answers, attorney feedback,
or benchmark prose.
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
            + " As procedural relevance only, pleaded identity/role, entity form, "
            "and residence or principal place of business can bear on "
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


class PartyRoleProceduralBearingSemanticsTests(unittest.TestCase):
    """Deterministic semantic acceptance/rejection for procedural_bearing."""

    def test_plausible_provider_phrasings_accepted(self):
        samples = [
            (
                "Pleaded identity/role, entity form, and location allegations "
                "can bear upon service, jurisdiction as applicable, and venue."
            ),
            (
                "Party identity and role, together with entity form and "
                "residence, may bear on service, jurisdiction as applicable, "
                "and venue; they are not conclusively established."
            ),
            (
                "As procedural relevance only, pleaded identity and procedural "
                "role, entity type, and principal place of business are "
                "relevant to service, jurisdiction as applicable, and venue."
            ),
            (
                "Identity/role plus entity-form and residence allegations can "
                "inform service, jurisdiction as applicable, and venue without "
                "claiming those doctrines are established."
            ),
        ]
        for text in samples:
            self.assertTrue(
                de._draft_has_procedural_bearing(de.normalize_citation_text(text)),
                msg=f"expected accept: {text}",
            )

    def test_conclusory_doctrine_claims_rejected(self):
        samples = [
            (
                "Pleaded identity/role, entity form, and residence can bear on "
                "service, jurisdiction as applicable, and venue, and those "
                "doctrines are established."
            ),
            (
                "Identity/role, entity form, and location establish service, "
                "jurisdiction, and venue."
            ),
            (
                "Party identity and role, entity form, and residence "
                "conclusively establish jurisdiction and venue as well as "
                "service."
            ),
        ]
        for text in samples:
            self.assertFalse(
                de._draft_has_procedural_bearing(de.normalize_citation_text(text)),
                msg=f"expected reject: {text}",
            )

    def test_nonconclusive_hedging_accepted(self):
        text = (
            "Pleaded identity/role, entity form, and residence or principal "
            "place of business can bear on service, jurisdiction as "
            "applicable, and venue; they do not themselves establish those "
            "doctrines."
        )
        self.assertTrue(
            de._draft_has_procedural_bearing(de.normalize_citation_text(text))
        )

    def test_ungrounded_or_incomplete_bearing_rejected(self):
        samples = [
            # Missing identity/role grounding.
            (
                "Entity form and residence can bear on service, jurisdiction "
                "as applicable, and venue."
            ),
            # Missing venue.
            (
                "Identity/role, entity form, and location can bear on service "
                "and jurisdiction as applicable."
            ),
            # No hedge.
            (
                "Identity/role, entity form, and location relate to service, "
                "jurisdiction, and venue."
            ),
            # Partial doctrine omission: missing jurisdiction.
            (
                "Pleaded identity/role, entity form, and residence can bear on "
                "service and venue."
            ),
            # Partial doctrine omission: missing service.
            (
                "Pleaded identity/role, entity form, and residence can bear on "
                "jurisdiction as applicable and venue."
            ),
        ]
        for text in samples:
            self.assertFalse(
                de._draft_has_procedural_bearing(de.normalize_citation_text(text)),
                msg=f"expected reject: {text}",
            )

    def test_merits_determination_language_rejected(self):
        samples = [
            (
                "Pleaded identity/role, entity form, and residence can bear on "
                "service, jurisdiction as applicable, and venue as a merits "
                "determination."
            ),
            (
                "Identity/role, entity form, and location can bear on service, "
                "jurisdiction as applicable, and venue and establish the merits."
            ),
            (
                "Party identity and role, entity form, and residence can bear "
                "on service, jurisdiction as applicable, and venue; this is a "
                "merits conclusion."
            ),
        ]
        for text in samples:
            self.assertFalse(
                de._draft_has_procedural_bearing(de.normalize_citation_text(text)),
                msg=f"expected reject merits claim: {text}",
            )

    def test_deterministic_paragraph_is_stable_and_valid(self):
        first = de.deterministic_party_role_procedural_bearing_paragraph()
        second = de.deterministic_party_role_procedural_bearing_paragraph()
        self.assertEqual(first, second)
        self.assertTrue(
            de._draft_has_procedural_bearing(de.normalize_citation_text(first))
        )
        # Must stay generic — no case-locked identities or question text.
        lowered = first.lower()
        self.assertNotIn("north quay", lowered)
        self.assertNotIn("triborough", lowered)
        self.assertIn("service", lowered)
        self.assertIn("jurisdiction as applicable", lowered)
        self.assertIn("venue", lowered)


class PartyRoleDeterministicProceduralBearingFallbackTests(unittest.TestCase):
    """Initial success, model repair, and deterministic PB fallback coverage."""

    def test_initial_success_without_repair_when_bearing_present(self):
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
        self.assertEqual(len(calls), 1)
        self.assertFalse(result["audit"].get("party_role_repair_attempted"))
        self.assertFalse(
            result["audit"].get("party_role_deterministic_procedural_bearing_fallback")
        )
        self.assertIn("can bear on service", result["proposed_answer"].lower())

    def test_model_repair_success_without_deterministic_fallback(self):
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
        self.assertTrue(result["audit"].get("party_role_repair_attempted"))
        self.assertFalse(
            result["audit"].get("party_role_deterministic_procedural_bearing_fallback")
        )
        lowered = result["proposed_answer"].lower()
        self.assertIn("can bear on service", lowered)
        self.assertIn("does not itself allege wrongdoing", lowered)

    def test_deterministic_fallback_after_repair_omission_of_procedural_bearing(self):
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
                # Satisfied: roster + notice + rescission + roadmap; missing PB.
                prefix = _notice_and_rescission_prefix(expected)
                roadmap = next(
                    item
                    for item in synthesis
                    if item["category"] == "complaint_roadmap"
                )
                nums = list(roadmap.get("paragraph_numbers") or [])
                prefix += (
                    f" The complaint parties roadmap appears at paragraphs "
                    f"{nums[0]} through {nums[-1]}."
                )
                return _synthetic_payload(prefix, hit)
            # Repair omits procedural_bearing entirely.
            return {"synthesis_patch": {}}

        result = de.answer_attorney_record_question(
            question,
            retrieval,
            model_call=_model,
        )
        self.assertEqual(result["status"], de.STATUS_READY)
        self.assertEqual(len(calls), 2)
        self.assertTrue(result["audit"].get("party_role_repair_attempted"))
        self.assertTrue(
            result["audit"].get("party_role_deterministic_procedural_bearing_fallback")
        )
        lowered = result["proposed_answer"].lower()
        self.assertIn("can bear on service", lowered)
        self.assertIn("jurisdiction as applicable", lowered)
        self.assertIn("venue", lowered)
        # Preservation of already-satisfied categories.
        self.assertIn("does not itself allege wrongdoing", lowered)
        self.assertIn("negatively affect", lowered)
        self.assertIn("paragraphs 1 through 4", lowered)
        det = de.deterministic_party_role_procedural_bearing_paragraph().lower()
        self.assertIn(det, lowered)

    def test_deterministic_fallback_replaces_conclusory_bearing_preserves_others(self):
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
            roadmap = _patch_paragraphs_for_categories(
                ["complaint_roadmap"], synthesis
            )
            return {
                "synthesis_patch": {
                    "complaint_roadmap": roadmap["complaint_roadmap"],
                    "procedural_bearing": (
                        "Pleaded identity/role, entity form, and residence "
                        "establish service, jurisdiction, and venue on the merits."
                    ),
                }
            }

        result = de.answer_attorney_record_question(
            question,
            retrieval,
            model_call=_model,
        )
        self.assertEqual(result["status"], de.STATUS_READY)
        self.assertEqual(len(calls), 2)
        self.assertTrue(
            result["audit"].get("party_role_deterministic_procedural_bearing_fallback")
        )
        lowered = result["proposed_answer"].lower()
        self.assertIn("can bear on service", lowered)
        self.assertNotIn("establish service, jurisdiction, and venue", lowered)
        self.assertIn("does not itself allege wrongdoing", lowered)
        self.assertIn("paragraphs 1 through 4", lowered)

    def test_equivalent_wording_accepted_without_fallback(self):
        text = (
            "Party identity and role, together with entity form and "
            "residence, may bear on service, jurisdiction as applicable, "
            "and venue; they are not conclusively established."
        )
        self.assertTrue(
            de._draft_has_procedural_bearing(de.normalize_citation_text(text))
        )

    def test_resolve_patch_fills_only_missing_procedural_bearing(self):
        packet = _packet(FULL_SYNTHETIC_COMPLAINT)
        expected = de.extract_party_role_expected_attributes(packet)
        synthesis = de.extract_party_role_expected_synthesis(packet, expected)
        roster = _notice_and_rescission_prefix(expected)
        roadmap = _patch_paragraphs_for_categories(["complaint_roadmap"], synthesis)
        audit = {}
        parsed = de.resolve_party_role_synthesis_patch(
            {
                "synthesis_patch": {
                    "complaint_roadmap": roadmap["complaint_roadmap"],
                    # procedural_bearing omitted
                }
            },
            allowed_categories=["procedural_bearing", "complaint_roadmap"],
            original_answer=roster,
            expected_synthesis=synthesis,
            audit_out=audit,
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(
            set(parsed.keys()), {"procedural_bearing", "complaint_roadmap"}
        )
        self.assertEqual(
            parsed["procedural_bearing"],
            de.deterministic_party_role_procedural_bearing_paragraph(),
        )
        self.assertTrue(audit.get("party_role_deterministic_procedural_bearing_fallback"))
        self.assertEqual(
            parsed["complaint_roadmap"],
            de.normalize_whitespace(roadmap["complaint_roadmap"]),
        )


    def test_resolve_patch_fills_missing_rescission_effect(self):
        packet = _packet(FULL_SYNTHETIC_COMPLAINT)
        expected = de.extract_party_role_expected_attributes(packet)
        synthesis = de.extract_party_role_expected_synthesis(packet, expected)
        self.assertIn(
            "rescission_effect",
            {item["category"] for item in synthesis},
        )
        audit = {}

        parsed = de.resolve_party_role_synthesis_patch(
            {"synthesis_patch": {}},
            allowed_categories=["rescission_effect"],
            original_answer=_notice_and_rescission_prefix(expected),
            expected_synthesis=synthesis,
            audit_out=audit,
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(set(parsed), {"rescission_effect"})
        self.assertEqual(
            parsed["rescission_effect"],
            de.deterministic_party_role_rescission_effect_paragraph(synthesis),
        )
        self.assertTrue(
            audit.get("party_role_deterministic_rescission_effect_fallback")
        )
        self.assertEqual(
            de.find_missing_party_role_synthesis(
                {"proposed_answer": parsed["rescission_effect"]},
                [
                    item
                    for item in synthesis
                    if item["category"] == "rescission_effect"
                ],
            ),
            [],
        )


class PartyRoleSynthesisPatchSchemaAndLifecycleTests(unittest.TestCase):
    def test_omitted_category_fails_closed_with_audit_reason(self):
        packet = _packet(FULL_SYNTHETIC_COMPLAINT)
        synthesis = de.extract_party_role_expected_synthesis(packet)
        allowed = ["procedural_bearing", "complaint_roadmap"]
        sections = _patch_paragraphs_for_categories(["procedural_bearing"], synthesis)
        audit = {}
        parsed = de.parse_party_role_synthesis_patch(
            {"synthesis_patch": sections},
            allowed_categories=allowed,
            original_answer="Roster only.",
            expected_synthesis=synthesis,
            audit_out=audit,
        )
        self.assertIsNone(parsed)
        self.assertEqual(
            audit.get("party_role_synthesis_patch_audit_reason"),
            "synthesis_patch_omitted_categories:complaint_roadmap",
        )
        lifecycle = audit.get("party_role_synthesis_category_lifecycle") or []
        self.assertEqual(
            {row["category"] for row in lifecycle},
            set(allowed),
        )
        self.assertTrue(all(row["requested"] and not row["parsed"] for row in lifecycle))

    def test_unknown_and_duplicate_category_fail_closed_with_audit_reason(self):
        packet = _packet(FULL_SYNTHETIC_COMPLAINT)
        synthesis = de.extract_party_role_expected_synthesis(packet)
        allowed = ["procedural_bearing"]
        sections = _patch_paragraphs_for_categories(allowed, synthesis)
        sections["not_a_real_category"] = "Invented category text."
        audit_unknown = {}
        self.assertIsNone(
            de.parse_party_role_synthesis_patch(
                {"synthesis_patch": sections},
                allowed_categories=allowed,
                original_answer="Roster only.",
                expected_synthesis=synthesis,
                audit_out=audit_unknown,
            )
        )
        self.assertEqual(
            audit_unknown.get("party_role_synthesis_patch_audit_reason"),
            "synthesis_patch_unknown_categories:not_a_real_category",
        )

        # Duplicate after normalization of distinct raw keys.
        bearing = sections["procedural_bearing"]
        audit_dup = {}
        self.assertIsNone(
            de.parse_party_role_synthesis_patch(
                {
                    "synthesis_patch": {
                        "procedural_bearing": bearing,
                        "procedural_bearing ": bearing,
                    }
                },
                allowed_categories=allowed,
                original_answer="Roster only.",
                expected_synthesis=synthesis,
                audit_out=audit_dup,
            )
        )
        self.assertEqual(
            audit_dup.get("party_role_synthesis_patch_audit_reason"),
            "synthesis_patch_duplicate_categories",
        )

    def test_empty_category_fails_closed_with_audit_reason(self):
        packet = _packet(FULL_SYNTHETIC_COMPLAINT)
        synthesis = de.extract_party_role_expected_synthesis(packet)
        allowed = ["procedural_bearing"]
        audit = {}
        self.assertIsNone(
            de.parse_party_role_synthesis_patch(
                {"synthesis_patch": {"procedural_bearing": "   "}},
                allowed_categories=allowed,
                original_answer="Roster only.",
                expected_synthesis=synthesis,
                audit_out=audit,
            )
        )
        self.assertEqual(
            audit.get("party_role_synthesis_patch_audit_reason"),
            "synthesis_patch_empty_category:procedural_bearing",
        )

    def test_merge_preserves_patch_text_verbatim_after_whitespace_normalization(self):
        packet = _packet(FULL_SYNTHETIC_COMPLAINT)
        expected = de.extract_party_role_expected_attributes(packet)
        synthesis = de.extract_party_role_expected_synthesis(packet, expected)
        roster = _roster_only_answer(expected)
        raw_patch = (
            "  As procedural relevance only,   pleaded identity/role, entity "
            "form, and residence can bear upon service, jurisdiction as "
            "applicable, and venue.  "
        )
        audit = {
            "party_role_synthesis_category_lifecycle": de._init_synthesis_category_lifecycle(
                ["procedural_bearing"]
            )
        }
        sections = de.parse_party_role_synthesis_patch(
            {"synthesis_patch": {"procedural_bearing": raw_patch}},
            allowed_categories=["procedural_bearing"],
            original_answer=roster,
            expected_synthesis=synthesis,
            audit_out=audit,
        )
        self.assertIsNotNone(sections)
        expected_text = de.normalize_whitespace(raw_patch)
        self.assertEqual(sections["procedural_bearing"], expected_text)
        draft = {
            "proposed_answer": roster,
            "propositions": [{"proposition_id": "P1", "text": roster}],
        }
        merged = de.merge_party_role_synthesis_patch(
            draft, sections, audit_out=audit
        )
        self.assertIsNotNone(merged)
        self.assertIn(expected_text, merged["proposed_answer"])
        self.assertTrue(
            merged["proposed_answer"].startswith(roster)
            or roster in merged["proposed_answer"]
        )
        lifecycle = audit["party_role_synthesis_category_lifecycle"]
        bearing = next(row for row in lifecycle if row["category"] == "procedural_bearing")
        self.assertTrue(bearing["requested"])
        self.assertTrue(bearing["parsed"])
        self.assertTrue(bearing["merged"])

    def test_category_lifecycle_requested_parsed_merged_validated(self):
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
        lifecycle = result["audit"].get("party_role_synthesis_category_lifecycle") or []
        by_cat = {row["category"]: row for row in lifecycle}
        self.assertEqual(
            set(by_cat),
            {"procedural_bearing", "complaint_roadmap"},
        )
        for row in lifecycle:
            self.assertTrue(row["requested"])
            self.assertTrue(row["parsed"])
            self.assertTrue(row["merged"])
            self.assertTrue(row["validated"])
            # Diagnostics must stay category-level only.
            self.assertEqual(set(row.keys()), {
                "category",
                "requested",
                "parsed",
                "merged",
                "validated",
            })
            self.assertIsInstance(row["category"], str)
            for key in ("requested", "parsed", "merged", "validated"):
                self.assertIsInstance(row[key], bool)
        # No private evidence / model prose keys leaked into lifecycle blob.
        blob = json.dumps(lifecycle).lower()
        self.assertNotIn("north quay", blob)
        self.assertNotIn("proposed_answer", blob)
        self.assertNotIn("can bear on", blob)


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


class PartyRoleQ1SynthesisValidationFixTests(unittest.TestCase):
    """Six focused regressions for the Q1 synthesis/validation fix."""

    def test_mixed_gaps_lifecycle_includes_notice_after_attribute_repair(self):
        question = "Identify the parties and their procedural roles."
        retrieval = {
            "query": question,
            "results": [_hit(FULL_SYNTHETIC_COMPLAINT)],
        }
        calls = []

        def _model(_system, user_prompt):
            calls.append(user_prompt)
            packet = de.build_evidence_packet(question, retrieval)
            expected = de.extract_party_role_expected_attributes(packet)
            hit = packet["retrieval_hits"][0]
            if len(calls) == 1:
                # Incomplete attributes (omit residence/PPB) + no synthesis.
                bits = []
                for party in expected:
                    bit = f"{party.get('procedural_role')} {party.get('identity')}"
                    if party.get("entity_type"):
                        bit += f" is a {party['entity_type']}"
                    bits.append(bit + ".")
                return _synthetic_payload(" ".join(bits), hit)
            # Attribute repair fills roster only; synthesis still missing.
            return _synthetic_payload(_roster_only_answer(expected), hit)

        result = de.answer_attorney_record_question(
            question, retrieval, model_call=_model
        )
        self.assertEqual(len(calls), 2)
        lifecycle = result["audit"].get("party_role_synthesis_category_lifecycle") or []
        cats = {row["category"] for row in lifecycle}
        self.assertIn("notice_defendant_explanation", cats)
        self.assertIn("procedural_bearing", cats)
        notice_row = next(
            row
            for row in lifecycle
            if row["category"] == "notice_defendant_explanation"
        )
        self.assertTrue(notice_row.get("requested"))

    def test_deterministic_notice_fallback_after_attribute_repair(self):
        question = "Identify the parties and their procedural roles."
        # Roadmap+rescission already present after attribute repair; only PB+notice
        # need deterministic recovery.
        excerpt = (
            "PARTIES\n"
            "1. Plaintiff North Quay Logistics LLC is a domestic limited "
            "liability company with its principal place of business in Albany "
            "County.\n"
            "2. Defendant Pier Gate Depot Inc. is a domestic corporation with "
            "its principal place of business in Kings County.\n"
            "3. Defendant Harbor Mill Carrier LP is a notice defendant because "
            "its rights may be affected by the requested declaratory relief.\n"
            "4. Defendant Harbor Mill Carrier LP is a limited partnership "
            "residing in Erie County.\n"
            "WHEREFORE Plaintiff seeks a declaration that the policy is void ab "
            "initio and for rescission of the same.\n"
        )
        retrieval = {"query": question, "results": [_hit(excerpt)]}
        calls = []

        def _model(_system, user_prompt):
            calls.append(user_prompt)
            packet = de.build_evidence_packet(question, retrieval)
            expected = de.extract_party_role_expected_attributes(packet)
            synthesis = de.extract_party_role_expected_synthesis(packet, expected)
            hit = packet["retrieval_hits"][0]
            if len(calls) == 1:
                bits = []
                for party in expected:
                    bit = f"{party.get('procedural_role')} {party.get('identity')}"
                    if party.get("entity_type"):
                        bit += f" is a {party['entity_type']}"
                    bits.append(bit + ".")
                return _synthetic_payload(" ".join(bits), hit)
            # Complete attributes + roadmap + rescission; omit PB + notice.
            answer = _roster_only_answer(expected)
            roadmap = next(
                item
                for item in synthesis
                if item["category"] == "complaint_roadmap"
            )
            nums = list(roadmap.get("paragraph_numbers") or [])
            answer += (
                f" The complaint parties roadmap appears at paragraphs "
                f"{nums[0]} through {nums[-1]}."
            )
            answer += (
                " The requested rescission or void ab initio treatment may "
                "negatively affect those asserted rights, as alleged."
            )
            return _synthetic_payload(answer, hit)

        result = de.answer_attorney_record_question(
            question, retrieval, model_call=_model
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["status"], de.STATUS_READY)
        self.assertTrue(
            result["audit"].get(
                "party_role_deterministic_notice_defendant_explanation_fallback"
            )
        )
        self.assertTrue(
            result["audit"].get("party_role_deterministic_procedural_bearing_fallback")
        )
        lowered = (result.get("proposed_answer") or "").lower()
        self.assertIn("does not itself allege wrongdoing", lowered)
        self.assertIn("bear on service", lowered)

    def test_procedural_bearing_section_survives_unrelated_full_draft_pollution(self):
        question = "Identify the parties and their procedural roles."
        retrieval = {"query": question, "results": [_hit(FULL_SYNTHETIC_COMPLAINT)]}
        packet = de.build_evidence_packet(question, retrieval)
        expected = de.extract_party_role_expected_attributes(packet)
        synthesis = de.extract_party_role_expected_synthesis(packet, expected)
        hit = packet["retrieval_hits"][0]
        good = _complete_synthesis_answer(expected, synthesis)
        polluted = (
            good
            + " Separately, jurisdiction is established over every claim and "
            "this is a merits conclusion."
        )
        # Section acceptance for the bearing paragraph alone still holds.
        bearing = (
            "As procedural relevance only, pleaded identity/role, entity form, "
            "and residence or principal place of business can bear on service, "
            "jurisdiction as applicable, and venue; they are not conclusively "
            "established by those allegations."
        )
        self.assertTrue(
            de._synthesis_section_satisfies(bearing, "procedural_bearing", None)
        )
        # Full-draft pollution must not mark procedural_bearing missing.
        missing = de.find_missing_party_role_synthesis(
            _synthetic_payload(polluted, hit), synthesis
        )
        missing_cats = {item["category"] for item in missing}
        self.assertNotIn("procedural_bearing", missing_cats)
        # Still reject merits conclusions / unsupported jurisdiction assertions
        # when they are the only bearing-like content (no valid section).
        bad_only = (
            _roster_only_answer(expected)
            + " Jurisdiction is established and this is a merits conclusion."
        )
        missing_bad = de.find_missing_party_role_synthesis(
            _synthetic_payload(bad_only, hit), synthesis
        )
        self.assertIn(
            "procedural_bearing", {item["category"] for item in missing_bad}
        )
        # Conclusory language inside the bearing section itself still fails.
        conclusory_section = (
            "Pleaded identity/role, entity form, and residence can bear on "
            "service, jurisdiction as applicable, and venue, and those "
            "doctrines are established."
        )
        self.assertFalse(
            de._synthesis_section_satisfies(
                conclusory_section, "procedural_bearing", None
            )
        )

    def test_citation_scrub_preserves_both_synthesis_sections(self):
        question = "Identify the parties and their procedural roles."
        retrieval = {"query": question, "results": [_hit(FULL_SYNTHETIC_COMPLAINT)]}
        packet = de.build_evidence_packet(question, retrieval)
        expected = de.extract_party_role_expected_attributes(packet)
        synthesis = de.extract_party_role_expected_synthesis(packet, expected)
        hit = packet["retrieval_hits"][0]
        roster = _roster_only_answer(expected)
        sections = _patch_paragraphs_for_categories(
            ["procedural_bearing", "notice_defendant_explanation"],
            synthesis,
        )
        draft = _synthetic_payload(roster, hit)
        audit = {
            "party_role_synthesis_category_lifecycle": de._init_synthesis_category_lifecycle(
                ["procedural_bearing", "notice_defendant_explanation"]
            )
        }
        merged = de.merge_party_role_synthesis_patch(
            draft,
            sections,
            expected_synthesis=synthesis,
            audit_out=audit,
        )
        self.assertIsNotNone(merged)
        units = (merged.get("audit") or {}).get(
            de._PARTY_ROLE_RETAINED_SYNTHESIS_UNITS_KEY
        )
        self.assertEqual(
            {u["category"] for u in units},
            {"procedural_bearing", "notice_defendant_explanation"},
        )
        # Simulate citation scrub rebuilding answer from roster-only props.
        scrub_input = dict(merged)
        scrub_input["propositions"] = [
            {
                "proposition_id": "P1",
                "text": roster,
                "classification": "party_allegation",
                "nyscef_document_number": hit["nyscef_document_number"],
                "page_id": hit["page_id"],
                "pdf_page": hit["pdf_page"],
                "source_excerpt": "Plaintiff North Quay Logistics LLC",
                "confidence": 0.9,
                "rationale": "roster",
                "polarity": "supporting",
            }
        ]
        scrub_input["audit"] = {
            "removed_propositions": [
                {"proposition_id": "P_bad", "removal_reason": "invented_content"}
            ],
            "notes": [],
            de._PARTY_ROLE_RETAINED_SYNTHESIS_UNITS_KEY: units,
        }
        scrubbed = de._scrub_party_role_answer_after_citation_filter(scrub_input)
        answer = (scrubbed.get("proposed_answer") or "").lower()
        self.assertIn("bear on service", answer)
        self.assertIn("does not itself allege wrongdoing", answer)

    def test_failure_retains_fallback_flags_and_notice_lifecycle(self):
        question = "Identify the parties and their procedural roles."
        retrieval = {
            "query": question,
            "results": [_hit(FULL_SYNTHETIC_COMPLAINT)],
        }
        calls = []

        def _model(_system, user_prompt):
            calls.append(user_prompt)
            packet = de.build_evidence_packet(question, retrieval)
            expected = de.extract_party_role_expected_attributes(packet)
            hit = packet["retrieval_hits"][0]
            if len(calls) == 1:
                return _synthetic_payload(_roster_only_answer(expected), hit)
            # Synthesis patch omits non-fillable categories → fail closed after
            # deterministic PB+notice salvage.
            return {"synthesis_patch": {}}

        result = de.answer_attorney_record_question(
            question, retrieval, model_call=_model
        )
        self.assertEqual(result["status"], de.STATUS_NOT_READY)
        self.assertTrue(result["audit"].get("party_role_completeness_failed"))
        self.assertTrue(
            result["audit"].get("party_role_deterministic_procedural_bearing_fallback")
        )
        self.assertTrue(
            result["audit"].get(
                "party_role_deterministic_notice_defendant_explanation_fallback"
            )
        )
        lifecycle = result["audit"].get("party_role_synthesis_category_lifecycle") or []
        by_cat = {row["category"]: row for row in lifecycle}
        self.assertIn("notice_defendant_explanation", by_cat)
        self.assertTrue(by_cat["notice_defendant_explanation"].get("requested"))
        # Missing either non-fillable category still fails closed.
        missing_cats = {
            item.get("category")
            for item in result["audit"].get("missing_party_role_attributes") or []
        }
        self.assertTrue(
            {"rescission_effect", "complaint_roadmap"} & missing_cats
        )

    def test_golden_replay_observed_mixed_gap_run_shape(self):
        """Replay the observed Q1 shape: mixed gaps → attribute repair →
        deterministic PB+notice recovery → durable synthesis; still reject
        merits conclusions and missing either required category.
        """
        question = "Identify the parties and their procedural roles."
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
            lowered = user_prompt.lower()
            self.assertNotIn("gold_should_not_appear", lowered)
            self.assertNotIn("feedback_should_not_appear", lowered)
            packet = de.build_evidence_packet(question, retrieval)
            expected = de.extract_party_role_expected_attributes(packet)
            synthesis = de.extract_party_role_expected_synthesis(packet, expected)
            hit = packet["retrieval_hits"][0]
            if len(calls) == 1:
                # Observed shape: attribute holes + no synthesis.
                bits = []
                for party in expected:
                    bit = f"{party.get('procedural_role')} {party.get('identity')}"
                    if party.get("entity_type"):
                        bit += f" is a {party['entity_type']}"
                    bits.append(bit + ".")
                return _synthetic_payload(" ".join(bits), hit)
            # Attribute repair returns complete roster + roadmap + rescission,
            # still omitting PB + notice (fillable deterministic recovery).
            answer = _roster_only_answer(expected)
            roadmap = next(
                item
                for item in synthesis
                if item["category"] == "complaint_roadmap"
            )
            nums = list(roadmap.get("paragraph_numbers") or [])
            headings = list(roadmap.get("section_headings") or [])
            answer += (
                f" The complaint parties roadmap appears at paragraphs "
                f"{nums[0]} through {nums[-1]}."
            )
            if headings:
                answer += f" Section organization includes {headings[0]}."
            answer += (
                " The requested rescission or void ab initio treatment may "
                "negatively affect those asserted rights, as alleged."
            )
            return _synthetic_payload(answer, hit)

        result = de.answer_attorney_record_question(
            question, retrieval, model_call=_model
        )
        self.assertEqual(len(calls), 2, "one-repair limit must hold")
        self.assertEqual(result["status"], de.STATUS_READY)
        audit = result["audit"]
        self.assertTrue(audit.get("party_role_repair_attempted"))
        self.assertTrue(
            audit.get("party_role_deterministic_procedural_bearing_fallback")
        )
        self.assertTrue(
            audit.get(
                "party_role_deterministic_notice_defendant_explanation_fallback"
            )
        )
        lifecycle = audit.get("party_role_synthesis_category_lifecycle") or []
        cats = {row["category"] for row in lifecycle}
        self.assertIn("notice_defendant_explanation", cats)
        self.assertIn("procedural_bearing", cats)
        answer = (result.get("proposed_answer") or "").lower()
        self.assertIn("bear on service", answer)
        self.assertIn("does not itself allege wrongdoing", answer)
        self.assertNotIn("merits conclusion that doctrines are established", answer)
        # Missing either fillable category still fails closed when recovery is
        # blocked: strip notice from a ready draft and re-check.
        synthesis = de.extract_party_role_expected_synthesis(
            de.build_evidence_packet(question, retrieval)
        )
        notice_criterion = next(
            item
            for item in synthesis
            if item["category"] == "notice_defendant_explanation"
        )
        no_notice = answer.replace(
            "notice-defendant joinder reflects the potential effect of the "
            "requested relief on asserted rights and does not itself allege "
            "wrongdoing.",
            "",
        )
        self.assertFalse(
            de._draft_has_notice_defendant_explanation(
                de.normalize_citation_text(no_notice),
                require_rights_link=bool(
                    notice_criterion.get("require_rights_link")
                ),
            )
        )


if __name__ == "__main__":
    unittest.main()
