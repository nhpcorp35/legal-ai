from engines.contradiction_engine import build_claim_finding
from engines.contradiction_reporter import build_contradiction_cards

conflict = {
    "type": "credibility_conflict",
    "severity": 9,
    "credibility_score": 10,
    "attack_rank": 1,
}

finding = build_claim_finding(conflict)

card = build_contradiction_cards([finding])[0]

assert card["narrative"] is not None
assert card["recommendation"] is not None
assert card["litigation_impact"] is not None

print("CONTRADICTION UI FIELDS PASSED")
