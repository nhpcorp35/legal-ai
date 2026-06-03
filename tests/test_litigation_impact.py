from engines.contradiction_claims import extract_claims
from engines.contradiction_comparison import compare_claims
from engines.litigation_impact import build_litigation_impact

claims = []

claims.extend(
    extract_claims(
        "John Smith testified notice was provided."
    )
)

claims.extend(
    extract_claims(
        "John Smith testified notice was not provided."
    )
)

claims.extend(
    extract_claims(
        "The affidavit states notice was provided."
    )
)

claims.extend(
    extract_claims(
        "The affidavit states notice was not provided."
    )
)

findings = compare_claims(claims)

report = build_litigation_impact(findings)

assert report[0]["litigation_impact"] == "high"
assert report[1]["litigation_impact"] == "high"

print("LITIGATION IMPACT PASSED")
