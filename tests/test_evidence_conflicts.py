from engines.contradiction_claims import extract_claims
from engines.contradiction_comparison import compare_claims


def first(text):
    results = compare_claims(extract_claims(text))
    assert results, f"No findings returned for:\n{text}"
    return results[0]


r = first("""
The email confirms notice was provided.
Defendant states notice was not provided.
""")

assert r["type"] == "evidence_conflict"

print("ALL EVIDENCE CONFLICT TESTS PASSED")
