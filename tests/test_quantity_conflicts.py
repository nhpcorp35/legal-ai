from engines.contradiction_claims import extract_claims
from engines.contradiction_comparison import compare_claims


def first(text):
    results = compare_claims(extract_claims(text))
    assert results, f"No findings returned for:\n{text}"
    return results[0]


# Dollar amount conflict
r = first("""
The tenant paid $5000.
The tenant paid $10000.
""")

assert r["type"] == "quantity_conflict"


# Numeric count conflict
r = first("""
The plaintiff made 3 payments.
The plaintiff made 5 payments.
""")

assert r["type"] == "quantity_conflict"


print("ALL QUANTITY CONFLICT TESTS PASSED")
