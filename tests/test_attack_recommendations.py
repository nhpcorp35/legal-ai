from engines.contradiction_claims import extract_claims
from engines.contradiction_comparison import compare_claims
from engines.attack_recommendations import build_attack_recommendations

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

report = build_attack_recommendations(findings)

assert report

assert report[0]["type"] == "credibility_conflict"
assert report[0]["attack_recommendation"] == "deposition impeachment"

assert "attack_recommendation" in report[1]
assert report[1]["attack_recommendation"] == "challenge document authenticity"

print("ATTACK RECOMMENDATIONS PASSED")
