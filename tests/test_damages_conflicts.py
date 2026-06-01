from engines.contradiction_claims import extract_claims
from engines.contradiction_comparison import compare_claims


def first(text):
    results = compare_claims(extract_claims(text))
    assert results, f"No findings returned for:\n{text}"
    return results[0]


r = first("""
Plaintiff claims damages of $50000.
Plaintiff claims damages of $100000.
""")

assert r["type"] == "damages_conflict"

print("ALL DAMAGES CONFLICT TESTS PASSED")
