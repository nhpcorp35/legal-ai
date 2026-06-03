from engines.contradiction_engine import build_claim_finding
from engines.contradiction_reporter import build_contradiction_cards

conflict = {
    "type": "witness_conflict",
    "claim_a": {
        "text": "Plaintiff alleges the door was locked."
    },
    "claim_b": {
        "text": "Defendant denies the door was locked."
    },
}

finding = build_claim_finding(conflict)

cards = build_contradiction_cards([finding])

assert cards[0]["statement_a"] == (
    "Plaintiff alleges the door was locked."
)

assert cards[0]["statement_b"] == (
    "Defendant denies the door was locked."
)

print("CONTRADICTION EVIDENCE DISPLAY PASSED")
