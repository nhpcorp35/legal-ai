"""Phase 2 synthetic tests: final-prose canonical roadmap coverage.

Proves that when authoritative complaint_structure_context is attached, every
canonical evidence-backed section must appear in the candidate answer.
Incomplete PARTIES-only / omitted-middle fallbacks fail completeness; the
single bounded repair receives the precise missing canonical section contract;
repaired prose that restores full coverage passes.

Uses only fabricated headings and paragraph ranges — no private case
identities, gold answers, attorney feedback, or benchmark prose.
"""

from __future__ import annotations

import unittest

import complaint_structure as cs
import engines.drafting_engine as de


SCHEMA = cs.SCHEMA_VERSION


def _page(
    *,
    nyscef: int,
    page_number: int,
    text: str,
    document_type: str = "complaint",
) -> dict:
    filename = f"doc_{nyscef}_{document_type}.pdf"
    return {
        "nyscef_document_number": nyscef,
        "page_number": page_number,
        "page_id": f"nyscef-{nyscef:03d}-page-{page_number:04d}",
        "text": text,
        "extraction_method": "native",
        "pdf_page_number": page_number,
        "source_filename": filename,
        "source_path": f"/synthetic/{filename}",
        "document_type": document_type,
        "document_title": filename,
        "document_classification": document_type,
    }


def _three_section_structure_map(nyscef: int = 710) -> dict:
    """Fabricated overview / middle intervening / parties with gaps."""
    pages = [
        _page(
            nyscef=nyscef,
            page_number=1,
            text=(
                "SUPREME COURT OF THE STATE OF NEW YORK\n"
                "Synthetic Harbor Freight LLC v. Pier Lantern Depot Inc.\n"
                "OVERVIEW\n"
                "1. This fabricated pleading frames a commercial carriage dispute.\n"
                "2. The overview identifies the contractual relationship at issue.\n"
            ),
        ),
        _page(
            nyscef=nyscef,
            page_number=2,
            text=(
                "INTERVENING FACTS\n"
                "4. On a fabricated date the parties exchanged shipping terms.\n"
                "5. Delivery windows allegedly failed under those terms.\n"
            ),
        ),
        _page(
            nyscef=nyscef,
            page_number=3,
            text=(
                "PARTIES\n"
                "10. Plaintiff Synthetic Harbor Freight LLC is a domestic "
                "limited liability company with its principal place of "
                "business in Kings County.\n"
                "11. Defendant Pier Lantern Depot Inc. is a domestic "
                "corporation.\n"
            ),
        ),
    ]
    return cs.build_complaint_structure_map({"pages": pages})


def _party_role_hits(nyscef: int = 710) -> dict:
    return {
        "query": "Who are the parties and what are their roles in this action?",
        "results": [
            {
                "result_id": "hit-parties",
                "page_id": f"nyscef-{nyscef:03d}-page-0003",
                "nyscef_document_number": nyscef,
                "pdf_page": 3,
                "source_filename": f"doc_{nyscef}_complaint.pdf",
                "document_type": "complaint",
                "excerpt": (
                    "PARTIES\n"
                    "10. Plaintiff Synthetic Harbor Freight LLC is a domestic "
                    "limited liability company with its principal place of "
                    "business in Kings County.\n"
                    "11. Defendant Pier Lantern Depot Inc. is a domestic "
                    "corporation.\n"
                ),
                "score": 0.9,
            }
        ],
    }


def _packet(nyscef: int = 710) -> dict:
    return de.build_evidence_packet(
        "Who are the parties and what are their roles in this action?",
        _party_role_hits(nyscef),
        complaint_structure_map=_three_section_structure_map(nyscef),
    )


def _roadmap(packet: dict) -> dict:
    synthesis = de.extract_party_role_expected_synthesis(packet)
    return next(
        item for item in synthesis if item["category"] == "complaint_roadmap"
    )


def _full_coverage_prose() -> str:
    return (
        "The complaint roadmap preserves OVERVIEW paragraphs 1 through 2, "
        "INTERVENING FACTS paragraphs 4 through 5, and PARTIES paragraphs "
        "10 through 11."
    )


def _omit_middle_prose() -> str:
    return (
        "The complaint roadmap preserves OVERVIEW paragraphs 1 through 2 "
        "and PARTIES paragraphs 10 through 11."
    )


def _incomplete_parties_fallback_prose() -> str:
    return (
        "The complaint parties roadmap appears in the PARTIES section at "
        "paragraphs 10 through 11."
    )


class Phase2FinalProseRoadmapCoverageTests(unittest.TestCase):
    def test_full_coverage_passes_completeness(self) -> None:
        packet = _packet(710)
        self.assertIsInstance(packet.get("complaint_structure_context"), dict)
        synthesis = de.extract_party_role_expected_synthesis(packet)
        roadmap = _roadmap(packet)
        self.assertTrue(roadmap.get("structure_backed"))
        self.assertEqual(len(roadmap.get("section_ranges") or []), 3)
        draft = {
            "proposed_answer": _full_coverage_prose(),
            "propositions": [],
        }
        missing = de.find_missing_party_role_synthesis(draft, synthesis)
        self.assertNotIn(
            "complaint_roadmap",
            {item["category"] for item in missing},
        )

    def test_omitted_middle_section_fails_completeness(self) -> None:
        packet = _packet(711)
        synthesis = de.extract_party_role_expected_synthesis(packet)
        draft = {
            "proposed_answer": _omit_middle_prose(),
            "propositions": [],
        }
        missing = de.find_missing_party_role_synthesis(draft, synthesis)
        self.assertIn(
            "complaint_roadmap",
            {item["category"] for item in missing},
        )
        gap = next(
            item for item in missing if item["category"] == "complaint_roadmap"
        )
        omitted = gap.get("missing_sections") or []
        omitted_headings = {
            de.normalize_whitespace(sec.get("heading") or "").lower()
            for sec in omitted
        }
        self.assertIn("intervening facts", omitted_headings)
        self.assertNotIn("overview", omitted_headings)
        self.assertNotIn("parties", omitted_headings)

    def test_incomplete_parties_fallback_rejected_when_structure_attached(
        self,
    ) -> None:
        packet = _packet(712)
        synthesis = de.extract_party_role_expected_synthesis(packet)
        draft = {
            "proposed_answer": _incomplete_parties_fallback_prose(),
            "propositions": [],
        }
        missing = de.find_missing_party_role_synthesis(draft, synthesis)
        self.assertIn(
            "complaint_roadmap",
            {item["category"] for item in missing},
        )


class Phase2BoundedRepairCanonicalContractTests(unittest.TestCase):
    def test_bounded_repair_receives_precise_missing_canonical_contract(
        self,
    ) -> None:
        packet = _packet(720)
        synthesis = de.extract_party_role_expected_synthesis(packet)
        roadmap = _roadmap(packet)
        missing = de.find_missing_party_role_synthesis(
            {
                "proposed_answer": _omit_middle_prose(),
                "propositions": [],
            },
            synthesis,
        )
        repair_item = next(
            item for item in missing if item["category"] == "complaint_roadmap"
        )
        # Full canonical contract preserved for repair (same as synthesis).
        self.assertEqual(
            repair_item.get("section_ranges"),
            roadmap.get("section_ranges"),
        )
        self.assertEqual(
            repair_item.get("section_headings"),
            [
                de.normalize_whitespace(h).lower()
                for h in (roadmap.get("section_headings") or [])
                if de.normalize_whitespace(h)
            ],
        )
        self.assertEqual(
            repair_item.get("paragraph_numbers"),
            roadmap.get("paragraph_numbers"),
        )
        self.assertIsNone(repair_item.get("exact_paragraph_range"))
        self.assertTrue(repair_item.get("structure_backed"))
        facts = repair_item.get("evidence_facts") or {}
        self.assertEqual(facts.get("section_ranges"), roadmap.get("section_ranges"))
        self.assertTrue(facts.get("structure_backed"))
        self.assertIsNone(facts.get("exact_paragraph_range"))

        omitted = repair_item.get("missing_sections") or []
        self.assertEqual(facts.get("missing_sections"), omitted)
        self.assertEqual(len(omitted), 1)
        middle = omitted[0]
        self.assertEqual(
            de.normalize_whitespace(middle.get("heading") or "").lower(),
            "intervening facts",
        )
        self.assertEqual(middle.get("start"), 4)
        self.assertEqual(middle.get("end"), 5)

        repair_prompt = de.build_party_role_synthesis_patch_prompt(
            question="Who are the parties and what are their roles?",
            missing_synthesis=[repair_item],
        )
        self.assertIn("missing_sections", repair_prompt)
        self.assertIn("intervening facts", repair_prompt.lower())
        self.assertIn('"start":4', repair_prompt)
        self.assertIn('"end":5', repair_prompt)
        # Full contract still present — not a collapsed continuous span.
        self.assertIn('"start":1', repair_prompt)
        self.assertIn('"end":2', repair_prompt)
        self.assertIn('"start":10', repair_prompt)
        self.assertIn('"end":11', repair_prompt)
        self.assertIn('"exact_paragraph_range":null', repair_prompt)
        self.assertNotIn(
            '"exact_paragraph_range":{"start":1,"end":11}',
            repair_prompt,
        )
        self.assertIn("every canonical section", repair_prompt.lower())

    def test_repaired_prose_passes_after_bounded_merge(self) -> None:
        packet = _packet(721)
        synthesis = de.extract_party_role_expected_synthesis(packet)
        original = (
            "Plaintiff Synthetic Harbor Freight LLC is a domestic limited "
            "liability company. Defendant Pier Lantern Depot Inc. is a "
            "domestic corporation. "
            + _omit_middle_prose()
        )
        # Initial candidate omits the middle section.
        initial_missing = de.find_missing_party_role_synthesis(
            {"proposed_answer": original, "propositions": []},
            synthesis,
        )
        self.assertIn(
            "complaint_roadmap",
            {item["category"] for item in initial_missing},
        )

        repaired_section = _full_coverage_prose()
        sections = de.parse_party_role_synthesis_patch(
            {
                "synthesis_patch": {
                    "complaint_roadmap": repaired_section,
                }
            },
            allowed_categories=["complaint_roadmap"],
            original_answer=original,
            expected_synthesis=synthesis,
        )
        self.assertIsNotNone(sections)
        merged = de.merge_party_role_synthesis_patch(
            {"proposed_answer": original, "propositions": []},
            sections,
            expected_synthesis=synthesis,
        )
        self.assertIsNotNone(merged)
        final_missing = de.find_missing_party_role_synthesis(merged, synthesis)
        self.assertNotIn(
            "complaint_roadmap",
            {item["category"] for item in final_missing},
        )
        answer = de.normalize_whitespace(merged.get("proposed_answer") or "")
        self.assertIn("intervening facts", answer.lower())
        self.assertIn("paragraphs 4 through 5", answer.lower())
        self.assertIn("paragraphs 1 through 2", answer.lower())
        self.assertIn("paragraphs 10 through 11", answer.lower())


class Phase2CanonicalContractConsistencyTests(unittest.TestCase):
    def test_synthesis_repair_merge_validation_share_contract(self) -> None:
        packet = _packet(730)
        synthesis = de.extract_party_role_expected_synthesis(packet)
        roadmap = _roadmap(packet)
        self.assertTrue(roadmap.get("structure_backed"))
        self.assertIsNone(roadmap.get("exact_paragraph_range"))
        ranges = roadmap.get("section_ranges") or []
        self.assertEqual(len(ranges), 3)

        missing = de.find_missing_party_role_synthesis(
            {
                "proposed_answer": _incomplete_parties_fallback_prose(),
                "propositions": [],
            },
            synthesis,
        )
        repair_item = next(
            item for item in missing if item["category"] == "complaint_roadmap"
        )
        self.assertEqual(repair_item.get("section_ranges"), ranges)
        self.assertTrue(repair_item.get("structure_backed"))
        self.assertIsNone(repair_item.get("exact_paragraph_range"))

        # Incomplete repair patch must fail the same structure-backed contract.
        audit = {}
        rejected = de.parse_party_role_synthesis_patch(
            {
                "synthesis_patch": {
                    "complaint_roadmap": _incomplete_parties_fallback_prose()
                }
            },
            allowed_categories=["complaint_roadmap"],
            original_answer="Roster text only.",
            expected_synthesis=synthesis,
            audit_out=audit,
        )
        self.assertIsNone(rejected)
        self.assertIn(
            "synthesis_patch_section_fails_category_check:complaint_roadmap",
            audit.get("party_role_synthesis_patch_audit_reason") or "",
        )

        accepted = de.parse_party_role_synthesis_patch(
            {
                "synthesis_patch": {
                    "complaint_roadmap": _full_coverage_prose()
                }
            },
            allowed_categories=["complaint_roadmap"],
            original_answer="Roster text only.",
            expected_synthesis=synthesis,
        )
        self.assertIsNotNone(accepted)
        merged = de.merge_party_role_synthesis_patch(
            {"proposed_answer": "Roster text only.", "propositions": []},
            accepted,
            expected_synthesis=synthesis,
        )
        self.assertIsNotNone(merged)
        self.assertNotIn(
            "complaint_roadmap",
            {
                item["category"]
                for item in de.find_missing_party_role_synthesis(
                    merged, synthesis
                )
            },
        )


if __name__ == "__main__":
    unittest.main()
