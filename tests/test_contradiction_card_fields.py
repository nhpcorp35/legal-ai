from engines.contradiction_orchestrator import build_contradiction_analysis

REQUIRED_CARD_FIELDS = [
    "summary",
    "statement_a",
    "statement_b",
    "source_a",
    "source_b",
    "contradiction_scope",
    "assertion_strength_a",
    "assertion_strength_b",
    "narrative",
    "recommendation",
    "litigation_impact",
    "similar_cases",
]

documents = [
    {
        "filename": "complaint.txt",
        "text": "Plaintiff states the door was locked.",
    },
    {
        "filename": "answer.txt",
        "text": "Defendant states the door was not locked.",
    },
]

analysis = build_contradiction_analysis(documents)

assert analysis["cards"], "Expected at least one contradiction card"

card = analysis["cards"][0]

missing = [
    field
    for field in REQUIRED_CARD_FIELDS
    if field not in card
]

assert not missing, f"Missing contradiction card fields: {missing}"

assert isinstance(card["similar_cases"], list)

print("CONTRADICTION CARD FIELDS PASSED")
