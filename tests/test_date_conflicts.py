from engines.contradiction_claims import extract_claims
from engines.contradiction_comparison import compare_claims


def first(text):
    results = compare_claims(extract_claims(text))
    assert results, f"No findings returned for:\n{text}"
    return results[0]


# Exact date conflict
r = first("""
The accident occurred on January 5.
The accident occurred on January 7.
""")

assert r["type"] == "date_conflict"


# Timeline conflict (existing behavior)
r = first("""
The accident occurred before January 5.
The accident occurred after January 5.
""")

assert r["type"] == "timeline_conflict"


print("ALL DATE CONFLICT TESTS PASSED")
