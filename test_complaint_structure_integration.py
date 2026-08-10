"""Focused Phase 2 tests: complaint-structure → party-role evidence/drafting.

Covers overview + intervening facts + party sections in party-role routing,
exclusion of unsupported ranges, OCR/ambiguity preservation, non-party
isolation, deterministic serialization, and explicit stale/absent degradation.
Uses only synthetic names — no Case-00 identities, gold answers, attorney
feedback, addresses, or benchmark prose.
"""

from __future__ import annotations

import unittest

import complaint_structure as cs
import engines.drafting_engine as de


def _page(
    *,
    nyscef: int,
    page_number: int,
    text: str,
    document_type: str = "complaint",
    source_filename: str | None = None,
) -> dict:
    filename = source_filename or f"doc_{nyscef}_{document_type}.pdf"
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


def _multi_section_map(nyscef: int = 801) -> dict:
    pages = [
        _page(
            nyscef=nyscef,
            page_number=1,
            text=(
                "SUPREME COURT OF THE STATE OF NEW YORK\n"
                "North Quay Logistics LLC v. Pier Gate Depot Inc.\n"
                "OVERVIEW\n"
                "1. This is an action for breach of a freight contract.\n"
                "2. The dispute concerns commercial carriage services.\n"
            ),
        ),
        _page(
            nyscef=nyscef,
            page_number=2,
            text=(
                "INTERVENING FACTS\n"
                "3. On a date certain the parties entered a carriage agreement.\n"
                "4. Delivery was not completed as scheduled.\n"
                "5. Damages followed from the missed delivery window.\n"
            ),
        ),
        _page(
            nyscef=nyscef,
            page_number=3,
            text=(
                "PARTIES\n"
                "6. Plaintiff North Quay Logistics LLC is a domestic limited "
                "liability company with its principal place of business in "
                "Kings County.\n"
                "7. Defendant Pier Gate Depot Inc. is a domestic corporation.\n"
            ),
        ),
    ]
    return cs.build_complaint_structure_map({"pages": pages})


def _party_role_hits_from_parties_only(nyscef: int = 801) -> dict:
    """Retrieval that only surfaces the PARTIES page (no overview/facts excerpts)."""
    return {
        "query": "Who are the parties and what are their roles?",
        "results": [
            {
                "result_id": "hit-parties",
                "page_id": f"nyscef-{nyscef:03d}-page-0003",
                "nyscef_document_number": nyscef,
                "pdf_page": 3,
                "source_filename": f"doc_{nyscef}.pdf",
                "document_type": "complaint",
                "excerpt": (
                    "PARTIES\n"
                    "6. Plaintiff North Quay Logistics LLC is a domestic limited "
                    "liability company with its principal place of business in "
                    "Kings County.\n"
                    "7. Defendant Pier Gate Depot Inc. is a domestic corporation.\n"
                ),
                "classifications": ["party_allegation"],
                "score": 0.9,
            }
        ],
    }


class PartyRoleRoadmapRoutingTests(unittest.TestCase):
    def test_party_role_packet_includes_overview_facts_and_parties(self) -> None:
        structure_map = _multi_section_map(810)
        self.assertEqual(
            structure_map["selection"]["status"], cs.SELECTION_STATUS_SELECTED
        )
        retrieval = _party_role_hits_from_parties_only(810)
        packet = de.build_evidence_packet(
            "Who are the parties and what are their roles in this action?",
            retrieval,
            complaint_structure_map=structure_map,
        )
        context = packet.get("complaint_structure_context")
        self.assertIsInstance(context, dict)
        self.assertEqual(context.get("schema_version"), cs.SCHEMA_VERSION)
        kinds = [
            sec.get("kind")
            for doc in context.get("documents") or []
            for sec in doc.get("sections") or []
        ]
        self.assertEqual(kinds.count("overview"), 1)
        self.assertEqual(kinds.count("factual_layout"), 1)
        self.assertEqual(kinds.count("parties"), 1)
        status = packet.get("complaint_structure_status") or {}
        self.assertTrue(status.get("ok"))
        self.assertTrue(status.get("attached"))

        synthesis = de.extract_party_role_expected_synthesis(packet)
        roadmap = next(
            item for item in synthesis if item["category"] == "complaint_roadmap"
        )
        self.assertTrue(roadmap.get("structure_backed"))
        headings = {h.lower() for h in roadmap.get("section_headings") or []}
        self.assertTrue(any("overview" in h for h in headings))
        self.assertTrue(any("intervening" in h for h in headings))
        self.assertTrue(any("parties" in h for h in headings))
        ranges = roadmap.get("section_ranges") or []
        self.assertTrue(any(item.get("kind") == "factual_layout" for item in ranges))
        factual = next(item for item in ranges if item.get("kind") == "factual_layout")
        self.assertEqual(factual.get("start"), 3)
        self.assertEqual(factual.get("end"), 5)

    def test_answer_quotations_do_not_enter_evidence_roadmap(self) -> None:
        complaint = _page(
            nyscef=815,
            page_number=1,
            text=(
                "OVERVIEW\n"
                "1. This is an action for breach of a freight contract.\n"
                "INTERVENING FACTS\n"
                "2. Delivery failed on the contracted date.\n"
                "PARTIES\n"
                "3. Plaintiff North Quay Logistics LLC is a domestic LLC.\n"
                "4. Defendant Pier Gate Depot Inc. is a domestic corporation.\n"
            ),
            document_type="complaint",
        )
        answer = _page(
            nyscef=816,
            page_number=1,
            text=(
                "OVERVIEW\n"
                "1. Denies complaint paragraph 1.\n"
                "INTERVENING FACTS\n"
                "2. Denies complaint paragraph 2.\n"
                "PARTIES\n"
                "3. Admits paragraph 3.\n"
                "4. Denies paragraph 4.\n"
            ),
            document_type="answer",
        )
        structure_map = cs.build_complaint_structure_map({"pages": [complaint, answer]})
        packet = de.build_evidence_packet(
            "Who are the parties and what are their roles?",
            _party_role_hits_from_parties_only(815),
            complaint_structure_map=structure_map,
        )
        context = packet.get("complaint_structure_context")
        self.assertIsInstance(context, dict)
        self.assertEqual(len(context["documents"]), 1)
        self.assertEqual(context["documents"][0]["nyscef_document_number"], 815)
        page_ids = {
            pid
            for sec in context["documents"][0]["sections"]
            for pid in sec.get("page_ids") or []
        }
        self.assertTrue(all(pid.startswith("nyscef-815-") for pid in page_ids))
        self.assertFalse(any(pid.startswith("nyscef-816-") for pid in page_ids))

    def test_unsupported_ranges_excluded_and_uncertainty_preserved(self) -> None:
        text = (
            "OVERVIEW\n"
            "1. Opening allegation.\n"
            "3. Skipped number is not invented.\n"
            "INTERVENING FACTS\n"
            "P A R T I E S\n"
            "10. Plaintiff Cedar Wharf Brokers LP is a limited liability partnership.\n"
        )
        structure_map = cs.build_complaint_structure_map(
            {"pages": [_page(nyscef=820, page_number=1, text=text)]}
        )
        doc = structure_map["documents"][0]
        overview = next(sec for sec in doc["sections"] if sec["kind"] == "overview")
        self.assertIsNone(overview.get("paragraph_range"))
        self.assertEqual(overview.get("paragraph_numbers"), [1, 3])
        self.assertNotIn(2, overview.get("paragraph_numbers") or [])
        self.assertIn(
            "noncontiguous_paragraph_numbers", overview.get("uncertainty") or []
        )
        facts = next(sec for sec in doc["sections"] if sec["kind"] == "factual_layout")
        self.assertIsNone(facts.get("paragraph_range"))
        self.assertIn(
            "range_not_inferred_from_heading_alone", facts.get("uncertainty") or []
        )
        parties = next(sec for sec in doc["sections"] if sec["kind"] == "parties")
        self.assertEqual(parties.get("heading"), "P A R T I E S")
        self.assertTrue(
            any(
                u.get("kind") == "ocr_heading_variation"
                for u in doc.get("uncertainties") or []
            )
        )

        roadmap = cs.select_party_role_complaint_roadmap_context(structure_map)
        self.assertIsNotNone(roadmap)
        selected = roadmap["documents"][0]["sections"]
        overview_sel = next(sec for sec in selected if sec["kind"] == "overview")
        self.assertIsNone(overview_sel.get("paragraph_range"))
        self.assertEqual(overview_sel.get("paragraph_numbers"), [1, 3])
        # Document-level uncertainties preserved on roadmap payload.
        self.assertTrue(roadmap["documents"][0].get("uncertainties"))

    def test_non_party_question_not_polluted_with_structure_context(self) -> None:
        structure_map = _multi_section_map(830)
        retrieval = {
            "query": "What relief is requested in the wherefore clause?",
            "results": [
                {
                    "result_id": "hit-wherefore",
                    "page_id": "nyscef-830-page-0004",
                    "nyscef_document_number": 830,
                    "pdf_page": 4,
                    "source_filename": "doc_830.pdf",
                    "document_type": "complaint",
                    "excerpt": "WHEREFORE plaintiff demands judgment.\n",
                    "classifications": ["legal_position"],
                    "score": 0.8,
                }
            ],
            "complaint_structure_map": structure_map,
            "complaint_structure_context": cs.select_party_role_complaint_roadmap_context(
                structure_map
            ),
        }
        packet = de.build_evidence_packet(
            "What relief is requested in the wherefore clause?",
            retrieval,
            complaint_structure_map=structure_map,
        )
        self.assertNotIn("complaint_structure_context", packet)
        self.assertNotIn("complaint_structure_status", packet)

    def test_structure_backed_validator_requires_intervening_section(self) -> None:
        structure_map = _multi_section_map(840)
        packet = de.build_evidence_packet(
            "Identify the parties and their roles.",
            _party_role_hits_from_parties_only(840),
            complaint_structure_map=structure_map,
        )
        expected = de.extract_party_role_expected_attributes(packet)
        synthesis = de.extract_party_role_expected_synthesis(packet, expected)
        roadmap = next(
            item for item in synthesis if item["category"] == "complaint_roadmap"
        )
        self.assertTrue(roadmap.get("structure_backed"))
        roster = (
            "Plaintiff North Quay Logistics LLC is a domestic limited liability "
            "company with its principal place of business in Kings County. "
            "Defendant Pier Gate Depot Inc. is a domestic corporation."
        )
        incomplete = roster + (
            " The complaint parties roadmap appears in the PARTIES section at "
            "paragraphs 6 through 7."
        )
        missing = de.find_missing_party_role_synthesis(
            {"proposed_answer": incomplete, "propositions": []},
            synthesis,
        )
        self.assertIn(
            "complaint_roadmap",
            {item["category"] for item in missing},
        )
        complete = roster + (
            " The complaint roadmap preserves OVERVIEW paragraphs 1 through 2, "
            "INTERVENING FACTS paragraphs 3 through 5, and PARTIES paragraphs "
            "6 through 7."
        )
        missing_ok = de.find_missing_party_role_synthesis(
            {"proposed_answer": complete, "propositions": []},
            synthesis,
        )
        self.assertNotIn(
            "complaint_roadmap",
            {item["category"] for item in missing_ok},
        )
        invented = complete + " See also paragraphs 40 through 55."
        missing_invented = de.find_missing_party_role_synthesis(
            {"proposed_answer": invented, "propositions": []},
            synthesis,
        )
        self.assertIn(
            "complaint_roadmap",
            {item["category"] for item in missing_invented},
        )

    def test_deterministic_serialization_stable(self) -> None:
        structure_map = _multi_section_map(850)
        roadmap_a = cs.select_party_role_complaint_roadmap_context(structure_map)
        roadmap_b = cs.select_party_role_complaint_roadmap_context(structure_map)
        self.assertEqual(
            cs.serialize_structure_map(roadmap_a),
            cs.serialize_structure_map(roadmap_b),
        )
        packet = de.build_evidence_packet(
            "Who are the parties and what are their roles?",
            _party_role_hits_from_parties_only(850),
            complaint_structure_map=structure_map,
        )
        first = de._stable_json(packet)
        second = de._stable_json(packet)
        self.assertEqual(first, second)
        self.assertIn("complaint_structure_context", first)

    def test_stale_or_absent_structure_degrades_explicitly(self) -> None:
        retrieval = _party_role_hits_from_parties_only(860)
        absent = de.build_evidence_packet(
            "Who are the parties and what are their roles?",
            retrieval,
            complaint_structure_map=None,
        )
        status_absent = absent.get("complaint_structure_status") or {}
        self.assertFalse(status_absent.get("ok"))
        self.assertFalse(status_absent.get("attached"))
        self.assertEqual(
            status_absent.get("reason"), "complaint_structure_map_absent"
        )
        self.assertNotIn("complaint_structure_context", absent)

        stale = de.build_evidence_packet(
            "Who are the parties and what are their roles?",
            retrieval,
            complaint_structure_map={
                "schema_version": "complaint_structure_map.v0",
                "documents": [],
            },
        )
        status_stale = stale.get("complaint_structure_status") or {}
        self.assertFalse(status_stale.get("ok"))
        self.assertFalse(status_stale.get("attached"))
        self.assertEqual(
            status_stale.get("reason"),
            "complaint_structure_map_stale_or_invalid_schema",
        )
        self.assertNotIn("complaint_structure_context", stale)

        # Stale pre-attached retrieval context must not be silently reused.
        polluted = dict(retrieval)
        polluted["complaint_structure_context"] = {
            "schema_version": "complaint_structure_map.v0",
            "documents": [
                {
                    "document_id": "nyscef-860",
                    "sections": [
                        {
                            "heading": "PARTIES",
                            "kind": "parties",
                            "paragraph_range": {"start": 1, "end": 99, "contiguous": True},
                        }
                    ],
                }
            ],
        }
        rejected = de.build_evidence_packet(
            "Who are the parties and what are their roles?",
            polluted,
        )
        self.assertNotIn("complaint_structure_context", rejected)
        self.assertEqual(
            (rejected.get("complaint_structure_status") or {}).get("reason"),
            "complaint_structure_context_stale_or_invalid_schema",
        )


class RealisticAttachmentAcceptanceTests(unittest.TestCase):
    """Live-defect acceptance: attachable three-part roadmap despite OCR/chrome."""

    def test_evidence_packet_attaches_three_part_roadmap(self) -> None:
        nyscef = 880
        pages = [
            _page(
                nyscef=nyscef,
                page_number=1,
                text=(
                    "FILED: COUNTY CLERK 02/01/2024\n"
                    "NYSCEF DOC. NO. 1\n"
                    "RECEIVED NYSCEF: 02/01/2024\n"
                    "NATURE OF THE ACTION\n"
                    "1. This pleading summarizes a commercial dispute.\n"
                    "2. The dispute concerns carriage services.\n"
                ),
            ),
            _page(
                nyscef=nyscef,
                page_number=2,
                text=(
                    "FILED: COUNTY CLERK 02/01/2024\n"
                    "NYSCEF DOC. NO. 1\n"
                    "F A C T U A L   B A C K G R O U N D\n"
                    "3. The parties entered an agreement.\n"
                    "4. Performance failed on the contracted date.\n"
                ),
            ),
            _page(
                nyscef=nyscef,
                page_number=3,
                text=(
                    "FILED: COUNTY CLERK 02/01/2024\n"
                    "NYSCEF DOC. NO. 1\n"
                    "RELEVANT FACTS\n"
                    "5. Damages followed from nonperformance.\n"
                    # Unobserved 6 — must remain a gap.
                    "7. Remediation costs followed.\n"
                ),
            ),
            _page(
                nyscef=nyscef,
                page_number=4,
                text=(
                    "FILED: COUNTY CLERK 02/01/2024\n"
                    "NYSCEF DOC. NO. 1\n"
                    "THE PARTIES\n"
                    "8. Plaintiff North Quay Logistics LLC is a domestic LLC.\n"
                    "9. Defendant Pier Gate Depot Inc. is a domestic corporation.\n"
                ),
            ),
        ]
        answer = _page(
            nyscef=nyscef + 1,
            page_number=1,
            text=(
                "ANSWER\n"
                "NATURE OF THE ACTION\n"
                "1. Denies paragraph 1 of the complaint.\n"
                "RELEVANT FACTS\n"
                "5. Denies paragraph 5.\n"
                "THE PARTIES\n"
                "8. Admits paragraph 8.\n"
            ),
            document_type="answer",
        )
        structure_map = cs.build_complaint_structure_map({"pages": pages + [answer]})
        retrieval = {
            "query": "Who are the parties and what are their roles?",
            "results": [
                {
                    "result_id": "hit-parties",
                    "page_id": f"nyscef-{nyscef:03d}-page-0004",
                    "nyscef_document_number": nyscef,
                    "pdf_page": 4,
                    "source_filename": f"doc_{nyscef}.pdf",
                    "document_type": "complaint",
                    "excerpt": (
                        "THE PARTIES\n"
                        "8. Plaintiff North Quay Logistics LLC is a domestic LLC.\n"
                        "9. Defendant Pier Gate Depot Inc. is a domestic corporation.\n"
                    ),
                    "classifications": ["party_allegation"],
                    "score": 0.9,
                }
            ],
        }
        packet = de.build_evidence_packet(
            "Who are the parties and what are their roles in this action?",
            retrieval,
            complaint_structure_map=structure_map,
        )
        status = packet.get("complaint_structure_status") or {}
        self.assertTrue(status.get("ok"))
        self.assertTrue(status.get("attached"))
        self.assertIsNone(status.get("reason"))
        context = packet.get("complaint_structure_context")
        self.assertIsInstance(context, dict)
        kinds = [
            sec.get("kind")
            for doc in context.get("documents") or []
            for sec in doc.get("sections") or []
        ]
        self.assertEqual(kinds.count("overview"), 1)
        self.assertGreaterEqual(kinds.count("factual_layout"), 2)
        self.assertEqual(kinds.count("parties"), 1)
        factual = [
            sec
            for doc in context["documents"]
            for sec in doc["sections"]
            if sec.get("kind") == "factual_layout"
        ]
        headings_upper = {str(sec.get("heading") or "").upper() for sec in factual}
        self.assertTrue(
            any("FACTUAL" in h or "F A C T U A L" in h for h in headings_upper)
        )
        self.assertTrue(any("RELEVANT FACTS" in h for h in headings_upper))
        relevant = next(
            sec for sec in factual if "RELEVANT" in str(sec.get("heading") or "").upper()
        )
        self.assertEqual(relevant.get("paragraph_numbers"), [5, 7])
        self.assertIsNone(relevant.get("paragraph_range"))
        self.assertEqual(context["documents"][0]["nyscef_document_number"], nyscef)
        page_ids = {
            pid
            for sec in context["documents"][0]["sections"]
            for pid in sec.get("page_ids") or []
        }
        self.assertFalse(any(str(pid).startswith(f"nyscef-{nyscef + 1:03d}-") for pid in page_ids))

    def test_non_party_question_regression_unaffected(self) -> None:
        structure_map = _multi_section_map(885)
        packet = de.build_evidence_packet(
            "What damages are alleged in the complaint?",
            {
                "query": "What damages are alleged in the complaint?",
                "results": [
                    {
                        "result_id": "hit-damages",
                        "page_id": "nyscef-885-page-0002",
                        "nyscef_document_number": 885,
                        "pdf_page": 2,
                        "source_filename": "doc_885.pdf",
                        "document_type": "complaint",
                        "excerpt": (
                            "4. Delivery was not completed as scheduled.\n"
                            "5. Damages followed from the missed delivery window.\n"
                        ),
                        "classifications": ["factual_allegation"],
                        "score": 0.8,
                    }
                ],
            },
            complaint_structure_map=structure_map,
        )
        self.assertNotIn("complaint_structure_context", packet)
        self.assertNotIn("complaint_structure_status", packet)


class SectionBindingExtractionTests(unittest.TestCase):
    def test_sections_bind_observed_paragraphs_without_invention(self) -> None:
        structure_map = _multi_section_map(870)
        doc = structure_map["documents"][0]
        by_kind = {sec["kind"]: sec for sec in doc["sections"]}
        self.assertEqual(
            by_kind["overview"].get("paragraph_range"),
            {"start": 1, "end": 2, "contiguous": True},
        )
        self.assertEqual(
            by_kind["factual_layout"].get("paragraph_range"),
            {"start": 3, "end": 5, "contiguous": True},
        )
        self.assertEqual(
            by_kind["parties"].get("paragraph_range"),
            {"start": 6, "end": 7, "contiguous": True},
        )
        for sec in doc["sections"]:
            self.assertTrue(sec.get("page_ids"))
            self.assertEqual(
                sec.get("provenance", {}).get("heading_marker"), sec.get("heading")
            )
            self.assertEqual(sec.get("provenance", {}).get("document_id"), doc["document_id"])


if __name__ == "__main__":
    unittest.main()
