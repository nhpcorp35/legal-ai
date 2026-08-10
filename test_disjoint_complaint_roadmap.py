"""Synthetic regressions for disjoint evidence-backed complaint roadmaps.

Covers structure-backed section_ranges that must stay disjoint across evidence
building, expected-synthesis extraction, bounded repair parse/merge, and final
completeness validation. Uses only fabricated headings and paragraph ranges —
no private case identities, gold answers, attorney feedback, or benchmark prose.
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


def _disjoint_gapped_structure_map(nyscef: int = 910) -> dict:
    """Overview / intervening / parties with numeric gaps between sections."""
    pages = [
        _page(
            nyscef=nyscef,
            page_number=1,
            text=(
                "SUPREME COURT OF THE STATE OF NEW YORK\n"
                "Synthetic Harbor Freight LLC v. Pier Lantern Depot Inc.\n"
                "OVERVIEW\n"
                "1. This is an action concerning a fabricated carriage dispute.\n"
                "2. The pleading frames commercial logistics obligations.\n"
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


def _adjacent_disjoint_structure_map(nyscef: int = 920) -> dict:
    """Three contiguous section blocks that must not collapse to 1–7."""
    pages = [
        _page(
            nyscef=nyscef,
            page_number=1,
            text=(
                "OVERVIEW\n"
                "1. Fabricated overview allegation one.\n"
                "2. Fabricated overview allegation two.\n"
            ),
        ),
        _page(
            nyscef=nyscef,
            page_number=2,
            text=(
                "INTERVENING FACTS\n"
                "3. Fabricated intervening fact three.\n"
                "4. Fabricated intervening fact four.\n"
                "5. Fabricated intervening fact five.\n"
            ),
        ),
        _page(
            nyscef=nyscef,
            page_number=3,
            text=(
                "PARTIES\n"
                "6. Plaintiff Synthetic Harbor Freight LLC is a domestic "
                "limited liability company with its principal place of "
                "business in Kings County.\n"
                "7. Defendant Pier Lantern Depot Inc. is a domestic "
                "corporation.\n"
            ),
        ),
    ]
    return cs.build_complaint_structure_map({"pages": pages})


def _party_role_hits(nyscef: int, *, parties_page: int = 3) -> dict:
    return {
        "query": "Who are the parties and what are their roles in this action?",
        "results": [
            {
                "result_id": f"hit-{nyscef}-parties",
                "page_id": f"nyscef-{nyscef:03d}-page-{parties_page:04d}",
                "nyscef_document_number": nyscef,
                "pdf_page": parties_page,
                "source_filename": f"doc_{nyscef}_complaint.pdf",
                "document_type": "complaint",
                "excerpt": (
                    "PARTIES\n"
                    "Plaintiff Synthetic Harbor Freight LLC is a domestic "
                    "limited liability company with its principal place of "
                    "business in Kings County.\n"
                    "Defendant Pier Lantern Depot Inc. is a domestic "
                    "corporation.\n"
                ),
                "classifications": ["party_allegation"],
                "score": 0.9,
            }
        ],
    }


def _roadmap_criterion(packet: dict) -> dict:
    synthesis = de.extract_party_role_expected_synthesis(packet)
    return next(
        item for item in synthesis if item["category"] == "complaint_roadmap"
    )


def _good_disjoint_gapped_paragraph() -> str:
    return (
        "The complaint roadmap preserves OVERVIEW paragraphs 1 through 2, "
        "INTERVENING FACTS paragraphs 4 through 5, and PARTIES paragraphs "
        "10 through 11."
    )


def _good_adjacent_disjoint_paragraph() -> str:
    return (
        "The complaint roadmap preserves OVERVIEW paragraphs 1 through 2, "
        "INTERVENING FACTS paragraphs 3 through 5, and PARTIES paragraphs "
        "6 through 7."
    )


class DisjointComplaintRoadmapEvidenceTests(unittest.TestCase):
    def test_evidence_packet_preserves_canonical_disjoint_section_ranges(self):
        structure_map = _disjoint_gapped_structure_map(910)
        packet = de.build_evidence_packet(
            "Who are the parties and what are their roles in this action?",
            _party_role_hits(910),
            complaint_structure_map=structure_map,
        )
        context = packet.get("complaint_structure_context")
        self.assertIsInstance(context, dict)
        self.assertEqual(context.get("schema_version"), SCHEMA)
        sections = context["documents"][0]["sections"]
        kinds = [sec.get("kind") for sec in sections]
        self.assertEqual(kinds.count("overview"), 1)
        self.assertEqual(kinds.count("factual_layout"), 1)
        self.assertEqual(kinds.count("parties"), 1)

        overview = next(sec for sec in sections if sec["kind"] == "overview")
        facts = next(sec for sec in sections if sec["kind"] == "factual_layout")
        parties = next(sec for sec in sections if sec["kind"] == "parties")
        self.assertEqual(overview.get("heading"), "OVERVIEW")
        self.assertEqual(facts.get("heading"), "INTERVENING FACTS")
        self.assertEqual(parties.get("heading"), "PARTIES")
        self.assertEqual(
            overview.get("paragraph_range"),
            {"start": 1, "end": 2, "contiguous": True},
        )
        self.assertEqual(
            facts.get("paragraph_range"),
            {"start": 4, "end": 5, "contiguous": True},
        )
        self.assertEqual(
            parties.get("paragraph_range"),
            {"start": 10, "end": 11, "contiguous": True},
        )
        # Must not invent a continuous document-level span across the gaps.
        for sec in sections:
            pr = sec.get("paragraph_range") or {}
            self.assertFalse(
                pr.get("start") == 1 and pr.get("end") == 11
            )


class DisjointComplaintRoadmapSynthesisContractTests(unittest.TestCase):
    def test_synthesis_keeps_disjoint_ranges_without_collapsed_exact_span(self):
        packet = de.build_evidence_packet(
            "Who are the parties and what are their roles in this action?",
            _party_role_hits(910),
            complaint_structure_map=_disjoint_gapped_structure_map(910),
        )
        roadmap = _roadmap_criterion(packet)
        self.assertTrue(roadmap.get("structure_backed"))
        self.assertIsNone(roadmap.get("exact_paragraph_range"))
        ranges = roadmap.get("section_ranges") or []
        self.assertEqual(len(ranges), 3)
        by_kind = {item["kind"]: item for item in ranges}
        self.assertEqual(
            (by_kind["overview"]["start"], by_kind["overview"]["end"]),
            (1, 2),
        )
        self.assertEqual(
            (by_kind["factual_layout"]["start"], by_kind["factual_layout"]["end"]),
            (4, 5),
        )
        self.assertEqual(
            (by_kind["parties"]["start"], by_kind["parties"]["end"]),
            (10, 11),
        )
        headings = {h.lower() for h in roadmap.get("section_headings") or []}
        self.assertIn("overview", headings)
        self.assertIn("intervening facts", headings)
        self.assertIn("parties", headings)

    def test_adjacent_sections_also_refuse_collapsed_exact_paragraph_range(self):
        packet = de.build_evidence_packet(
            "Who are the parties and what are their roles in this action?",
            _party_role_hits(920),
            complaint_structure_map=_adjacent_disjoint_structure_map(920),
        )
        roadmap = _roadmap_criterion(packet)
        self.assertTrue(roadmap.get("structure_backed"))
        self.assertIsNone(roadmap.get("exact_paragraph_range"))
        self.assertEqual(len(roadmap.get("section_ranges") or []), 3)

    def test_initial_synthesis_and_repair_share_canonical_roadmap_contract(self):
        packet = de.build_evidence_packet(
            "Who are the parties and what are their roles in this action?",
            _party_role_hits(910),
            complaint_structure_map=_disjoint_gapped_structure_map(910),
        )
        synthesis = de.extract_party_role_expected_synthesis(packet)
        roadmap = next(
            item for item in synthesis if item["category"] == "complaint_roadmap"
        )
        missing = de.find_missing_party_role_synthesis(
            {
                "proposed_answer": (
                    "Plaintiff Synthetic Harbor Freight LLC is a domestic "
                    "limited liability company. Defendant Pier Lantern Depot "
                    "Inc. is a domestic corporation."
                ),
                "propositions": [],
            },
            synthesis,
        )
        repair_item = next(
            item for item in missing if item["category"] == "complaint_roadmap"
        )
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
        self.assertIsNone(facts.get("exact_paragraph_range"))
        self.assertTrue(facts.get("structure_backed"))

        repair_prompt = de.build_party_role_synthesis_patch_prompt(
            question="Who are the parties and what are their roles?",
            missing_synthesis=[repair_item],
        )
        self.assertIn("section_ranges", repair_prompt)
        self.assertIn('"start":1', repair_prompt)
        self.assertIn('"end":2', repair_prompt)
        self.assertIn('"start":10', repair_prompt)
        self.assertIn('"end":11', repair_prompt)
        # Collapsed continuous contract must not be injected for repair.
        self.assertNotIn('"exact_paragraph_range":{"start":1,"end":11}', repair_prompt)
        self.assertIn('"exact_paragraph_range":null', repair_prompt)


class DisjointComplaintRoadmapValidationTests(unittest.TestCase):
    def test_accepts_evidence_backed_disjoint_ranges(self):
        packet = de.build_evidence_packet(
            "Who are the parties and what are their roles in this action?",
            _party_role_hits(910),
            complaint_structure_map=_disjoint_gapped_structure_map(910),
        )
        synthesis = de.extract_party_role_expected_synthesis(packet)
        draft = {
            "proposed_answer": _good_disjoint_gapped_paragraph(),
            "propositions": [],
        }
        missing = de.find_missing_party_role_synthesis(draft, synthesis)
        self.assertNotIn(
            "complaint_roadmap",
            {item["category"] for item in missing},
        )

    def test_rejects_invented_continuous_range_spanning_gaps(self):
        packet = de.build_evidence_packet(
            "Who are the parties and what are their roles in this action?",
            _party_role_hits(910),
            complaint_structure_map=_disjoint_gapped_structure_map(910),
        )
        synthesis = de.extract_party_role_expected_synthesis(packet)
        collapsed = {
            "proposed_answer": (
                "The complaint roadmap preserves OVERVIEW, INTERVENING FACTS, "
                "and PARTIES at paragraphs 1 through 11."
            ),
            "propositions": [],
        }
        missing = de.find_missing_party_role_synthesis(collapsed, synthesis)
        self.assertIn(
            "complaint_roadmap",
            {item["category"] for item in missing},
        )

    def test_rejects_collapsed_adjacent_disjoint_ranges(self):
        packet = de.build_evidence_packet(
            "Who are the parties and what are their roles in this action?",
            _party_role_hits(920),
            complaint_structure_map=_adjacent_disjoint_structure_map(920),
        )
        synthesis = de.extract_party_role_expected_synthesis(packet)
        collapsed = {
            "proposed_answer": (
                "The complaint roadmap preserves OVERVIEW, INTERVENING FACTS, "
                "and PARTIES at paragraphs 1 through 7."
            ),
            "propositions": [],
        }
        missing = de.find_missing_party_role_synthesis(collapsed, synthesis)
        self.assertIn(
            "complaint_roadmap",
            {item["category"] for item in missing},
        )
        cross_section = {
            "proposed_answer": (
                "The complaint roadmap preserves OVERVIEW, INTERVENING FACTS, "
                "and PARTIES at paragraphs 1 through 5 and paragraphs 6 "
                "through 7."
            ),
            "propositions": [],
        }
        missing_cross = de.find_missing_party_role_synthesis(
            cross_section, synthesis
        )
        self.assertIn(
            "complaint_roadmap",
            {item["category"] for item in missing_cross},
        )
        good = {
            "proposed_answer": _good_adjacent_disjoint_paragraph(),
            "propositions": [],
        }
        missing_ok = de.find_missing_party_role_synthesis(good, synthesis)
        self.assertNotIn(
            "complaint_roadmap",
            {item["category"] for item in missing_ok},
        )

    def test_rejects_invented_span_when_sections_lack_contiguous_ranges(self):
        context = {
            "schema_version": SCHEMA,
            "selection": {"status": "selected"},
            "documents": [
                {
                    "document_id": "nyscef-930",
                    "nyscef_document_number": 930,
                    "sections": [
                        {
                            "heading": "OVERVIEW",
                            "kind": "overview",
                            "paragraph_numbers": [1, 3],
                            "paragraph_range": None,
                            "page_ids": ["nyscef-930-page-0001"],
                            "provenance": {"nyscef_document_number": 930},
                        },
                        {
                            "heading": "PARTIES",
                            "kind": "parties",
                            "paragraph_numbers": [10, 12],
                            "paragraph_range": None,
                            "page_ids": ["nyscef-930-page-0002"],
                            "provenance": {"nyscef_document_number": 930},
                        },
                    ],
                }
            ],
        }
        packet = {
            "question": "Who are the parties and what are their roles?",
            "retrieval_hits": [
                {
                    "excerpt": "PARTIES\n10. Plaintiff Synthetic Harbor Freight LLC.\n",
                    "page_id": "nyscef-930-page-0002",
                    "nyscef_document_number": 930,
                    "pdf_page": 2,
                }
            ],
            "complaint_structure_context": context,
        }
        synthesis = de.extract_party_role_expected_synthesis(packet)
        roadmap = next(
            item for item in synthesis if item["category"] == "complaint_roadmap"
        )
        self.assertIsNone(roadmap.get("exact_paragraph_range"))
        invented = {
            "proposed_answer": (
                "The complaint roadmap preserves OVERVIEW paragraphs 1 through "
                "3 and PARTIES paragraphs 10 through 12."
            ),
            "propositions": [],
        }
        missing = de.find_missing_party_role_synthesis(invented, synthesis)
        self.assertIn(
            "complaint_roadmap",
            {item["category"] for item in missing},
        )
        observed = {
            "proposed_answer": (
                "The complaint roadmap preserves OVERVIEW paragraphs 1 and 3 "
                "and PARTIES paragraphs 10 and 12."
            ),
            "propositions": [],
        }
        missing_ok = de.find_missing_party_role_synthesis(observed, synthesis)
        self.assertNotIn(
            "complaint_roadmap",
            {item["category"] for item in missing_ok},
        )


class DisjointComplaintRoadmapRepairMergeTests(unittest.TestCase):
    def test_repair_parse_rejects_collapsed_range_and_accepts_disjoint(self):
        packet = de.build_evidence_packet(
            "Who are the parties and what are their roles in this action?",
            _party_role_hits(910),
            complaint_structure_map=_disjoint_gapped_structure_map(910),
        )
        synthesis = de.extract_party_role_expected_synthesis(packet)
        original = (
            "Plaintiff Synthetic Harbor Freight LLC is a domestic limited "
            "liability company. Defendant Pier Lantern Depot Inc. is a "
            "domestic corporation."
        )
        audit = {}
        rejected = de.parse_party_role_synthesis_patch(
            {
                "synthesis_patch": {
                    "complaint_roadmap": (
                        "The complaint roadmap preserves OVERVIEW, "
                        "INTERVENING FACTS, and PARTIES at paragraphs 1 "
                        "through 11."
                    )
                }
            },
            allowed_categories=["complaint_roadmap"],
            original_answer=original,
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
                    "complaint_roadmap": _good_disjoint_gapped_paragraph()
                }
            },
            allowed_categories=["complaint_roadmap"],
            original_answer=original,
            expected_synthesis=synthesis,
        )
        self.assertIsNotNone(accepted)
        self.assertIn("complaint_roadmap", accepted)

    def test_merge_preserves_disjoint_roadmap_paragraph(self):
        packet = de.build_evidence_packet(
            "Who are the parties and what are their roles in this action?",
            _party_role_hits(910),
            complaint_structure_map=_disjoint_gapped_structure_map(910),
        )
        synthesis = de.extract_party_role_expected_synthesis(packet)
        original = (
            "Plaintiff Synthetic Harbor Freight LLC is a domestic limited "
            "liability company. Defendant Pier Lantern Depot Inc. is a "
            "domestic corporation."
        )
        roadmap_text = _good_disjoint_gapped_paragraph()
        sections = de.parse_party_role_synthesis_patch(
            {"synthesis_patch": {"complaint_roadmap": roadmap_text}},
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
        answer = de.normalize_whitespace(merged.get("proposed_answer") or "")
        self.assertIn(
            de.normalize_whitespace(roadmap_text).lower(),
            answer.lower(),
        )
        self.assertIn("paragraphs 1 through 2", answer.lower())
        self.assertIn("paragraphs 4 through 5", answer.lower())
        self.assertIn("paragraphs 10 through 11", answer.lower())
        self.assertNotIn("paragraphs 1 through 11", answer.lower())

        missing = de.find_missing_party_role_synthesis(merged, synthesis)
        self.assertNotIn(
            "complaint_roadmap",
            {item["category"] for item in missing},
        )


if __name__ == "__main__":
    unittest.main()
