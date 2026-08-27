"""Fail-closed attorney review packets for verified active-matter corpora.

This is deliberately model-agnostic.  A caller may supply a candidate answer
only after a lawyer chooses the question; this module verifies that every
quoted proposition points to an existing canonical page and that the quoted
text appears on that page before rendering a review packet.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


PACKET_FILENAME = "active_matter_attorney_review_packet.md"
CONFIDENCE = {"strong", "related", "weak"}


class ActiveMatterReviewError(Exception):
    """Raised when a candidate is not safe to present for attorney review."""


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


def _require_string(payload: Mapping[str, Any], field: str) -> str:
    value = _text(payload.get(field))
    if not value:
        raise ActiveMatterReviewError(f"candidate {field} is required")
    return value


def load_page_index(page_records_path: Path | str) -> dict[tuple[int, int], Mapping[str, Any]]:
    """Load canonical page records into a stable NYSCEF-document/page index."""
    try:
        payload = json.loads(Path(page_records_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ActiveMatterReviewError("canonical page records are unreadable") from exc
    pages = payload.get("pages") if isinstance(payload, Mapping) else None
    if not isinstance(pages, list) or not pages:
        raise ActiveMatterReviewError("canonical page records contain no pages")
    index: dict[tuple[int, int], Mapping[str, Any]] = {}
    for page in pages:
        if not isinstance(page, Mapping):
            continue
        try:
            key = (int(page["nyscef_document_number"]), int(page["page_number"]))
        except (KeyError, TypeError, ValueError):
            continue
        if key in index:
            raise ActiveMatterReviewError(f"canonical page records duplicate NYSCEF {key[0]} page {key[1]}")
        index[key] = page
    if not index:
        raise ActiveMatterReviewError("canonical page records contain no usable citations")
    return index


def validate_candidate(candidate: Mapping[str, Any], page_index: Mapping[tuple[int, int], Mapping[str, Any]]) -> dict[str, Any]:
    """Validate a lawyer-requested candidate and enrich its citations from source."""
    if not isinstance(candidate, Mapping):
        raise ActiveMatterReviewError("candidate must be an object")
    case_id = _require_string(candidate, "case_id")
    question = _require_string(candidate, "question")
    answer = _require_string(candidate, "proposed_answer")
    findings = candidate.get("findings")
    if not isinstance(findings, list) or not findings:
        raise ActiveMatterReviewError("candidate requires at least one finding")
    verified: list[dict[str, Any]] = []
    for finding_number, raw_finding in enumerate(findings, start=1):
        if not isinstance(raw_finding, Mapping):
            raise ActiveMatterReviewError(f"finding {finding_number} must be an object")
        statement = _require_string(raw_finding, "statement")
        confidence = _text(raw_finding.get("confidence")).lower()
        if confidence not in CONFIDENCE:
            raise ActiveMatterReviewError(f"finding {finding_number} confidence must be strong, related, or weak")
        evidence = raw_finding.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ActiveMatterReviewError(f"finding {finding_number} requires evidence")
        checked_evidence: list[dict[str, Any]] = []
        for evidence_number, raw_evidence in enumerate(evidence, start=1):
            if not isinstance(raw_evidence, Mapping):
                raise ActiveMatterReviewError(f"finding {finding_number} evidence {evidence_number} must be an object")
            try:
                key = (int(raw_evidence["nyscef_document_number"]), int(raw_evidence["page_number"]))
            except (KeyError, TypeError, ValueError) as exc:
                raise ActiveMatterReviewError(f"finding {finding_number} evidence {evidence_number} needs NYSCEF document and page") from exc
            page = page_index.get(key)
            if page is None:
                raise ActiveMatterReviewError(f"finding {finding_number} cites unavailable NYSCEF {key[0]} page {key[1]}")
            quote = _text(raw_evidence.get("quote"))
            if len(quote) < 12:
                raise ActiveMatterReviewError(f"finding {finding_number} evidence {evidence_number} quote is too short")
            if quote.casefold() not in _text(page.get("text")).casefold():
                raise ActiveMatterReviewError(f"finding {finding_number} evidence {evidence_number} quote is not on NYSCEF {key[0]} page {key[1]}")
            checked_evidence.append({
                "nyscef_document_number": key[0],
                "page_number": key[1],
                "page_id": str(page.get("page_id") or ""),
                "source_filename": str(page.get("source_filename") or ""),
                "quote": quote,
            })
        verified.append({"statement": statement, "confidence": confidence, "evidence": checked_evidence})
    return {
        "schema_version": "active-matter-candidate.v1",
        "case_id": case_id,
        "question": question,
        "proposed_answer": answer,
        "findings": verified,
        "unresolved_questions": [_text(item) for item in candidate.get("unresolved_questions", []) if _text(item)],
        "limitations": _text(candidate.get("limitations")) or "Candidate is limited to the cited verified record; attorney review is required.",
        "attorney_approved": False,
    }


def render_attorney_review_packet(candidate: Mapping[str, Any]) -> str:
    """Render a compact, evidence-adjacent packet from a verified candidate."""
    lines = [
        "# Active-Matter Attorney Review Packet",
        "",
        "> **Status: CANDIDATE — NOT ATTORNEY-APPROVED.** Verify every cited page and applicable law before relying on this packet.",
        "",
        "## Question",
        "",
        str(candidate["question"]),
        "",
        "## Candidate Answer",
        "",
        str(candidate["proposed_answer"]),
        "",
        "## Findings and Record Proof",
        "",
    ]
    for number, finding in enumerate(candidate["findings"], start=1):
        lines.extend([f"### {number}. {finding['statement']}", "", f"**Confidence:** {finding['confidence'].capitalize()}", ""])
        for source in finding["evidence"]:
            lines.extend([
                f"- **NYSCEF {source['nyscef_document_number']}, PDF page {source['page_number']}** ({source['source_filename'] or 'verified filing'})",
                f"  > {source['quote']}",
            ])
        lines.append("")
    lines.extend(["## Open Questions", ""])
    lines.extend([f"- {item}" for item in candidate["unresolved_questions"]] or ["- None identified by the candidate."])
    lines.extend(["", "## Scope and Attorney Decision", "", f"- **Limitations:** {candidate['limitations']}", "- [ ] Accept", "- [ ] Revise", "- [ ] Reject", "- [ ] Investigate further", ""])
    return "\n".join(lines)


def build_review_packet(candidate_path: Path | str, page_records_path: Path | str, *, output_path: Path | str | None = None) -> Path:
    """Validate candidate JSON against canonical pages and write a review packet."""
    try:
        candidate = json.loads(Path(candidate_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ActiveMatterReviewError("candidate JSON is unreadable") from exc
    verified = validate_candidate(candidate, load_page_index(page_records_path))
    destination = Path(output_path) if output_path else Path(candidate_path).parent / PACKET_FILENAME
    destination.write_text(render_attorney_review_packet(verified), encoding="utf-8")
    return destination.resolve()
