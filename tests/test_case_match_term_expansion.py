from engines.contradiction_case_matching import build_case_match_terms

conflict = {
    "type": "witness_conflict",
    "attack_surface_category": "credibility",
}

terms = build_case_match_terms(conflict)

assert "issues of credibility" in terms
assert "questions of fact" in terms
assert "conflicting testimony" in terms

print("CASE MATCH TERM EXPANSION PASSED")
