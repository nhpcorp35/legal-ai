CONFLICT_TYPE_TERMS = {
    "witness_conflict": [
        "conflicting witness testimony",
        "conflicting testimony",
        "questions of fact",
    ],
    "credibility_conflict": [
        "conflicting witness testimony",
        "conflicting testimony",
        "credibility dispute",
        "questions of fact",
    ],
}

ATTACK_SURFACE_CATEGORY_TERMS = {
    "credibility": [
        "credibility dispute",
        "issues of credibility",
    ],
    "procedure": [
        "procedural defect",
    ],
    "chronology": [
        "timeline inconsistency",
    ],
    "factual": [
        "conflicting factual assertions",
    ],
}


def build_case_match_terms(conflict):
    terms = []

    conflict_type = conflict.get("type", "")
    for term in CONFLICT_TYPE_TERMS.get(conflict_type, []):
        if term not in terms:
            terms.append(term)

    category = conflict.get("attack_surface_category", "")
    for term in ATTACK_SURFACE_CATEGORY_TERMS.get(category, []):
        if term not in terms:
            terms.append(term)

    return terms
