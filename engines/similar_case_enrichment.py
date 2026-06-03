from engines.case_retrieval_spike import retrieve_matching_cases
from engines.contradiction_case_matching import build_case_match_terms


def enrich_similar_cases(conflict, limit=5):
    enriched = dict(conflict)

    if enriched.get("similar_cases"):
        return enriched

    terms = build_case_match_terms(enriched)
    enriched["similar_cases"] = retrieve_matching_cases(terms, limit=limit)
    return enriched
