import unittest

from engines import issue_engine_v4 as engine


class FirstHandEvidenceFilterTests(unittest.TestCase):
    def test_excludes_pleadings_and_attorney_advocacy(self):
        accepted, excluded = engine.filter_first_hand_evidence([
            {"filename": "complaint.pdf", "type": "complaint", "text": "Plaintiff alleges defendant breached the agreement."},
            {"filename": "affirmation_of_counsel.pdf", "type": "affirmation", "text": "Counsel affirms that the defendant received notice."},
        ])
        self.assertEqual(accepted, [])
        self.assertEqual([item["reason"] for item in excluded], ["pleading_or_attorney_advocacy_not_first_hand_evidence", "second_hand_or_advocacy_language"])

    def test_accepts_deposition_and_non_service_affidavit(self):
        accepted, excluded = engine.filter_first_hand_evidence([
            {"filename": "deposition_of_jane_doe.pdf", "type": "deposition", "text": "I observed the condition."},
            {"filename": "affidavit_of_jane_doe.pdf", "type": "affidavit", "text": "I have personal knowledge."},
            {"filename": "affidavit_of_service.pdf", "type": "affidavit", "text": "I served the papers by mail."},
        ])
        self.assertEqual([doc["filename"] for doc in accepted], ["deposition_of_jane_doe.pdf", "affidavit_of_jane_doe.pdf"])
        self.assertEqual(excluded[0]["reason"], "service_filing_not_substantive_evidence")

    def test_analysis_uses_only_first_hand_sources_and_reports_audit(self):
        result = engine.build_issue_analysis({"motion": "summary judgment motion"}, documents=[
            {"filename": "complaint.pdf", "type": "complaint", "text": "Plaintiff alleges damages are unknown."},
            {"filename": "deposition.pdf", "type": "deposition", "text": "I cannot recall the date."},
        ])
        self.assertEqual(result["first_hand_evidence"]["accepted_documents"], ["deposition.pdf"])
        self.assertEqual(result["first_hand_evidence"]["excluded_count"], 1)
        self.assertTrue(result["fact_risk_flags"])
        self.assertTrue(all(finding.source.filename == "deposition.pdf" for finding in result["fact_risk_flags"]))


if __name__ == "__main__":
    unittest.main()
