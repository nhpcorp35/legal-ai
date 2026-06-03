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
}

finding = build_claim_finding(conflict)

card = build_contradiction_cards([finding])[0]

assert card["source_a"] == "complaint"
assert card["source_b"] == "answer"

print("CONTRADICTION SOURCE TRACEABILITY UI PASSED")
