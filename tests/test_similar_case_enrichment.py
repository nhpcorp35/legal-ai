from engines.contradiction_case_matching import (
    build_case_match_terms,
)
from engines.case_retrieval_spike import (
    retrieve_matching_cases,
)
from engines.similar_case_enrichment import (
    enrich_similar_cases,
)

conflict = {
    "type": "witness_conflict",
    "attack_surface_category": "credibility",
}

enriched = enrich_similar_cases(conflict)

assert "similar_cases" in enriched
assert isinstance(enriched["similar_cases"], list)

print("SIMILAR CASE ENRICHMENT PASSED")
