"""Read-only, non-model checks for the two archived Rennick motion answers.

Input is a local JSON export of the two exact ``draft.get`` results (either a
list or a mapping keyed by request ID). No network, B2 write, draft creation,
or review submission occurs. Results identify mechanical defects and questions
for human legal review; a clean result does not certify legal reasoning.
"""

import argparse
import json
import re
from pathlib import Path


CASE_ID = "NY-Nassau-613561-2026-Desousa-v-Rennick"
RECOMMENDATION_ID = "draft-1790275196-5d33f8a041c2"
RESPONSE_ID = "draft-1790200223-c52acd236d81"
SIGNED_TRO_SHA256 = "c3ebfd9a47a673932b40f470ff02072e4902acbda49412a938596b110f29a1fc"
SECTIONS = {
    RECOMMENDATION_ID: (
        "Objective and posture", "Candidate motions", "Record support",
        "Likely opposition", "Gaps and prerequisites", "Recommendation",
    ),
    RESPONSE_ID: (
        "Motion and burden", "Opponent showing", "Response grounds",
        "Evidence to submit", "Procedural objections", "Recommendation",
    ),
}


def _unwrap(item):
    if isinstance(item, dict) and isinstance(item.get("result"), dict):
        item = item["result"]
    return item


def evaluate(item):
    """Return bounded findings, without reproducing the answer or source text."""
    item = _unwrap(item)
    request_id = item.get("request_id")
    defects = []
    if request_id not in SECTIONS:
        return {"request_id": request_id, "defects": ["unexpected_request_id"], "review_questions": []}
    if item.get("case_id") != CASE_ID:
        defects.append("case_id_mismatch")
    if item.get("status") != "READY":
        defects.append("draft_not_ready")
    draft = item.get("draft") or {}
    if draft.get("request_id") not in (None, request_id):
        defects.append("draft_identity_mismatch")
    findings = draft.get("findings") or []
    sections = [f.get("section") for f in findings]
    expected = SECTIONS[request_id]
    if tuple(dict.fromkeys(sections)) != expected:
        defects.append("decision_sequence_missing_or_out_of_order")
    if not str(draft.get("summary") or "").strip():
        defects.append("missing_direct_answer")

    cited_signed_tro = False
    for finding in findings:
        if not str(finding.get("statement") or "").strip():
            defects.append("empty_finding")
        citations = finding.get("citations") or []
        authorities = finding.get("authority_citations") or []
        if not citations and not authorities:
            defects.append("finding_without_source")
        for citation in citations:
            filename = citation.get("filename") or ""
            sha = citation.get("source_sha256") or ""
            if (not filename.lower().endswith(".pdf") or not isinstance(citation.get("page_number"), int)
                    or citation["page_number"] < 1 or not re.fullmatch(r"[0-9a-f]{64}", sha)):
                defects.append("invalid_page_citation")
            if "Kuzmicki" in filename:
                defects.append("cited_case_used_as_rennick_record")
            if sha == SIGNED_TRO_SHA256 and "ORDER_TO_SHOW_CAUSE_32.pdf" in filename:
                cited_signed_tro = True
        if any(not isinstance(a, str) or not a.strip() for a in authorities):
            defects.append("invalid_authority_reference")
    if request_id == RECOMMENDATION_ID and not cited_signed_tro:
        defects.append("signed_tro_not_cited_for_motion_posture")
    if request_id == RESPONSE_ID:
        missing = " ".join(str(s) for s in draft.get("missing_information") or [])
        # The archived response predates the separately displayed signed-TRO
        # correction. Do not silently treat its obsolete gap as current truth.
        if re.search(r"signed TRO.{0,100}(?:unresolved|not established|unknown)", missing, re.I):
            defects.append("archived_response_obsolete_tro_gap")

    return {
        "request_id": request_id,
        "defects": sorted(set(defects)),
        "review_questions": [
            "Does each decisive proposition match the cited page, including its source type and limits?",
            "Does the answer weigh the strongest opposing reading and explain why the recommended action follows?",
            "Are any claimed contradictions genuine conflicts rather than alternative pleadings or advocacy?",
            "Do the cited authorities actually support the stated legal burden and procedural vehicle?",
        ],
        "scope": "Mechanical checks only; citation truth and legal reasoning require record and attorney review.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path, help="Local JSON export of both existing READY drafts")
    args = parser.parse_args()
    payload = json.loads(args.export.read_text(encoding="utf-8"))
    items = payload.values() if isinstance(payload, dict) else payload
    reports = [evaluate(item) for item in items]
    ids = {report["request_id"] for report in reports}
    if ids != set(SECTIONS) or len(reports) != 2:
        parser.error("export must contain the two exact Rennick motion draft IDs once each")
    print(json.dumps(reports, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
