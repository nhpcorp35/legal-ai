from engines.contradiction_case_matching import build_case_match_terms
from engines.case_retrieval_spike import retrieve_matching_cases

conflict = {
    "type": "witness_conflict",
    "attack_surface_category": "credibility",
}

terms = build_case_match_terms(conflict)

cases = retrieve_matching_cases(terms)

assert isinstance(cases, list)

print("CASE RETRIEVAL SPIKE PASSED")
