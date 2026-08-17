"""Focused synthetic tests for complaint structure extraction and cache schema."""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

import complaint_structure as cs


def _load_rebuild_cli():
    path = Path(__file__).resolve().parent / "scripts" / "rebuild_case00_derived.py"
    spec = importlib.util.spec_from_file_location("rebuild_case00_derived", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    repo_root = Path(__file__).resolve().parent
    if str(repo_root) not in os.sys.path:
        os.sys.path.insert(0, str(repo_root))
    os.sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


CLI = _load_rebuild_cli()


def _page(
    *,
    nyscef: int,
    page_number: int,
    text: str,
    document_type: str = "complaint",
    source_filename: str | None = None,
    document_title: str | None = None,
    document_classification: str | None = None,
) -> dict:
    filename = source_filename or f"doc_{nyscef}_{document_type or 'filing'}.pdf"
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
        "document_title": document_title or filename,
        "document_classification": document_classification or document_type,
    }


class MultiSectionComplaintTests(unittest.TestCase):
    def test_multi_section_headings_and_paragraphs(self) -> None:
        text = (
            "INTRODUCTION\n"
            "1. This action seeks declaratory relief.\n"
            "PARTIES\n"
            "2. Plaintiff Synthetic Carrier LLC is a domestic company.\n"
            "3. Defendant Harbor Depot Inc. is a domestic corporation.\n"
            "FACTS\n"
            "4. On a date certain the parties entered an agreement.\n"
            "WHEREFORE\n"
        )
        payload = cs.build_complaint_structure_map({"pages": [_page(nyscef=10, page_number=1, text=text)]})
        self.assertEqual(payload["schema_version"], cs.SCHEMA_VERSION)
        doc = payload["documents"][0]
        keys = [h["match_key"] for h in doc["section_headings"] if not h["ambiguous"]]
        self.assertEqual(
            keys,
            ["introduction", "parties", "facts", "wherefore"],
        )
        nums = [p["number"] for p in doc["paragraph_numbers"]]
        self.assertEqual(nums, [1, 2, 3, 4])
        self.assertEqual(
            doc["contiguous_ranges"],
            [{"start": 1, "end": 4, "observed_numbers": [1, 2, 3, 4]}],
        )
        self.assertEqual(doc["missing_paragraph_numbers"], [])
        self.assertEqual(doc["noncontiguous_sequences"], [])


class OverviewInterveningFactsPartyTests(unittest.TestCase):
    def test_overview_intervening_facts_and_parties(self) -> None:
        text = (
            "OVERVIEW\n"
            "1. This pleading summarizes the dispute.\n"
            "INTERVENING FACTS\n"
            "2. An intervening event occurred after filing.\n"
            "PARTIES\n"
            "3. Plaintiff River Bend Logistics LP resides in Oneida County.\n"
        )
        doc = cs.build_complaint_structure_map(
            {"pages": [_page(nyscef=11, page_number=1, text=text)]}
        )["documents"][0]
        keys = [h["match_key"] for h in doc["section_headings"]]
        self.assertEqual(keys, ["overview", "intervening_facts", "parties"])
        self.assertEqual([p["number"] for p in doc["paragraph_numbers"]], [1, 2, 3])
        markers = [h["observed_marker"] for h in doc["section_headings"]]
        self.assertEqual(markers, ["OVERVIEW", "INTERVENING FACTS", "PARTIES"])


class OcrHeadingTests(unittest.TestCase):
    def test_ocr_spaced_heading_preserves_observed_marker(self) -> None:
        text = (
            "P A R T I E S\n"
            "1. Plaintiff Oak Pier Transit LLC is a domestic LLC.\n"
        )
        doc = cs.build_complaint_structure_map(
            {"pages": [_page(nyscef=12, page_number=1, text=text)]}
        )["documents"][0]
        self.assertEqual(len(doc["section_headings"]), 1)
        heading = doc["section_headings"][0]
        self.assertEqual(heading["match_key"], "parties")
        self.assertEqual(heading["observed_marker"], "P A R T I E S")
        self.assertFalse(heading["ambiguous"])
        self.assertTrue(
            any(u["kind"] == "ocr_heading_variation" for u in doc["uncertainties"])
        )


class NoncontiguousMissingParagraphTests(unittest.TestCase):
    def test_missing_and_noncontiguous_numbers_are_explicit(self) -> None:
        text = (
            "PARTIES\n"
            "1. First observed allegation.\n"
            "2. Second observed allegation.\n"
            "5. Fifth observed allegation.\n"
            "6. Sixth observed allegation.\n"
        )
        doc = cs.build_complaint_structure_map(
            {"pages": [_page(nyscef=13, page_number=1, text=text)]}
        )["documents"][0]
        self.assertEqual([p["number"] for p in doc["paragraph_numbers"]], [1, 2, 5, 6])
        self.assertEqual(doc["missing_paragraph_numbers"], [3, 4])
        self.assertEqual(
            doc["contiguous_ranges"],
            [
                {"start": 1, "end": 2, "observed_numbers": [1, 2]},
                {"start": 5, "end": 6, "observed_numbers": [5, 6]},
            ],
        )
        self.assertEqual(
            doc["noncontiguous_sequences"],
            [
                {"observed_numbers": [1, 2]},
                {"observed_numbers": [5, 6]},
            ],
        )
        # No fabricated summarized 1-6 range.
        starts_ends = {(r["start"], r["end"]) for r in doc["contiguous_ranges"]}
        self.assertNotIn((1, 6), starts_ends)

    def test_ocr_spaced_paragraph_delimiter_tolerated(self) -> None:
        text = "PARTIES\n1 . Plaintiff Synthetic One LLC is domestic.\n"
        doc = cs.build_complaint_structure_map(
            {"pages": [_page(nyscef=14, page_number=1, text=text)]}
        )["documents"][0]
        self.assertEqual(doc["paragraph_numbers"][0]["number"], 1)
        self.assertEqual(doc["paragraph_numbers"][0]["observed_marker"], "1.")


class AmbiguityTests(unittest.TestCase):
    def test_heading_with_trailing_prose_marked_ambiguous(self) -> None:
        text = (
            "PARTIES Plaintiff and Defendant are identified below without a break.\n"
            "1. Plaintiff Cedar Wharf LLC is a domestic company.\n"
        )
        doc = cs.build_complaint_structure_map(
            {"pages": [_page(nyscef=15, page_number=1, text=text)]}
        )["documents"][0]
        self.assertTrue(doc["section_headings"])
        self.assertTrue(doc["section_headings"][0]["ambiguous"])
        self.assertEqual(
            doc["section_headings"][0]["ambiguity_note"],
            "heading_token_with_trailing_prose",
        )
        # Bounded heading label only — no absorbed trailing prose.
        self.assertEqual(doc["section_headings"][0]["observed_marker"], "PARTIES")
        self.assertNotIn("Plaintiff", doc["section_headings"][0]["observed_marker"])
        self.assertTrue(
            any(u["kind"] == "ambiguous_heading" for u in doc["uncertainties"])
        )


class ControllingComplaintSelectionTests(unittest.TestCase):
    def test_complaint_plus_answers_quoting_headings_uses_only_complaint(self) -> None:
        complaint_text = (
            "OVERVIEW\n"
            "1. This action concerns a freight dispute.\n"
            "PARTIES\n"
            "2. Plaintiff River Bend Carrier LLC is a domestic company.\n"
            "3. Defendant Harbor Pier Depot Inc. is a domestic corporation.\n"
            "FACTS\n"
            "4. The parties entered a carriage agreement.\n"
        )
        answer_a = (
            "ANSWER\n"
            "OVERVIEW\n"
            "1. Denies the allegations of complaint paragraph 1.\n"
            "PARTIES\n"
            "2. Admits paragraph 2 only as to residence.\n"
            "3. Denies knowledge of paragraph 3.\n"
            "FACTS\n"
            "4. Denies paragraph 4.\n"
        )
        answer_b = (
            "VERIFIED ANSWER\n"
            "PARTIES\n"
            "10. Repeats and realleges responses to paragraphs 2 through 3.\n"
            "FACTS\n"
            "11. Denies each and every allegation in complaint paragraph 4.\n"
        )
        pages = [
            _page(
                nyscef=101,
                page_number=1,
                text=complaint_text,
                document_type="complaint",
                source_filename="synthetic_summons_complaint_101.pdf",
            ),
            _page(
                nyscef=118,
                page_number=1,
                text=answer_a,
                document_type="answer",
                source_filename="synthetic_answer_118.pdf",
            ),
            _page(
                nyscef=127,
                page_number=1,
                text=answer_b,
                document_type="answer",
                source_filename="synthetic_amended_answer_127.pdf",
            ),
        ]
        payload = cs.build_complaint_structure_map({"pages": pages})
        self.assertEqual(payload["selection"]["status"], cs.SELECTION_STATUS_SELECTED)
        self.assertEqual(payload["selection"]["controlling_nyscef_document_number"], 101)
        self.assertEqual(len(payload["documents"]), 1)
        doc = payload["documents"][0]
        self.assertEqual(doc["document_id"], "nyscef-101")
        self.assertEqual(
            [h["match_key"] for h in doc["section_headings"] if not h["ambiguous"]],
            ["overview", "parties", "facts"],
        )
        self.assertEqual([p["number"] for p in doc["paragraph_numbers"]], [1, 2, 3, 4])
        # Answer paragraph numbers / provenance must not appear.
        self.assertTrue(
            all(p["page_id"].startswith("nyscef-101-") for p in doc["paragraph_numbers"])
        )
        self.assertTrue(
            all(h["page_id"].startswith("nyscef-101-") for h in doc["section_headings"])
        )
        roadmap = cs.select_party_role_complaint_roadmap_context(payload)
        self.assertIsNotNone(roadmap)
        self.assertEqual(len(roadmap["documents"]), 1)
        self.assertEqual(roadmap["documents"][0]["nyscef_document_number"], 101)
        kinds = [sec["kind"] for sec in roadmap["documents"][0]["sections"]]
        self.assertEqual(kinds.count("overview"), 1)
        self.assertEqual(kinds.count("parties"), 1)
        self.assertEqual(kinds.count("factual_layout"), 1)

    def test_ambiguous_multiple_complaints_fail_closed(self) -> None:
        pages = [
            _page(
                nyscef=201,
                page_number=1,
                text="PARTIES\n1. Plaintiff Alpha LLC is domestic.\n",
                document_type="complaint",
                source_filename="complaint_201.pdf",
            ),
            _page(
                nyscef=205,
                page_number=1,
                text="PARTIES\n1. Plaintiff Beta LLC is domestic.\n",
                document_type="complaint",
                source_filename="amended_complaint_205.pdf",
            ),
        ]
        payload = cs.build_complaint_structure_map({"pages": pages})
        self.assertEqual(payload["selection"]["status"], cs.SELECTION_STATUS_AMBIGUOUS)
        self.assertEqual(payload["documents"], [])
        self.assertEqual(
            payload["selection"]["candidate_nyscef_document_numbers"],
            [201, 205],
        )
        status = cs.structure_map_status(payload)
        self.assertFalse(status["ok"])
        self.assertEqual(status["reason"], "controlling_complaint_ambiguous")
        self.assertIsNone(cs.select_party_role_complaint_roadmap_context(payload))

    def test_absent_complaint_metadata_unavailable(self) -> None:
        pages = [
            _page(
                nyscef=301,
                page_number=1,
                text="PARTIES\n1. Plaintiff Gamma LLC is domestic.\n",
                document_type="",
                source_filename="doc_301.pdf",
                document_classification="",
            )
        ]
        # Clear title/classification signals that would otherwise classify.
        pages[0]["document_title"] = ""
        pages[0]["document_classification"] = ""
        payload = cs.build_complaint_structure_map({"pages": pages})
        self.assertEqual(payload["selection"]["status"], cs.SELECTION_STATUS_UNAVAILABLE)
        self.assertEqual(payload["selection"]["reason"], "complaint_metadata_absent")
        self.assertEqual(payload["documents"], [])
        status = cs.structure_map_status(payload)
        self.assertFalse(status["ok"])
        self.assertEqual(status["reason"], "complaint_metadata_absent")

    def test_answer_only_corpus_unavailable(self) -> None:
        pages = [
            _page(
                nyscef=401,
                page_number=1,
                text=(
                    "PARTIES\n"
                    "1. Denies complaint paragraph 1.\n"
                    "FACTS\n"
                    "2. Denies complaint paragraph 2.\n"
                ),
                document_type="answer",
                source_filename="verified_answer_401.pdf",
            ),
            _page(
                nyscef=402,
                page_number=1,
                text="PARTIES\n5. Affiant quotes complaint parties heading.\n",
                document_type="affidavit",
                source_filename="affidavit_402.pdf",
            ),
        ]
        payload = cs.build_complaint_structure_map({"pages": pages})
        self.assertEqual(payload["selection"]["status"], cs.SELECTION_STATUS_UNAVAILABLE)
        self.assertEqual(payload["documents"], [])
        self.assertIn("answer", payload["selection"]["reason"])
        self.assertIsNone(cs.select_party_role_complaint_roadmap_context(payload))

    def test_inventory_metadata_selects_controlling_complaint(self) -> None:
        pages = [
            {
                "nyscef_document_number": 501,
                "page_number": 1,
                "page_id": "nyscef-501-page-0001",
                "text": "PARTIES\n1. Plaintiff Delta Transit LP is domestic.\n",
                "extraction_method": "native",
                "source_filename": "501.pdf",
            },
            {
                "nyscef_document_number": 502,
                "page_number": 1,
                "page_id": "nyscef-502-page-0001",
                "text": "PARTIES\n1. Denies paragraph 1 of the complaint.\n",
                "extraction_method": "native",
                "source_filename": "502.pdf",
            },
        ]
        inventory = {
            "filings": [
                {
                    "nyscef_document_number": 501,
                    "filename": "matter_summons_complaint_501.pdf",
                    "document_type": "complaint",
                },
                {
                    "nyscef_document_number": 502,
                    "filename": "matter_answer_502.pdf",
                    "document_type": "answer",
                },
            ]
        }
        payload = cs.build_complaint_structure_map(
            {"pages": pages}, filing_inventory=inventory
        )
        self.assertEqual(payload["selection"]["status"], cs.SELECTION_STATUS_SELECTED)
        self.assertEqual(payload["selection"]["controlling_nyscef_document_number"], 501)
        self.assertEqual(payload["documents"][0]["document_id"], "nyscef-501")


class RealisticMultiPageRoadmapTests(unittest.TestCase):
    """Acceptance: noisy multi-page controlling complaint → three-part roadmap."""

    def _noisy_controlling_complaint_pages(self, nyscef: int = 901) -> list[dict]:
        return [
            _page(
                nyscef=nyscef,
                page_number=1,
                text=(
                    "FILED: KINGS COUNTY CLERK 01/15/2024 10:00 AM\n"
                    "NYSCEF DOC. NO. 1                    INDEX NO. 500001/2024\n"
                    "RECEIVED NYSCEF: 01/15/2024\n"
                    "SUPREME COURT OF THE STATE OF NEW YORK\n"
                    "COUNTY OF KINGS\n"
                    "                      Nature of the Action.\n"
                    "1. This is an action for breach of a freight contract.\n"
                    "2. Plaintiff seeks damages arising from failed deliveries.\n"
                    "page 1 of 4\n"
                ),
                document_type="complaint",
                source_filename=f"summons_complaint_{nyscef}.pdf",
                document_title="Summons and Complaint",
                document_classification="summons_and_complaint",
            ),
            _page(
                nyscef=nyscef,
                page_number=2,
                text=(
                    "FILED: KINGS COUNTY CLERK 01/15/2024 10:00 AM\n"
                    "NYSCEF DOC. NO. 1                    INDEX NO. 500001/2024\n"
                    "RECEIVED NYSCEF: 01/15/2024\n"
                    "                   F A C T U A L   B A C K G R O U N D\n"
                    "3. On a date certain the parties entered a carriage agreement.\n"
                    "4. Delivery was not completed as scheduled.\n"
                    "page 2 of 4\n"
                ),
                document_type="complaint",
                source_filename=f"summons_complaint_{nyscef}.pdf",
            ),
            _page(
                nyscef=nyscef,
                page_number=3,
                text=(
                    "FILED: KINGS COUNTY CLERK 01/15/2024 10:00 AM\n"
                    "NYSCEF DOC. NO. 1                    INDEX NO. 500001/2024\n"
                    "RECEIVED NYSCEF: 01/15/2024\n"
                    "STATEMENT OF FACTS\n"
                    "5. Damages followed from the missed delivery window.\n"
                    "6. A second missed window occurred thereafter.\n"
                    # Gap: paragraph 7 is unobserved — must not be bridged.
                    "8. Additional remediation costs were incurred.\n"
                    "page 3 of 4\n"
                ),
                document_type="complaint",
                source_filename=f"summons_complaint_{nyscef}.pdf",
            ),
            _page(
                nyscef=nyscef,
                page_number=4,
                text=(
                    "FILED: KINGS COUNTY CLERK 01/15/2024 10:00 AM\n"
                    "NYSCEF DOC. NO. 1                    INDEX NO. 500001/2024\n"
                    "RECEIVED NYSCEF: 01/15/2024\n"
                    "                            THE PARTIES\n"
                    "9. Plaintiff North Quay Logistics LLC is a domestic LLC.\n"
                    "10. Defendant Pier Gate Depot Inc. is a domestic corporation.\n"
                    "page 4 of 4\n"
                ),
                document_type="complaint",
                source_filename=f"summons_complaint_{nyscef}.pdf",
            ),
        ]

    def test_three_part_roadmap_from_noisy_multipage_complaint(self) -> None:
        pages = self._noisy_controlling_complaint_pages(901)
        answer = _page(
            nyscef=918,
            page_number=1,
            text=(
                "VERIFIED ANSWER\n"
                "Nature of the Action.\n"
                "1. Denies the allegations of complaint paragraph 1.\n"
                "STATEMENT OF FACTS\n"
                "5. Denies complaint paragraph 5.\n"
                "THE PARTIES\n"
                "9. Admits paragraph 9 only as to residence.\n"
            ),
            document_type="answer",
            source_filename="verified_answer_918.pdf",
        )
        payload = cs.build_complaint_structure_map({"pages": pages + [answer]})
        self.assertEqual(payload["selection"]["status"], cs.SELECTION_STATUS_SELECTED)
        self.assertEqual(payload["selection"]["controlling_nyscef_document_number"], 901)
        self.assertEqual(len(payload["documents"]), 1)

        doc = payload["documents"][0]
        keys = [h["match_key"] for h in doc["section_headings"] if h.get("match_key")]
        self.assertIn("nature_of_the_action", keys)
        self.assertIn("factual_background", keys)
        self.assertIn("statement_of_facts", keys)
        self.assertIn("parties", keys)
        # Varied intervening headings both classified as factual layout.
        factual_sections = [
            sec for sec in doc["sections"] if sec.get("kind") == "factual_layout"
        ]
        self.assertGreaterEqual(len(factual_sections), 2)
        factual_headings = {sec.get("heading", "").upper() for sec in factual_sections}
        self.assertTrue(any("F A C T U A L" in h or "FACTUAL" in h for h in factual_headings))
        self.assertTrue(any("STATEMENT OF FACTS" in h for h in factual_headings))

        # Exact observed ranges survive; gap at 7 is not bridged.
        by_key = {sec.get("match_key"): sec for sec in doc["sections"]}
        self.assertEqual(
            by_key["nature_of_the_action"].get("paragraph_range"),
            {"start": 1, "end": 2, "contiguous": True},
        )
        self.assertEqual(
            by_key["factual_background"].get("paragraph_range"),
            {"start": 3, "end": 4, "contiguous": True},
        )
        statement = by_key["statement_of_facts"]
        self.assertEqual(statement.get("paragraph_numbers"), [5, 6, 8])
        self.assertIsNone(statement.get("paragraph_range"))
        self.assertIn(
            "noncontiguous_paragraph_numbers", statement.get("uncertainty") or []
        )
        self.assertNotIn(7, statement.get("paragraph_numbers") or [])
        self.assertEqual(
            by_key["parties"].get("paragraph_range"),
            {"start": 9, "end": 10, "contiguous": True},
        )
        self.assertIn(7, doc.get("missing_paragraph_numbers") or [])

        roadmap = cs.select_party_role_complaint_roadmap_context(payload)
        self.assertIsNotNone(roadmap)
        kinds = [sec["kind"] for sec in roadmap["documents"][0]["sections"]]
        self.assertGreaterEqual(kinds.count("overview"), 1)
        self.assertGreaterEqual(kinds.count("factual_layout"), 2)
        self.assertGreaterEqual(kinds.count("parties"), 1)
        # Answer quotations excluded from roadmap provenance.
        page_ids = {
            pid
            for sec in roadmap["documents"][0]["sections"]
            for pid in sec.get("page_ids") or []
        }
        self.assertTrue(all(pid.startswith("nyscef-901-") for pid in page_ids))
        self.assertFalse(any(pid.startswith("nyscef-918-") for pid in page_ids))

    def test_heading_variants_and_adjacent_paragraph_detection(self) -> None:
        text = (
            "RELEVANT FACTS\n"
            "1. First relevant event occurred.\n"
            "FACTUAL ALLEGATIONS\n"
            "2. A second allegation follows.\n"
            "PARTIES 3. Plaintiff Cedar Wharf Brokers LP is domestic.\n"
        )
        doc = cs.build_complaint_structure_map(
            {"pages": [_page(nyscef=902, page_number=1, text=text)]}
        )["documents"][0]
        keys = [h["match_key"] for h in doc["section_headings"]]
        self.assertEqual(
            keys, ["relevant_facts", "factual_allegations", "parties"]
        )
        self.assertEqual([p["number"] for p in doc["paragraph_numbers"]], [1, 2, 3])
        parties = next(sec for sec in doc["sections"] if sec["kind"] == "parties")
        self.assertEqual(parties.get("paragraph_numbers"), [3])
        self.assertEqual(
            next(
                h for h in doc["section_headings"] if h["match_key"] == "parties"
            ).get("ambiguity_note"),
            "heading_adjacent_to_paragraph_text",
        )

    def test_deterministic_output_stable_for_noisy_complaint(self) -> None:
        pages = self._noisy_controlling_complaint_pages(903)
        a = cs.build_complaint_structure_map({"pages": list(pages)})
        b = cs.build_complaint_structure_map({"pages": list(reversed(pages))})
        self.assertEqual(cs.serialize_structure_map(a), cs.serialize_structure_map(b))
        roadmap_a = cs.select_party_role_complaint_roadmap_context(a)
        roadmap_b = cs.select_party_role_complaint_roadmap_context(b)
        self.assertEqual(
            cs.serialize_structure_map(roadmap_a),
            cs.serialize_structure_map(roadmap_b),
        )


class MultipleDocumentTests(unittest.TestCase):
    def test_structures_not_mixed_across_non_complaint_filings(self) -> None:
        pages = [
            _page(
                nyscef=20,
                page_number=1,
                text="PARTIES\n1. Plaintiff Alpha LLC is domestic.\n2. Defendant Beta Inc. is domestic.\n",
                document_type="complaint",
                source_filename="complaint_20.pdf",
            ),
            _page(
                nyscef=21,
                page_number=1,
                text=(
                    "OVERVIEW\n"
                    "10. Overview paragraph quoted in an answer.\n"
                    "INTERVENING FACTS\n"
                    "11. Intervening paragraph quoted in an answer.\n"
                ),
                document_type="answer",
                source_filename="answer_21.pdf",
            ),
        ]
        payload = cs.build_complaint_structure_map({"pages": pages})
        self.assertEqual([d["document_id"] for d in payload["documents"]], [
            "nyscef-020",
        ])
        first = payload["documents"][0]
        self.assertEqual([p["number"] for p in first["paragraph_numbers"]], [1, 2])
        self.assertEqual(
            [h["match_key"] for h in first["section_headings"]],
            ["parties"],
        )
        self.assertTrue(
            all(p["nyscef_document_number"] == 20 for p in first["source_pages"])
        )


class ProvenanceTests(unittest.TestCase):
    def test_source_page_provenance_and_markers(self) -> None:
        pages = [
            _page(
                nyscef=30,
                page_number=1,
                text="PARTIES\n1. First page allegation.\n",
            ),
            _page(
                nyscef=30,
                page_number=2,
                text="FACTS\n2. Second page allegation.\n",
            ),
        ]
        doc = cs.build_complaint_structure_map({"pages": pages})["documents"][0]
        self.assertEqual(
            doc["source_pages"],
            [
                {
                    "nyscef_document_number": 30,
                    "page_id": "nyscef-030-page-0001",
                    "page_number": 1,
                },
                {
                    "nyscef_document_number": 30,
                    "page_id": "nyscef-030-page-0002",
                    "page_number": 2,
                },
            ],
        )
        self.assertEqual(doc["paragraph_numbers"][0]["page_id"], "nyscef-030-page-0001")
        self.assertEqual(doc["paragraph_numbers"][1]["page_id"], "nyscef-030-page-0002")
        self.assertEqual(doc["section_headings"][0]["observed_marker"], "PARTIES")
        self.assertEqual(doc["section_headings"][1]["observed_marker"], "FACTS")


class DeterministicSerializationTests(unittest.TestCase):
    def test_serialization_is_byte_stable(self) -> None:
        pages = [
            _page(
                nyscef=40,
                page_number=1,
                text="PARTIES\n1. One.\n3. Three.\n",
                document_type="complaint",
                source_filename="complaint_40.pdf",
            ),
            _page(
                nyscef=41,
                page_number=1,
                text="OVERVIEW\n2. Two quoted in answer.\n",
                document_type="answer",
                source_filename="answer_41.pdf",
            ),
        ]
        # Reverse input order must not change output.
        a = cs.build_complaint_structure_map({"pages": list(reversed(pages))})
        b = cs.build_complaint_structure_map({"pages": pages})
        self.assertEqual(cs.serialize_structure_map(a), cs.serialize_structure_map(b))
        self.assertEqual(a, b)
        self.assertEqual(a["selection"]["controlling_nyscef_document_number"], 40)
        self.assertEqual(len(a["documents"]), 1)
        # sort_keys deterministic JSON
        first = cs.serialize_structure_map(a)
        second = cs.serialize_structure_map(a)
        self.assertEqual(first, second)
        self.assertTrue(first.endswith("\n"))

    def test_noisy_ocr_heading_deterministic_with_answers_present(self) -> None:
        pages = [
            _page(
                nyscef=45,
                page_number=1,
                text="P A R T I E S\n1. Plaintiff Oak Pier Transit LLC is domestic.\n",
                document_type="complaint",
            ),
            _page(
                nyscef=46,
                page_number=1,
                text="PARTIES\n1. Answer denies paragraph 1.\n",
                document_type="answer",
            ),
        ]
        a = cs.build_complaint_structure_map({"pages": pages})
        b = cs.build_complaint_structure_map({"pages": list(reversed(pages))})
        self.assertEqual(cs.serialize_structure_map(a), cs.serialize_structure_map(b))
        self.assertEqual(a["documents"][0]["section_headings"][0]["observed_marker"], "P A R T I E S")


class StaleCacheRejectionTests(unittest.TestCase):
    def test_missing_structure_map_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            case_root = Path(tmp) / "case"
            case_root.mkdir()
            inv = case_root / "nyscef_filing_inventory.json"
            inv.write_text(json.dumps({"filings": []}) + "\n", encoding="utf-8")
            qdir = case_root / "derived" / "question-text"
            qdir.mkdir(parents=True)
            (qdir / "questions.json").write_text(
                json.dumps({"Q1": "Who are the parties?"}) + "\n",
                encoding="utf-8",
            )
            paths = CLI.resolve_derived_paths(case_root)
            CLI.atomic_write_json(paths["page_records"], {"pages": []})
            CLI.atomic_write_json(paths["exhibit_map"], {"filings": []})
            CLI.atomic_write_json(
                paths["case_map"], {"case_map": CLI.mb.empty_case_map()}
            )
            report = CLI.validate_generator_inputs(case_root, inventory_path=inv)
            self.assertFalse(report["ok"])
            self.assertTrue(
                any("complaint structure" in e.lower() or "complaint_structure" in e
                    for e in report["errors"])
            )

    def test_wrong_schema_version_rejected_as_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            case_root = Path(tmp) / "case"
            case_root.mkdir()
            inv = case_root / "nyscef_filing_inventory.json"
            inv.write_text(json.dumps({"filings": []}) + "\n", encoding="utf-8")
            qdir = case_root / "derived" / "question-text"
            qdir.mkdir(parents=True)
            (qdir / "questions.json").write_text(
                json.dumps({"Q1": "Who are the parties?"}) + "\n",
                encoding="utf-8",
            )
            paths = CLI.resolve_derived_paths(case_root)
            CLI.atomic_write_json(paths["page_records"], {"pages": []})
            CLI.atomic_write_json(paths["exhibit_map"], {"filings": []})
            CLI.atomic_write_json(
                paths["case_map"], {"case_map": CLI.mb.empty_case_map()}
            )
            CLI.atomic_write_json(
                paths["complaint_structure"],
                {"schema_version": "complaint_structure_map.v0", "documents": []},
            )
            report = CLI.validate_generator_inputs(case_root, inventory_path=inv)
            self.assertFalse(report["ok"])
            self.assertTrue(any("stale" in e.lower() for e in report["errors"]))
            self.assertEqual(
                report["required_complaint_structure_schema"],
                cs.SCHEMA_VERSION,
            )

    def test_current_schema_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            case_root = Path(tmp) / "case"
            case_root.mkdir()
            inv = case_root / "nyscef_filing_inventory.json"
            inv.write_text(json.dumps({"filings": []}) + "\n", encoding="utf-8")
            qdir = case_root / "derived" / "question-text"
            qdir.mkdir(parents=True)
            (qdir / "questions.json").write_text(
                json.dumps({"Q1": "Who are the parties?"}) + "\n",
                encoding="utf-8",
            )
            paths = CLI.resolve_derived_paths(case_root)
            CLI.atomic_write_json(paths["page_records"], {"pages": []})
            CLI.atomic_write_json(paths["exhibit_map"], {"filings": []})
            CLI.atomic_write_json(
                paths["case_map"], {"case_map": CLI.mb.empty_case_map()}
            )
            CLI.atomic_write_json(
                paths["complaint_structure"],
                cs.empty_complaint_structure_map(),
            )
            report = CLI.validate_generator_inputs(case_root, inventory_path=inv)
            self.assertTrue(report["ok"], report["errors"])
            self.assertTrue(cs.is_current_structure_schema(
                json.loads(paths["complaint_structure"].read_text(encoding="utf-8"))
            ))


class RebuildIntegrationStructureTests(unittest.TestCase):
    def test_build_derived_payloads_includes_structure_map(self) -> None:
        documents = [
            {
                "nyscef_document_number": 7,
                "filename": "synthetic_complaint.pdf",
                "title": "synthetic_complaint.pdf",
                "type": "complaint",
                "path": "/synthetic/synthetic_complaint.pdf",
                "pages": [
                    {
                        "page_number": 1,
                        "page_id": "nyscef-007-page-0001",
                        "text": "PARTIES\n1. Plaintiff Gamma LLC is domestic.\n",
                        "extraction_method": "native",
                    }
                ],
                "exhibit_segments": [],
                "uncertain_exhibit_boundaries": [],
            }
        ]
        payloads = CLI.build_derived_payloads(documents)
        self.assertIn("complaint_structure", payloads)
        structure = payloads["complaint_structure"]
        self.assertEqual(structure["schema_version"], cs.SCHEMA_VERSION)
        self.assertEqual(structure["selection"]["status"], cs.SELECTION_STATUS_SELECTED)
        self.assertEqual(structure["selection"]["controlling_nyscef_document_number"], 7)
        self.assertEqual(structure["documents"][0]["document_id"], "nyscef-007")
        self.assertEqual(
            [p["number"] for p in structure["documents"][0]["paragraph_numbers"]],
            [1],
        )
        page = payloads["page_records"]["pages"][0]
        self.assertEqual(page["document_type"], "complaint")
        self.assertEqual(page["source_filename"], "synthetic_complaint.pdf")
        self.assertTrue(page.get("document_title"))
        self.assertTrue(page.get("document_classification"))


class ContractRoadmapScopeRegressionTests(unittest.TestCase):
    def test_answer_packet_ranges_do_not_pollute_complaint_roadmap(self) -> None:
        complaint = {
            "note": "synthetic complaint roadmap",
            "schema_version": cs.SCHEMA_VERSION,
            "documents": [
                {
                    "document_id": "synthetic-complaint",
                    "nyscef_document_number": 700,
                    "sections": [
                        {
                            "heading": "PARTIES",
                            "kind": "parties",
                            "paragraph_numbers": [10, 11],
                            "paragraph_range": {
                                "start": 10,
                                "end": 11,
                                "contiguous": True,
                            },
                        }
                    ],
                }
            ],
        }
        answer_contract = {
            "required_kinds": ["answer_text", "supporting_evidence", "limitations"],
            "required_categories": ["attorney_packet"],
            "required_ranges": [
                {"kind": "answer_text", "heading": "answer text", "start": 0, "end": 1},
                {
                    "kind": "supporting_evidence",
                    "heading": "supporting evidence",
                    "start": 0,
                    "end": 10,
                },
                {"kind": "limitations", "heading": "limitations", "start": 0, "end": 5},
            ],
        }

        merged = cs.merge_contract_structure_requirements(
            complaint,
            answer_contract,
        )

        self.assertIsNotNone(merged)
        assert merged is not None
        sections = merged["documents"][0]["sections"]
        self.assertEqual([section["kind"] for section in sections], ["parties"])
        self.assertEqual(merged["contract_required_kinds"], [])
        self.assertEqual(
            merged["contract_required_categories"],
            ["attorney_packet"],
        )
        self.assertIsNone(
            cs.merge_contract_structure_requirements(None, answer_contract)
        )

    def test_complaint_scoped_contract_range_is_retained(self) -> None:
        merged = cs.merge_contract_structure_requirements(
            None,
            {
                "required_kinds": ["factual_layout"],
                "required_ranges": [
                    {
                        "kind": "factual_layout",
                        "heading": "FACTUAL BACKGROUND",
                        "start": 20,
                        "end": 22,
                    }
                ],
            },
        )
        self.assertIsNotNone(merged)
        assert merged is not None
        section = merged["documents"][0]["sections"][0]
        self.assertEqual(section["kind"], "factual_layout")
        self.assertEqual(section["paragraph_numbers"], [20, 21, 22])


if __name__ == "__main__":
    unittest.main()
