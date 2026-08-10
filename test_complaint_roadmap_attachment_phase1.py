"""Phase 1 synthetic e2e: structure-map + party-role roadmap attachment.

Proves generic recognition of introduction/overview, factual/background
allegation, and parties sections from headings and paragraph boundaries, and
that party-role attachment preserves all relevant disjoint section ranges.

Uses only fabricated headings and ranges — no private case identities, gold
answers, attorney feedback, or benchmark prose. Does not exercise final-prose
completeness enforcement.
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


def _fabricated_disjoint_pages(nyscef: int = 610) -> list[dict]:
    """Introduction + two factual blocks + parties with numeric gaps."""
    return [
        _page(
            nyscef=nyscef,
            page_number=1,
            text=(
                "SUPREME COURT OF THE STATE OF NEW YORK\n"
                "Synthetic Harbor Freight LLC v. Pier Lantern Depot Inc.\n"
                "INTRODUCTION\n"
                "1. This fabricated pleading frames a commercial carriage dispute.\n"
                "2. The overview identifies the contractual relationship at issue.\n"
            ),
        ),
        _page(
            nyscef=nyscef,
            page_number=2,
            text=(
                "JURISDICTION AND VENUE\n"
                "3. This court has jurisdiction over the fabricated controversy.\n"
            ),
        ),
        _page(
            nyscef=nyscef,
            page_number=3,
            text=(
                "FACTUAL BACKGROUND\n"
                "5. On a fabricated date the parties exchanged shipping terms.\n"
                "6. Delivery windows allegedly failed under those terms.\n"
            ),
        ),
        _page(
            nyscef=nyscef,
            page_number=4,
            text=(
                "ALLEGATIONS\n"
                "8. Remediation costs followed from the missed windows.\n"
            ),
        ),
        _page(
            nyscef=nyscef,
            page_number=5,
            text=(
                "PARTIES\n"
                "10. Plaintiff Synthetic Harbor Freight LLC is a domestic "
                "limited liability company with its principal place of "
                "business in Kings County.\n"
                "11. Defendant Pier Lantern Depot Inc. is a domestic "
                "corporation.\n"
            ),
        ),
        _page(
            nyscef=nyscef,
            page_number=6,
            text=(
                "CAUSES OF ACTION\n"
                "20. Breach of contract is alleged in the fabricated pleading.\n"
            ),
        ),
    ]


def _party_role_hits(nyscef: int, *, parties_page: int = 5) -> dict:
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


class Phase1StructureMapCreationTests(unittest.TestCase):
    def test_generic_headings_bind_disjoint_paragraph_ranges(self) -> None:
        structure_map = cs.build_complaint_structure_map(
            {"pages": _fabricated_disjoint_pages(610)}
        )
        self.assertEqual(structure_map["schema_version"], SCHEMA)
        self.assertEqual(
            structure_map["selection"]["status"], cs.SELECTION_STATUS_SELECTED
        )
        doc = structure_map["documents"][0]
        by_key = {
            sec.get("match_key"): sec
            for sec in doc["sections"]
            if sec.get("match_key")
        }
        self.assertEqual(
            by_key["introduction"].get("paragraph_range"),
            {"start": 1, "end": 2, "contiguous": True},
        )
        self.assertEqual(
            by_key["jurisdiction_and_venue"].get("paragraph_range"),
            {"start": 3, "end": 3, "contiguous": True},
        )
        self.assertEqual(
            by_key["factual_background"].get("paragraph_range"),
            {"start": 5, "end": 6, "contiguous": True},
        )
        self.assertEqual(
            by_key["allegations"].get("paragraph_range"),
            {"start": 8, "end": 8, "contiguous": True},
        )
        self.assertEqual(
            by_key["parties"].get("paragraph_range"),
            {"start": 10, "end": 11, "contiguous": True},
        )
        # Gap paragraphs must not be invented across section boundaries.
        observed = {int(p["number"]) for p in doc["paragraph_numbers"]}
        self.assertNotIn(4, observed)
        self.assertNotIn(7, observed)
        self.assertNotIn(9, observed)
        self.assertIn(4, doc.get("missing_paragraph_numbers") or [])
        self.assertIn(7, doc.get("missing_paragraph_numbers") or [])

    def test_arabic_allegation_lines_not_stolen_as_section_headings(self) -> None:
        """``2. Fact.`` style allegation openers must remain paragraphs."""
        text = (
            "INTRODUCTION\n"
            "1. Fabricated introduction allegation.\n"
            "GENERAL BACKGROUND\n"
            "2. Fact. The fabricated lease was signed on a given date.\n"
            "PARTIES\n"
            "3. Plaintiff Synthetic Harbor Freight LLC is domestic.\n"
        )
        doc = cs.build_complaint_structure_map(
            {"pages": [_page(nyscef=611, page_number=1, text=text)]}
        )["documents"][0]
        keys = [h["match_key"] for h in doc["section_headings"] if h.get("match_key")]
        self.assertEqual(keys, ["introduction", "general_background", "parties"])
        self.assertEqual([p["number"] for p in doc["paragraph_numbers"]], [1, 2, 3])
        background = next(
            sec for sec in doc["sections"] if sec.get("match_key") == "general_background"
        )
        self.assertEqual(background.get("paragraph_numbers"), [2])

    def test_numbered_major_section_headings_still_recognized(self) -> None:
        text = (
            "14. PARTIES\n"
            "15. Plaintiff Synthetic Harbor Freight LLC is domestic.\n"
            "16. Defendant Pier Lantern Depot Inc. is domestic.\n"
            "17. FACTS\n"
            "18. On a fabricated date an event occurred.\n"
        )
        doc = cs.build_complaint_structure_map(
            {"pages": [_page(nyscef=612, page_number=1, text=text)]}
        )["documents"][0]
        keys = [h["match_key"] for h in doc["section_headings"]]
        self.assertEqual(keys, ["parties", "facts"])
        self.assertEqual([p["number"] for p in doc["paragraph_numbers"]], [15, 16, 18])


class Phase1PartyRoleAttachmentTests(unittest.TestCase):
    def test_attachment_preserves_all_relevant_disjoint_sections(self) -> None:
        structure_map = cs.build_complaint_structure_map(
            {"pages": _fabricated_disjoint_pages(620)}
        )
        roadmap = cs.select_party_role_complaint_roadmap_context(structure_map)
        self.assertIsNotNone(roadmap)
        assert roadmap is not None
        sections = roadmap["documents"][0]["sections"]
        kinds = [sec.get("kind") for sec in sections]
        self.assertEqual(kinds.count("overview"), 1)
        self.assertEqual(kinds.count("procedural_layout"), 1)
        self.assertEqual(kinds.count("factual_layout"), 2)
        self.assertEqual(kinds.count("parties"), 1)
        # Claims / causes of action stay out of the party-role roadmap.
        self.assertNotIn("claims", kinds)
        # Source order preserved across disjoint blocks.
        self.assertEqual(
            [sec.get("heading") for sec in sections],
            [
                "INTRODUCTION",
                "JURISDICTION AND VENUE",
                "FACTUAL BACKGROUND",
                "ALLEGATIONS",
                "PARTIES",
            ],
        )
        ranges = [
            (
                sec.get("kind"),
                (sec.get("paragraph_range") or {}).get("start"),
                (sec.get("paragraph_range") or {}).get("end"),
            )
            for sec in sections
        ]
        self.assertEqual(
            ranges,
            [
                ("overview", 1, 2),
                ("procedural_layout", 3, 3),
                ("factual_layout", 5, 6),
                ("factual_layout", 8, 8),
                ("parties", 10, 11),
            ],
        )
        # Must not collapse into one continuous invented span.
        for sec in sections:
            pr = sec.get("paragraph_range") or {}
            self.assertFalse(pr.get("start") == 1 and pr.get("end") == 11)

    def test_evidence_packet_attaches_full_disjoint_roadmap(self) -> None:
        structure_map = cs.build_complaint_structure_map(
            {"pages": _fabricated_disjoint_pages(630)}
        )
        packet = de.build_evidence_packet(
            "Who are the parties and what are their roles in this action?",
            _party_role_hits(630),
            complaint_structure_map=structure_map,
        )
        status = packet.get("complaint_structure_status") or {}
        self.assertTrue(status.get("ok"))
        self.assertTrue(status.get("attached"))
        self.assertEqual(status.get("schema_version"), SCHEMA)
        context = packet.get("complaint_structure_context")
        self.assertIsInstance(context, dict)
        assert isinstance(context, dict)
        sections = context["documents"][0]["sections"]
        self.assertEqual(len(sections), 5)
        headings = {str(sec.get("heading") or "").upper() for sec in sections}
        self.assertIn("INTRODUCTION", headings)
        self.assertIn("FACTUAL BACKGROUND", headings)
        self.assertIn("ALLEGATIONS", headings)
        self.assertIn("PARTIES", headings)
        self.assertIn("JURISDICTION AND VENUE", headings)


class Phase1CacheInvalidationTests(unittest.TestCase):
    def test_schema_version_bump_rejects_prior_derived_cache(self) -> None:
        """Derived caches keyed by schema_version must rebuild after builder changes."""
        self.assertEqual(SCHEMA, "complaint_structure_map.v2")
        stale = {
            "schema_version": "complaint_structure_map.v1",
            "documents": [],
            "selection": {"status": "selected", "controlling_nyscef_document_number": 1},
        }
        self.assertFalse(cs.is_current_structure_schema(stale))
        status = cs.structure_map_status(stale)
        self.assertFalse(status.get("ok"))
        self.assertEqual(
            status.get("reason"),
            "complaint_structure_map_stale_or_invalid_schema",
        )
        self.assertEqual(status.get("required_schema_version"), SCHEMA)

        packet = de.build_evidence_packet(
            "Who are the parties and what are their roles in this action?",
            _party_role_hits(640),
            complaint_structure_map=stale,
        )
        # Stale schema must not attach a party-role roadmap context.
        self.assertNotIn("complaint_structure_context", packet)
        stale_status = packet.get("complaint_structure_status") or {}
        self.assertFalse(stale_status.get("attached"))
        self.assertEqual(
            stale_status.get("reason"),
            "complaint_structure_map_stale_or_invalid_schema",
        )

    def test_current_structure_map_accepted_for_attachment(self) -> None:
        structure_map = cs.build_complaint_structure_map(
            {"pages": _fabricated_disjoint_pages(650)}
        )
        self.assertTrue(cs.is_current_structure_schema(structure_map))
        status = cs.structure_map_status(structure_map)
        self.assertTrue(status.get("ok"))
        roadmap = cs.select_party_role_complaint_roadmap_context(structure_map)
        self.assertIsNotNone(roadmap)
        assert roadmap is not None
        self.assertEqual(roadmap.get("schema_version"), SCHEMA)


if __name__ == "__main__":
    unittest.main()
