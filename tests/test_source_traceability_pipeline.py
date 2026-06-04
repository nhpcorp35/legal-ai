from engines.contradiction_orchestrator import build_contradiction_analysis

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

assert card.get("statement_a")
assert card.get("statement_b")
assert card.get("source_a")
assert card.get("source_b")

assert {
    card["source_a"],
    card["source_b"],
} == {
    "complaint.txt",
    "answer.txt",
}

print("SOURCE TRACEABILITY PIPELINE PASSED")
