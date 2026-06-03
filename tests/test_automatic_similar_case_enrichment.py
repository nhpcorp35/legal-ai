from engines.contradiction_orchestrator import (
    build_contradiction_analysis,
)

documents = [
    {
        "filename": "complaint",
        "text": "Plaintiff alleges the door was locked.",
    },
    {
        "filename": "answer",
        "text": "Defendant denies the door was locked.",
    },
]

analysis = build_contradiction_analysis(documents)

assert analysis["cards"]

card = analysis["cards"][0]

assert "similar_cases" in card

print("AUTOMATIC SIMILAR CASE ENRICHMENT PASSED")
