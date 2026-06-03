from engines.contradiction_engine import build_claim_finding

conflict = {
    "type": "witness_conflict",
    "claim_a": {
        "speaker": "plaintiff",
        "fact_text": "the door was locked",
        "text": "Plaintiff alleges the door was locked.",
    },
    "claim_b": {
        "speaker": "defendant",
        "fact_text": "the door was locked",
        "text": "Defendant denies the door was locked.",
    },
}

finding = build_claim_finding(conflict)

assert (
    finding.summary
    != "Potential contradiction detected."
)

print("ATTORNEY GRADE SUMMARIES PASSED")
