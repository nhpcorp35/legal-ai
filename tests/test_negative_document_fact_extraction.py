from engines.contradiction_claims import extract_claims

claims = extract_claims(
    "The affidavit states notice was not provided."
)

c = claims[0]

assert c["fact_subject"] == "notice"
assert c["fact_action"] == "provide"
assert c["polarity"] == "negative"

print("NEGATIVE DOCUMENT FACT EXTRACTION PASSED")
