from engines.contradiction_claims import extract_claims
from engines.contradiction_comparison import compare_claims
from engines.top_attack_surfaces import build_top_attack_surfaces

claims = []

claims.extend(
    extract_claims(
        "John Smith testified notice was provided."
    )
)

claims.extend(
    extract_claims(
        "John Smith later testified notice was not provided."
    )
)

claims.extend(
    extract_claims(
        "The contract required insurance."
    )
)

claims.extend(
    extract_claims(
        "The contract did not require insurance."
    )
)

findings = compare_claims(claims)

assert findings

report = build_top_attack_surfaces(findings)

assert report
assert len(report) > 0

assert "attack_rank" in report[0]
assert "credibility_score" in report[0]

print("TOP ATTACK SURFACES PASSED")