from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from active_matter_review import ActiveMatterReviewError, build_review_packet, load_page_index, validate_candidate


PAGES = {"pages": [{"nyscef_document_number": 2, "page_number": 1, "page_id": "nyscef-2-page-0001", "source_filename": "complaint.pdf", "text": "The verified complaint alleges a waterfront access dispute between the parties."}]}
CANDIDATE = {"case_id": "NY-Nassau-613561-2026-Desousa-v-Rennick", "question": "What does the complaint allege?", "proposed_answer": "It alleges a waterfront access dispute.", "findings": [{"statement": "The complaint alleges a waterfront access dispute.", "confidence": "strong", "evidence": [{"nyscef_document_number": 2, "page_number": 1, "quote": "waterfront access dispute between the parties"}]}]}


class ActiveMatterReviewTests(unittest.TestCase):
    def test_verifies_quote_and_renders_evidence_adjacent_packet(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pages = root / "pages.json"; pages.write_text(json.dumps(PAGES), encoding="utf-8")
            candidate = root / "candidate.json"; candidate.write_text(json.dumps(CANDIDATE), encoding="utf-8")
            packet = build_review_packet(candidate, pages)
            text = packet.read_text(encoding="utf-8")
            self.assertIn("NYSCEF 2, PDF page 1", text)
            self.assertIn("NOT ATTORNEY-APPROVED", text)
            self.assertIn("Strong", text)

    def test_refuses_a_quote_not_present_on_cited_page(self):
        invalid = json.loads(json.dumps(CANDIDATE))
        invalid["findings"][0]["evidence"][0]["quote"] = "not in the verified record"
        with self.assertRaisesRegex(ActiveMatterReviewError, "quote is not"):
            validate_candidate(invalid, load_page_index_from_payload())

    def test_refuses_unavailable_citation(self):
        invalid = json.loads(json.dumps(CANDIDATE))
        invalid["findings"][0]["evidence"][0]["page_number"] = 99
        with self.assertRaisesRegex(ActiveMatterReviewError, "unavailable"):
            validate_candidate(invalid, load_page_index_from_payload())


def load_page_index_from_payload():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "pages.json"; path.write_text(json.dumps(PAGES), encoding="utf-8")
        return load_page_index(path)
