from engines.contradiction_engine import build_claim_finding
from engines.contradiction_reporter import build_contradiction_cards

conflict = {
    "type": "credibility_conflict",
    "severity": 9,
    "credibility_score": 10,
    "attack_rank": 1,
    "cluster_summary":
        "John Smith testified notice was provided and later testified notice was not provided.",
    "impeachment_candidate": True,
}

finding = build_claim_finding(conflict)

cards = build_contradiction_cards([finding])

assert "rank" in cards[0]
assert "narrative" in cards[0]
assert "recommendation" in cards[0]
assert "litigation_impact" in cards[0]

print("REPORT ENRICHED CARDS PASSED")
