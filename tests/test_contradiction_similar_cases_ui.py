from engines.contradiction_engine import build_claim_finding
from engines.contradiction_reporter import build_contradiction_cards

conflict = {
    "type": "witness_conflict",
    "similar_cases": [
        {
            "case_name": "Smith v. Jones",
            "reason": "conflicting witness testimony",
        }
    ],
}

finding = build_claim_finding(conflict)

card = build_contradiction_cards([finding])[0]

assert card["similar_cases"][0]["case_name"] == "Smith v. Jones"

print("CONTRADICTION SIMILAR CASES UI PASSED")
