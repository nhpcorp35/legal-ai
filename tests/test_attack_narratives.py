from engines.contradiction_claims import extract_claims
from engines.contradiction_comparison import compare_claims
from engines.attack_narratives import build_attack_narratives

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

report = build_attack_narratives(findings)

assert report

assert "attack_narrative" in report[0]
assert len(report[0]["attack_narrative"]) > 0

print("ATTACK NARRATIVES PASSED")
