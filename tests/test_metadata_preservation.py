from engines.contradiction_engine import build_claim_finding

conflict = {
    "type": "credibility_conflict",
    "severity": 9,
    "credibility_score": 10,
    "attack_rank": 1,
    "cluster_id": "cluster_1",
}

finding = build_claim_finding(conflict)

assert finding.comparison is not None

assert finding.comparison["severity"] == 9
assert finding.comparison["credibility_score"] == 10
assert finding.comparison["attack_rank"] == 1
assert finding.comparison["cluster_id"] == "cluster_1"

print("METADATA PRESERVATION PASSED")
