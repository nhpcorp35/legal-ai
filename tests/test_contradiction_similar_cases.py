from engines.contradiction_engine import build_claim_finding
from engines.contradiction_reporter import build_contradiction_cards

conflict = {
    "type": "witness_conflict",
    "claim_a": {
        "text": "Plaintiff alleges the door was locked.",
        "source_document": "complaint",
    },
    "claim_b": {
        "text": "Defendant denies the door was locked.",
        "source_document": "answer",
    },
    "similar_cases": [
        {
            "case_name": "Smith v. Jones",
            "reason": "conflicting witness testimony",
        }
    ],
}

finding = build_claim_finding(conflict)

cards = build_contradiction_cards([finding])

assert len(cards[0]["similar_cases"]) == 1

assert cards[0]["similar_cases"][0]["case_name"] == (
    "Smith v. Jones"
)

print("CONTRADICTION SIMILAR CASES PASSED")
