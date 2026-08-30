import json
from pathlib import Path

import pytest

from verified_case_review import VerifiedCaseReviewError, load_page_index, validate_candidate


def test_accepts_literal_filename_page_citation(tmp_path: Path):
    pages = tmp_path / "pages.jsonl"
    pages.write_text(json.dumps({"filename": "Complaint.pdf", "page_number": 2, "text": "Plaintiff seeks damages for breach of contract."}) + "\n")
    candidate = {"case_id": "case", "question": "What are the claims?", "proposed_answer": "The verified complaint seeks contract damages.", "findings": [{"statement": "The complaint seeks contract damages.", "evidence": [{"filename": "Complaint.pdf", "page_number": 2, "quote": "seeks damages for breach of contract"}]}]}
    assert validate_candidate(candidate, load_page_index(pages))["case_id"] == "case"


def test_rejects_quote_not_in_cited_page(tmp_path: Path):
    pages = tmp_path / "pages.jsonl"
    pages.write_text(json.dumps({"filename": "Complaint.pdf", "page_number": 2, "text": "Only verified text."}) + "\n")
    candidate = {"case_id": "case", "question": "Q", "proposed_answer": "A", "findings": [{"statement": "S", "evidence": [{"filename": "Complaint.pdf", "page_number": 2, "quote": "Invented text here"}]}]}
    with pytest.raises(VerifiedCaseReviewError):
        validate_candidate(candidate, load_page_index(pages))
