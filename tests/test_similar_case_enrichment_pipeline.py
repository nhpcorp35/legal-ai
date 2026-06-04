from engines.contradiction_orchestrator import build_contradiction_analysis

SIMILAR_CASE_ENTRY_FIELDS = [
    "case_name",
    "reason",
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

assert analysis["cards"], (
    "Similar-case enrichment must not prevent contradiction generation"
)

card = analysis["cards"][0]

assert "similar_cases" in card
assert isinstance(card["similar_cases"], list)
assert card["similar_cases"], "Expected enriched similar cases on card"

for entry in card["similar_cases"]:
    for field in SIMILAR_CASE_ENTRY_FIELDS:
        assert field in entry, f"Missing similar_cases field: {field}"

assert card.get("summary")
assert card.get("statement_a")
assert card.get("statement_b")

print("SIMILAR CASE ENRICHMENT PIPELINE PASSED")
