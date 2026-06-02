from engines.contradiction_claims import extract_claims
from engines.contradiction_comparison import compare_claims

a = extract_claims(
    "The email confirms notice was provided."
)

b = extract_claims(
    "The affidavit states notice was not provided."
)

claims = a + b

results = compare_claims(claims)

assert len(results) == 1

r = results[0]

assert "attack_surface_category" in r
assert r["attack_surface_category"] == "credibility"

print("ATTACK SURFACE CATEGORY PASSED")
