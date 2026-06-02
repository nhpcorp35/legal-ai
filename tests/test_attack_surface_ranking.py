from engines.contradiction_claims import extract_claims
from engines.contradiction_comparison import compare_claims

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

results = compare_claims(claims)

assert results

for r in results:
    assert "attack_rank" in r
    assert r["attack_rank"] >= 1

print("ATTACK SURFACE RANKING PASSED")
