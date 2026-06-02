from engines.contradiction_claims import extract_claims

a = extract_claims(
    "John Smith testified the notice was provided."
)

b = extract_claims(
    "John Smith later testified the notice was not provided."
)

assert a[0]["witness_name"] == "John Smith"
assert b[0]["witness_name"] == "John Smith"

print("WITNESS NAME EXTRACTION PASSED")
