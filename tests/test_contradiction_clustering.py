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
        "John Smith testified lease was signed."
    )
)
claims.extend(
    extract_claims(
        "John Smith later testified notice was not provided."
    )
)
claims.extend(
    extract_claims(
        "John Smith later testified lease was not signed."
    )
)

results = compare_claims(claims)

assert any("cluster_id" in r for r in results)

print("CONTRADICTION CLUSTERING PASSED")
