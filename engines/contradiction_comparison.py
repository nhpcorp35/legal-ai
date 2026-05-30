def claims_match(claim_a, claim_b):
    fact_a = claim_a.get(
        "fact_text",
        "",
    ).strip().lower()

    fact_b = claim_b.get(
        "fact_text",
        "",
    ).strip().lower()

    if not fact_a or not fact_b:
        return False

    return fact_a == fact_b


def compare_claims(claims):
    findings = []

    for i, claim_a in enumerate(claims):

        for claim_b in claims[i + 1:]:

            if not claims_match(
                claim_a,
                claim_b,
            ):
                continue

            if (
                claim_a.get("polarity")
                ==
                claim_b.get("polarity")
            ):
                continue

            findings.append(
                {
                    "type": "position_conflict",
                    "summary":
                        "Opposite positions detected "
                        "for the same factual assertion.",
                    "claim_a": claim_a,
                    "claim_b": claim_b,
                }
            )

    return findings
