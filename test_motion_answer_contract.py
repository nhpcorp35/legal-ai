"""Unit tests for the attorney-facing motion decision-slot contract."""

import unittest

from scripts.run_verified_case_draft import motion_answer_contract


def finding(section):
    return {
        "section": section,
        "statement": "Verified record analysis.",
        "citations": [],
        "authority_citations": [],
    }


class MotionAnswerContractTests(unittest.TestCase):
    def test_recommendation_exposes_all_six_decision_slots(self):
        result = {
            "findings": [
                finding("Objective and posture"),
                finding("Candidate motions"),
                finding("Record support"),
                finding("Likely opposition"),
                finding("Gaps and prerequisites"),
                finding("Recommendation"),
            ]
        }

        contract = motion_answer_contract(
            result, "I need to make a motion. Which motions should I consider?"
        )

        self.assertEqual(contract["mode"], "motion_recommendation")
        self.assertEqual(
            list(contract["slots"]),
            [
                "posture",
                "relief",
                "burden",
                "decisive_evidence",
                "strongest_opposition",
                "action",
            ],
        )

    def test_response_exposes_all_six_decision_slots(self):
        result = {
            "findings": [
                finding("Motion and burden"),
                finding("Opponent showing"),
                finding("Response grounds"),
                finding("Evidence to submit"),
                finding("Procedural objections"),
                finding("Recommendation"),
            ]
        }

        contract = motion_answer_contract(
            result, "My opponent made a motion. How should I answer it?"
        )

        self.assertEqual(contract["mode"], "motion_response")
        self.assertEqual(contract["slots"]["decisive_evidence"]["finding_count"], 3)

    def test_missing_slot_fails_closed(self):
        result = {
            "findings": [
                finding("Motion and burden"),
                finding("Opponent showing"),
                finding("Response grounds"),
                finding("Evidence to submit"),
                finding("Procedural objections"),
            ]
        }

        with self.assertRaisesRegex(ValueError, "missing action"):
            motion_answer_contract(result, "My opponent made a motion. How should I answer it?")


if __name__ == "__main__":
    unittest.main()
