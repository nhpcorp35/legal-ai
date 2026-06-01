from engines.contradiction_claims import extract_claims

claims = extract_claims(
    "The email confirms notice was provided."
)

c = claims[0]

assert c["document_subject"] == "email"
assert c["document_action"] == "confirm"

assert c["document_requirement"] == "notice was provided"

print("DOCUMENT REQUIREMENT EXTRACTION PASSED")
