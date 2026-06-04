from engines.contradiction_orchestrator import build_contradiction_analysis

cross_document_analysis = build_contradiction_analysis(
    [
        {
            "filename": "complaint.txt",
            "text": "Plaintiff states the door was locked.",
        },
        {
            "filename": "answer.txt",
            "text": "Defendant states the door was not locked.",
        },
    ]
)

assert cross_document_analysis["cards"]
cross_card = cross_document_analysis["cards"][0]
assert cross_card["contradiction_scope"] == "cross_document"

internal_document_analysis = build_contradiction_analysis(
    [
        {
            "filename": "complaint.txt",
            "text": (
                "Plaintiff states the door was locked. "
                "Plaintiff states the door was not locked."
            ),
        },
    ]
)

assert internal_document_analysis["cards"]
internal_card = internal_document_analysis["cards"][0]
assert internal_card["contradiction_scope"] == "internal_document"

print("CONTRADICTION SCOPE PIPELINE PASSED")
