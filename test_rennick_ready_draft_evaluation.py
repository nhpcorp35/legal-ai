"""Behavioral checks for read-only evaluation of archived motion answers."""

import unittest

from scripts.evaluate_rennick_ready_drafts import (
    CASE_ID, RECOMMENDATION_ID, RESPONSE_ID, SECTIONS, SIGNED_TRO_SHA256, evaluate,
)


def sample(request_id):
    findings = [
        {"section": section, "statement": "A concrete analysis.", "citations": [{
            "filename": "613561_2026_MICHAEL_DESOUSA_et_al_v_GEORGE_RENNICK_et_al_ORDER_TO_SHOW_CAUSE_32.pdf",
            "page_number": 2, "source_sha256": SIGNED_TRO_SHA256,
        }], "authority_citations": ["ny-cplr-6301"]}
        for section in SECTIONS[request_id]
    ]
    if request_id == RECOMMENDATION_ID:
        support = [f for f in findings if f["section"] == "Record support"][0]
        support["citations"].extend([
            {"filename": "613561_2026_EXHIBIT_S__27.pdf", "page_number": 1,
             "source_sha256": "a" * 64},
            {"filename": "613561_2026_EXHIBIT_S__28.pdf", "page_number": 1,
             "source_sha256": "b" * 64},
            {"filename": "613561_2026_AFFIDAVIT_OR_AFFIRM_37 (2).pdf", "page_number": 1,
             "source_sha256": "c" * 64},
        ])
        findings.insert(3, {"section": "Record support", "statement": "Separate source analysis.",
                            "citations": support["citations"][:1], "authority_citations": []})
        findings.insert(4, {"section": "Record support", "statement": "Separate source analysis.",
                            "citations": support["citations"][:1], "authority_citations": []})
    findings[-2]["citations"].append({
        "filename": "613561_2026_EXHIBIT_S__48.pdf", "page_number": 3,
        "source_sha256": "d" * 64,
    })
    return {"case_id": CASE_ID, "request_id": request_id, "status": "READY", "draft": {
        "request_id": request_id, "summary": "Consider the signed order and evidence.",
        "findings": findings, "missing_information": [],
    }}


class RennickReadyDraftEvaluationTests(unittest.TestCase):
    def test_complete_answer_still_requires_substantive_review(self):
        report = evaluate(sample(RECOMMENDATION_ID))
        self.assertEqual(report["defects"], [])
        self.assertEqual(len(report["review_questions"]), 4)
        self.assertIn("attorney review", report["scope"])

    def test_signed_tro_gap_in_archived_response_is_visible(self):
        item = sample(RESPONSE_ID)
        item["draft"]["missing_information"] = [
            "The operative signed TRO’s exact restrictions remain unresolved in the selected excerpts."
        ]
        self.assertIn("archived_response_obsolete_tro_gap", evaluate(item)["defects"])

    def test_missing_competing_expert_rebuttal_is_visible(self):
        item = sample(RESPONSE_ID)
        for finding in item["draft"]["findings"]:
            finding["citations"] = [c for c in finding["citations"]
                                    if not c["filename"].endswith("EXHIBIT_S__48.pdf")]
        self.assertIn("competing_expert_rebuttal_not_cited", evaluate(item)["defects"])

    def test_wrong_case_and_uncited_decision_cannot_pass(self):
        item = sample(RECOMMENDATION_ID)
        item["case_id"] = "NY-Richmond-151944-2017-Kuzmicki-v-Bentley-Yacht-Club"
        item["draft"]["findings"][1]["citations"] = []
        item["draft"]["findings"][1]["authority_citations"] = []
        report = evaluate(item)
        self.assertIn("case_id_mismatch", report["defects"])
        self.assertIn("finding_without_source", report["defects"])

    def test_cited_case_cannot_masquerade_as_rennick_evidence(self):
        item = sample(RESPONSE_ID)
        item["draft"]["findings"][2]["citations"][0]["filename"] = "Kuzmicki_EXHIBIT_53.pdf"
        self.assertIn("cited_case_used_as_rennick_record", evaluate(item)["defects"])

    def test_unsupported_page_and_missing_operative_order_are_flagged(self):
        item = sample(RECOMMENDATION_ID)
        for finding in item["draft"]["findings"]:
            finding["citations"][0]["source_sha256"] = "invalid"
        defects = evaluate(item)["defects"]
        self.assertIn("invalid_page_citation", defects)
        self.assertIn("signed_tro_not_cited_for_motion_posture", defects)

    def test_section_presence_without_decision_order_fails(self):
        item = sample(RESPONSE_ID)
        item["draft"]["findings"] = list(reversed(item["draft"]["findings"]))
        self.assertIn("decision_sequence_missing_or_out_of_order", evaluate(item)["defects"])

    def test_expert_account_does_not_replace_direct_agency_record(self):
        item = sample(RECOMMENDATION_ID)
        for finding in item["draft"]["findings"]:
            finding["citations"] = [c for c in finding["citations"]
                                    if not c["filename"].endswith("EXHIBIT_S__28.pdf")]
        self.assertIn("direct_usace_record_missing_from_support", evaluate(item)["defects"])


if __name__ == "__main__":
    unittest.main()
