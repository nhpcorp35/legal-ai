"""Focused regression: stale pre-attached roadmap context fallback.

Proves build_evidence_packet ignores stale/invalid pre-attached
complaint_structure_context and selects a fresh party-role roadmap from the
current validated structure_payload when structure_map_status is otherwise ok,
while remaining fail-closed when no usable current map exists.

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


def _multi_section_map(nyscef: int = 901) -> dict:
    pages = [
        _page(
            nyscef=nyscef,
            page_number=1,
            text=(
                "SUPREME COURT OF THE STATE OF NEW YORK\n"
                "Cedar Pier Freight LLC v. Lantern Quay Depot Inc.\n"
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
                "6. Plaintiff Cedar Pier Freight LLC is a domestic limited "
                "liability company with its principal place of business in "
                "Kings County.\n"
                "7. Defendant Lantern Quay Depot Inc. is a domestic corporation.\n"
            ),
        ),
    ]
    return cs.build_complaint_structure_map({"pages": pages})


def _party_role_hits(nyscef: int = 901) -> dict:
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
                    "6. Plaintiff Cedar Pier Freight LLC is a domestic limited "
                    "liability company with its principal place of business in "
                    "Kings County.\n"
                    "7. Defendant Lantern Quay Depot Inc. is a domestic corporation.\n"
                ),
                "classifications": ["party_allegation"],
                "score": 0.9,
            }
        ],
    }


def _stale_v1_preattached_context(nyscef: int = 901) -> dict:
    """Pre-attached context on a prior schema that must never be reused."""
    return {
        "schema_version": "complaint_structure_map.v1",
        "documents": [
            {
                "document_id": f"nyscef-{nyscef}",
                "sections": [
                    {
                        "heading": "STALE V1 PARTIES ONLY",
                        "kind": "parties",
                        "paragraph_range": {
                            "start": 1,
                            "end": 99,
                            "contiguous": True,
                        },
                    }
                ],
            }
        ],
    }


class StaleContextFallbackRegressionTests(unittest.TestCase):
    def test_current_v2_map_alone_attaches_structure_backed_context(self) -> None:
        structure_map = _multi_section_map(910)
        expected = cs.select_party_role_complaint_roadmap_context(structure_map)
        self.assertIsInstance(expected, dict)

        packet = de.build_evidence_packet(
            "Who are the parties and what are their roles?",
            _party_role_hits(910),
            complaint_structure_map=structure_map,
        )
        status = packet.get("complaint_structure_status") or {}
        context = packet.get("complaint_structure_context")

        self.assertTrue(status.get("ok"))
        self.assertTrue(status.get("attached"))
        self.assertIsNone(status.get("reason"))
        self.assertEqual(context, expected)
        self.assertEqual(context.get("schema_version"), cs.SCHEMA_VERSION)

    def test_stale_v1_preattached_falls_back_to_current_v2_map(self) -> None:
        structure_map = _multi_section_map(920)
        expected = cs.select_party_role_complaint_roadmap_context(structure_map)
        self.assertIsInstance(expected, dict)

        retrieval = _party_role_hits(920)
        retrieval["complaint_structure_context"] = _stale_v1_preattached_context(920)

        packet = de.build_evidence_packet(
            "Who are the parties and what are their roles?",
            retrieval,
            complaint_structure_map=structure_map,
        )
        status = packet.get("complaint_structure_status") or {}
        context = packet.get("complaint_structure_context")

        self.assertTrue(status.get("ok"))
        self.assertTrue(status.get("attached"))
        self.assertIsNone(status.get("reason"))
        self.assertEqual(context, expected)
        self.assertEqual(context.get("schema_version"), cs.SCHEMA_VERSION)
        headings = {
            str(sec.get("heading") or "")
            for doc in (context.get("documents") or [])
            for sec in (doc.get("sections") or [])
        }
        self.assertNotIn("STALE V1 PARTIES ONLY", headings)

    def test_stale_context_without_valid_map_remains_fail_closed(self) -> None:
        retrieval = _party_role_hits(930)
        retrieval["complaint_structure_context"] = _stale_v1_preattached_context(930)

        packet = de.build_evidence_packet(
            "Who are the parties and what are their roles?",
            retrieval,
            complaint_structure_map=None,
        )
        status = packet.get("complaint_structure_status") or {}

        self.assertNotIn("complaint_structure_context", packet)
        self.assertFalse(status.get("ok"))
        self.assertFalse(status.get("attached"))
        self.assertEqual(
            status.get("reason"),
            "complaint_structure_context_stale_or_invalid_schema",
        )
        self.assertEqual(status.get("schema_version"), "complaint_structure_map.v1")


if __name__ == "__main__":
    unittest.main()
