from engines.contradiction_claims import extract_claims
from engines.contradiction_comparison import compare_claims

a = extract_claims(
    "John Smith testified notice was provided."
)

b = extract_claims(
    "John Smith later testified notice was not provided."
)

claims = a + b

results = compare_claims(claims)

assert len(results) == 1

r = results[0]

assert "cluster_summary" in r
assert len(r["cluster_summary"]) > 0

print("CLUSTER SUMMARY PASSED")
