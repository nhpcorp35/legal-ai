from engines.contradiction_case_matching import build_case_match_terms

conflict = {
    "type": "witness_conflict",
    "attack_surface_category": "credibility",
}

terms = build_case_match_terms(conflict)

assert "conflicting witness testimony" in terms
assert "credibility dispute" in terms

print("CONTRADICTION CASE MATCHING PASSED")
