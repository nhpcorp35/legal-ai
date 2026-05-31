from engines.contradiction_claims import extract_claims
from engines.contradiction_comparison import compare_claims


def first(text):
    results = compare_claims(extract_claims(text))
    assert results, f"No findings returned for:\n{text}"
    return results[0]


# Credibility conflict
r = first("""
John Smith testified the light was green.
John Smith testified the light was not green.
""")
assert r["type"] == "credibility_conflict"
assert r.get("impeachment_candidate") is True
assert r.get("severity") == 9

# Witness conflict
r = first("""
John Smith testified the light was green.
Mary Jones testified the light was not green.
""")
assert r["type"] == "witness_conflict"

# Document conflict
r = first("""
The lease requires written approval.
The lease does not require written approval.
""")
assert r["type"] == "document_conflict"

# Timeline conflict
r = first("""
The accident occurred before January 5.
The accident occurred after January 5.
""")
assert r["type"] == "timeline_conflict"

print("ALL CONTRADICTION ENGINE TESTS PASSED")
