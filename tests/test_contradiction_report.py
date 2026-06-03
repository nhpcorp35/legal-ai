from engines.contradiction_claims import extract_claims
from engines.contradiction_comparison import compare_claims
from engines.contradiction_report import build_contradiction_report

claims = []

claims.extend(
    extract_claims(
        "John Smith testified notice was provided."
    )
)

claims.extend(
    extract_claims(
        "John Smith testified notice was not provided."
    )
)

findings = compare_claims(claims)

report = build_contradiction_report(findings)

assert len(report) >= 1

assert "rank" in report[0]
assert "narrative" in report[0]
assert "recommendation" in report[0]
assert "litigation_impact" in report[0]

print("CONTRADICTION REPORT PASSED")
