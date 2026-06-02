from engines.contradiction_claims import extract_claims
from engines.contradiction_comparison import compare_claims

a = extract_claims(
    "John Smith testified the notice was provided."
)

b = extract_claims(
    "John Smith later testified the notice was not provided."
)

claims = a + b

results = compare_claims(claims)

assert len(results) == 1

r = results[0]

assert r["type"] == "credibility_conflict"
assert "credibility_score" in r
assert r["credibility_score"] > 0

print("WITNESS CONFLICT DETECTION PASSED")
