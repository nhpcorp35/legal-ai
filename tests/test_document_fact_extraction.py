from engines.contradiction_claims import extract_claims

claims = extract_claims(
    "The email confirms notice was provided."
)

c = claims[0]

assert c["document_subject"] == "email"
assert c["document_action"] == "confirm"

# future fields
assert c["fact_subject"] == "notice"
assert c["fact_action"] == "provide"

print("DOCUMENT FACT EXTRACTION PASSED")
