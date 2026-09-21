"""Deterministic orchestration for record-grounded litigation reasoning.

This module does not decide a case or invent legal authority.  It classifies
the supplied record pages, runs the existing issue and contradiction engines,
and produces bounded reasoning metadata for the verified-draft model.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Iterable, Mapping, Sequence

from engines.contradiction_orchestrator import build_contradiction_analysis
from engines.issue_engine_v4 import build_issue_analysis


MOTION_RECOMMENDATION_RE = re.compile(
    r"\b(?:what|which)\s+motions?\b.{0,100}\b(?:consider|make|bring|file|move)\b|"
    r"\b(?:motion|motions)\s+(?:should|could|can)\s+(?:i|we|counsel)\s+"
    r"(?:consider|make|bring|file)\b",
    re.IGNORECASE | re.DOTALL,
)
MOTION_RESPONSE_RE = re.compile(
    r"\b(?:opponent|adversary|plaintiff|defendant|movant)\b.{0,100}"
    r"\b(?:made|filed|brought|served|moves?|motion)\b.{0,100}"
    r"\b(?:answer|oppose|opposition|respond|response|defeat)\b|"
    r"\b(?:answer|oppose|respond\s+to|defeat)\b.{0,80}\b(?:motion|application)\b",
    re.IGNORECASE | re.DOTALL,
)

_COURT_RE = re.compile(r"\b(?:decision\s+(?:and|&)\s+order|ordered|court\s+(?:held|finds|determines)|judgment)\b", re.I)
_EXPERT_RE = re.compile(r"\b(?:expert|professional\s+(?:engineer|surveyor)|I\s+(?:opine|conclude)|expert\s+(?:report|opinion))\b", re.I)
_REGULATORY_RE = re.compile(r"\b(?:DEC|Department\s+of\s+Environmental\s+Conservation|permit|regulatory|regulation|agency|certificate\s+of\s+occupancy|inspection|approval|violation)\b", re.I)
_VISUAL_RE = re.compile(r"\b(?:drawing|diagram|survey|site\s+plan|plan|photograph|aerial|map|sketch|measurement|dimension)\b", re.I)
_PLEADING_RE = re.compile(r"\b(?:complaint|answer|reply|counterclaim|cross[ -]?claim|affirmative\s+defense|wherefore)\b", re.I)
_ADVOCACY_RE = re.compile(r"\b(?:memorandum|brief|attorney\s+affirmation|counsel\s+(?:argues|affirms)|plaintiff\s+argues|defendant\s+contends)\b", re.I)
_AUTHORITY_CITATION_RE = re.compile(
    r"\b\d+\s+(?:N\.?Y\.?|A\.?D\.?(?:2d|3d)|Misc\.?(?:2d|3d))\s+\d+\b|"
    r"\bCPLR\s+\d+\b|\bECL\s+\d+(?:-\d+)*\b",
    re.I,
)
_REGULATORY_EXPERIENCE_RE = re.compile(r"\b(?:regulatory|agency|DEC|permit)\s+(?:experience|practice|work)\b", re.I)
_DESIGN_EXPERIENCE_RE = re.compile(r"\b(?:design|engineering|surveying|construction)\s+(?:experience|practice|work)\b", re.I)


def question_mode(question: str) -> str:
    if MOTION_RESPONSE_RE.search(question or ""):
        return "motion_response"
    if MOTION_RECOMMENDATION_RE.search(question or ""):
        return "motion_recommendation"
    return "strategic_analysis"


def _document_type(filename: str, text: str) -> str:
    haystack = f"{filename} {text[:1200]}"
    if _COURT_RE.search(haystack):
        return "court_ruling"
    if _EXPERT_RE.search(haystack):
        return "expert_opinion"
    if _REGULATORY_RE.search(haystack):
        return "regulatory_record"
    if _VISUAL_RE.search(haystack):
        return "visual_or_measurement_evidence"
    if _PLEADING_RE.search(haystack):
        return "pleading"
    if _ADVOCACY_RE.search(haystack):
        return "party_argument"
    return "other_record_material"


def classify_page(page: Mapping[str, Any]) -> dict[str, Any]:
    filename = str(page.get("filename") or "")
    text = " ".join(str(page.get("text") or "").split())
    source_type = _document_type(filename, text)
    return {
        "source_sha256": page.get("source_sha256"),
        "filename": filename,
        "page_number": page.get("page_number"),
        "source_type": source_type,
        "legal_status": (
            "record_evidence_not_law"
            if source_type in {"expert_opinion", "regulatory_record", "visual_or_measurement_evidence"}
            else "party_position_not_verified_law"
            if source_type in {"pleading", "party_argument"}
            else "court_ruling_limited_to_actual_holding"
            if source_type == "court_ruling"
            else "record_material"
        ),
        "contains_cited_authority": bool(_AUTHORITY_CITATION_RE.search(text)),
        "expert_qualification_scope": (
            "regulatory"
            if _REGULATORY_EXPERIENCE_RE.search(text)
            else "design_or_technical"
            if _DESIGN_EXPERIENCE_RE.search(text)
            else "not_established"
            if source_type == "expert_opinion"
            else None
        ),
    }

def _engine_documents(pages: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    documents = []
    for page in pages:
        classified = classify_page(page)
        source_type = classified["source_type"]
        documents.append({
            "filename": classified["filename"],
            "text": page.get("text") or "",
            "type": {
                "expert_opinion": "expert_report",
                "court_ruling": "decision",
                "regulatory_record": "agency_record",
                "visual_or_measurement_evidence": "authenticated_exhibit",
                "party_argument": "brief",
                "pleading": "pleading",
            }.get(source_type, "other"),
            "source_kind": (
                "authenticated_exhibit"
                if source_type == "visual_or_measurement_evidence"
                else ""
            ),
        })
    return documents


def build_reasoning_context(
    question: str,
    pages: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return bounded orchestration metadata for the model and audit trail."""
    classifications = [classify_page(page) for page in pages]
    counts = Counter(item["source_type"] for item in classifications)
    engine_documents = _engine_documents(pages)
    issue_analysis = build_issue_analysis(
        {"motion": question if "motion" in (question or "").casefold() else ""},
        documents=engine_documents,
    )
    contradiction_analysis = build_contradiction_analysis(engine_documents)
    return {
        "schema_version": "legalai-litigation-reasoning-context.v1",
        "question_mode": question_mode(question),
        "source_type_counts": dict(sorted(counts.items())),
        "page_classifications": classifications,
        "issue_engine": {
            "engine": issue_analysis.get("engine"),
            "motion_type": issue_analysis.get("motion_type"),
            "priority_ranking": issue_analysis.get("priority_ranking", [])[:8],
            "attorney_focus": issue_analysis.get("attorney_focus", [])[:5],
            "first_hand_evidence": issue_analysis.get("first_hand_evidence", {}),
        },
        "contradiction_engine": {
            "summary": contradiction_analysis.get("summary"),
            "cards": contradiction_analysis.get("cards", [])[:10],
        },
        "reasoning_rules": [
            "Expert opinions are evidence, not governing law.",
            "A qualification in design or engineering does not establish regulatory expertise.",
            "Cases, statutes, or regulations cited only in party papers remain attributed positions until independently verified.",
            "Regulatory records and drawings must be analyzed when supplied; their presence cannot be described as missing.",
            "Engine flags are retrieval and issue-prioritization signals, not independent proof.",
            "Answer the attorney's objective directly before supplying background.",
        ],
    }
