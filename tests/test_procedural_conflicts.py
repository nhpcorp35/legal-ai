from engines.contradiction_claims import extract_claims
from engines.contradiction_comparison import compare_claims


def first(text):
    results = compare_claims(extract_claims(text))
    assert results, f"No findings returned for:\n{text}"
    return results[0]


r = first("""
The motion was served on defendant.
The motion was never served on defendant.
""")

assert r["type"] == "procedural_conflict"

print("ALL PROCEDURAL CONFLICT TESTS PASSED")
