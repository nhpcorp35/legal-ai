"""Fail-closed attorney review packets for verified filename/page case sources."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


class VerifiedCaseReviewError(Exception):
    """Raised when a candidate is not safe to present for attorney review."""


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


def _required(payload: Mapping[str, Any], field: str) -> str:
    value = _text(payload.get(field))
    if not value:
        raise VerifiedCaseReviewError(f"candidate {field} is required")
    return value


def _validate_alternative_pleading_context(
    answer: str,
    findings: list[dict[str, Any]],
    unresolved_questions: list[str],
) -> None:
    """Keep alleged pleading contradictions conditional until their context is verified.

    A difference between pleaded positions is not, by itself, an inconsistency:
    it may be alternative or hypothetical pleading.  A candidate that calls such
    a difference inconsistent must therefore preserve that question for review
    and identify the missing pleading context.
    """
    conclusion_text = " ".join(
        [answer, *(finding["statement"] for finding in findings)]
    ).casefold()
    if not any(term in conclusion_text for term in ("inconsisten", "contradict")):
        return

    context_text = " ".join(unresolved_questions).casefold()
    if not any(
        term in context_text
        for term in (
            "alternative pleading",
            "alternative or hypothetical",
            "information and belief",
            "full pleading",
            "factual basis",
        )
    ):
        raise VerifiedCaseReviewError(
            "candidate labels pleaded positions inconsistent without preserving "
            "the alternative-pleading context as an open question"
        )


def load_page_index(path: Path | str) -> dict[tuple[str, int], Mapping[str, Any]]:
    """Load immutable JSONL page records keyed by filename and page number."""
    try:
        rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError) as exc:
        raise VerifiedCaseReviewError("verified page records are unreadable") from exc
    index: dict[tuple[str, int], Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        filename, page = _text(row.get("filename")), row.get("page_number")
        if not filename or not isinstance(page, int) or page < 1 or not _text(row.get("text")):
            continue
        key = (filename, page)
        if key in index:
            raise VerifiedCaseReviewError("verified page records contain duplicate filename/page citations")
        index[key] = row
    if not index:
        raise VerifiedCaseReviewError("verified page records contain no usable pages")
    return index


def validate_candidate(candidate: Mapping[str, Any], pages: Mapping[tuple[str, int], Mapping[str, Any]]) -> dict[str, Any]:
    """Require every conclusion to cite a literal quote in the verified source."""
    case_id, question, answer = (_required(candidate, key) for key in ("case_id", "question", "proposed_answer"))
    findings = candidate.get("findings")
    if not isinstance(findings, list) or not findings:
        raise VerifiedCaseReviewError("candidate requires at least one finding")
    checked: list[dict[str, Any]] = []
    for number, finding in enumerate(findings, start=1):
        if not isinstance(finding, Mapping):
            raise VerifiedCaseReviewError(f"finding {number} must be an object")
        statement = _required(finding, "statement")
        evidence = finding.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise VerifiedCaseReviewError(f"finding {number} requires evidence")
        citations = []
        for evidence_number, source in enumerate(evidence, start=1):
            if not isinstance(source, Mapping):
                raise VerifiedCaseReviewError(f"finding {number} evidence {evidence_number} must be an object")
            filename, quote = _required(source, "filename"), _required(source, "quote")
            page = source.get("page_number")
            if not isinstance(page, int) or page < 1:
                raise VerifiedCaseReviewError(f"finding {number} evidence {evidence_number} needs a positive page_number")
            record = pages.get((filename, page))
            if record is None or quote.casefold() not in _text(record.get("text")).casefold():
                raise VerifiedCaseReviewError(f"finding {number} evidence {evidence_number} quote is not in the verified source")
            citations.append({"filename": filename, "page_number": page, "quote": quote})
        checked.append({"statement": statement, "evidence": citations})
    unresolved_questions = [_text(x) for x in candidate.get("unresolved_questions", []) if _text(x)]
    _validate_alternative_pleading_context(answer, checked, unresolved_questions)
    return {"schema_version": "verified-case-candidate.v1", "case_id": case_id, "question": question, "proposed_answer": answer, "findings": checked, "unresolved_questions": unresolved_questions, "limitations": _text(candidate.get("limitations")) or "Limited to the cited verified record; attorney review is required."}


def render_packet(candidate: Mapping[str, Any]) -> str:
    lines = ["# Verified-Case Attorney Review Packet", "", "> **Status: CANDIDATE - NOT ATTORNEY-APPROVED.**", "", "## Question", "", candidate["question"], "", "## Candidate Answer", "", candidate["proposed_answer"], "", "## Verified Record Support", ""]
    for number, finding in enumerate(candidate["findings"], start=1):
        lines.extend([f"### {number}. {finding['statement']}", ""])
        for source in finding["evidence"]:
            lines.extend([f"- **{source['filename']}, PDF page {source['page_number']}**", f"  > {source['quote']}"])
        lines.append("")
    lines.extend(["## Open Questions", ""] + [f"- {item}" for item in candidate["unresolved_questions"]] + ["", "## Scope and Attorney Decision", "", f"- **Limitations:** {candidate['limitations']}", "- [ ] Accept", "- [ ] Revise", "- [ ] Reject", "- [ ] Investigate further", ""])
    return "\n".join(lines)
