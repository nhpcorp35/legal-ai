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


def test_rejects_unqualified_pleading_inconsistency(tmp_path: Path):
    pages = tmp_path / "pages.jsonl"
    pages.write_text(json.dumps({"filename": "Answer.pdf", "page_number": 1, "text": "A party pleads two alternative claims."}) + "\n")
    candidate = {"case_id": "case", "question": "Q", "proposed_answer": "The two claims are inconsistent.", "findings": [{"statement": "The pleading is internally inconsistent.", "evidence": [{"filename": "Answer.pdf", "page_number": 1, "quote": "two alternative claims"}]}]}
    with pytest.raises(VerifiedCaseReviewError, match="alternative-pleading context"):
        validate_candidate(candidate, load_page_index(pages))


def test_allows_conditional_pleading_inconsistency_with_open_question(tmp_path: Path):
    pages = tmp_path / "pages.jsonl"
    pages.write_text(json.dumps({"filename": "Answer.pdf", "page_number": 1, "text": "A party pleads two alternative claims."}) + "\n")
    candidate = {"case_id": "case", "question": "Q", "proposed_answer": "The excerpts appear inconsistent unless they are pleaded in the alternative.", "findings": [{"statement": "The excerpts present different claimed relief.", "evidence": [{"filename": "Answer.pdf", "page_number": 1, "quote": "two alternative claims"}]}], "unresolved_questions": ["Does the full pleading identify these positions as alternative pleading or upon information and belief?"]}
    validated = validate_candidate(candidate, load_page_index(pages))
    assert validated["unresolved_questions"]
