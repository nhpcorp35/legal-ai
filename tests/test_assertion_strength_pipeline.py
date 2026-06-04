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

strength_a = card.get("assertion_strength_a")
strength_b = card.get("assertion_strength_b")

assert isinstance(strength_a, str) and strength_a
assert isinstance(strength_b, str) and strength_b

print("ASSERTION STRENGTH PIPELINE PASSED")
