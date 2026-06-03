from engines.contradiction_engine import analyze_contradictions

docs = [
    {
        "filename": "complaint.txt",
        "text": (
            "Plaintiff states the door was locked. "
            "Plaintiff states the door was not locked."
        ),
    }
]

results = analyze_contradictions(docs)

assert len(results) > 0
assert results[0]["contradiction_scope"] == "internal_document"

docs = [
    {
        "filename": "complaint.txt",
        "text": "Plaintiff states the door was locked.",
    },
    {
        "filename": "answer.txt",
        "text": "Defendant states the door was not locked.",
    },
]

results = analyze_contradictions(docs)

assert len(results) > 0
assert results[0]["contradiction_scope"] == "cross_document"

print("PASS")
