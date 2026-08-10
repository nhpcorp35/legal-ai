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
) -> dict:
    return {
        "nyscef_document_number": nyscef,
        "page_number": page_number,
        "page_id": f"nyscef-{nyscef:03d}-page-{page_number:04d}",
        "text": text,
        "extraction_method": "native",
        "pdf_page_number": page_number,
        "source_filename": f"doc_{nyscef}.pdf",
        "source_path": f"/synthetic/doc_{nyscef}.pdf",
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
        self.assertTrue(
            any(u["kind"] == "ambiguous_heading" for u in doc["uncertainties"])
        )


class MultipleDocumentTests(unittest.TestCase):
    def test_structures_not_mixed_across_documents(self) -> None:
        pages = [
            _page(
                nyscef=20,
                page_number=1,
                text="PARTIES\n1. Plaintiff Alpha LLC is domestic.\n2. Defendant Beta Inc. is domestic.\n",
            ),
            _page(
                nyscef=21,
                page_number=1,
                text=(
                    "OVERVIEW\n"
                    "10. Overview paragraph for the second filing.\n"
                    "INTERVENING FACTS\n"
                    "11. Intervening paragraph for the second filing.\n"
                ),
            ),
        ]
        payload = cs.build_complaint_structure_map({"pages": pages})
        self.assertEqual([d["document_id"] for d in payload["documents"]], [
            "nyscef-020",
            "nyscef-021",
        ])
        first = payload["documents"][0]
        second = payload["documents"][1]
        self.assertEqual([p["number"] for p in first["paragraph_numbers"]], [1, 2])
        self.assertEqual([p["number"] for p in second["paragraph_numbers"]], [10, 11])
        self.assertEqual(
            [h["match_key"] for h in first["section_headings"]],
            ["parties"],
        )
        self.assertEqual(
            [h["match_key"] for h in second["section_headings"]],
            ["overview", "intervening_facts"],
        )
        # Provenance stays document-local.
        self.assertTrue(
            all(p["nyscef_document_number"] == 20 for p in first["source_pages"])
        )
        self.assertTrue(
            all(p["nyscef_document_number"] == 21 for p in second["source_pages"])
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
            ),
            _page(
                nyscef=41,
                page_number=1,
                text="OVERVIEW\n2. Two.\n",
            ),
        ]
        # Reverse input order must not change output.
        a = cs.build_complaint_structure_map({"pages": list(reversed(pages))})
        b = cs.build_complaint_structure_map({"pages": pages})
        self.assertEqual(cs.serialize_structure_map(a), cs.serialize_structure_map(b))
        self.assertEqual(a, b)
        # sort_keys deterministic JSON
        first = cs.serialize_structure_map(a)
        second = cs.serialize_structure_map(a)
        self.assertEqual(first, second)
        self.assertTrue(first.endswith("\n"))


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
        self.assertEqual(structure["documents"][0]["document_id"], "nyscef-007")
        self.assertEqual(
            [p["number"] for p in structure["documents"][0]["paragraph_numbers"]],
            [1],
        )


if __name__ == "__main__":
    unittest.main()
