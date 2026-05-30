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


def classify_conflict(claim_a, claim_b):
    speaker_a = claim_a.get(
        "speaker",
        "unknown",
    )

    speaker_b = claim_b.get(
        "speaker",
        "unknown",
    )

    if (
        speaker_a != "unknown"
        and speaker_a == speaker_b
    ):
        return (
            "position_shift",
            "Same speaker takes opposite "
            "positions on the same fact."
        )

    return (
        "factual_dispute",
        "Different parties take opposite "
        "positions on the same fact."
    )


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

            conflict_type, summary = (
                classify_conflict(
                    claim_a,
                    claim_b,
                )
            )

            findings.append(
                {
                    "type": conflict_type,
                    "summary": summary,
                    "claim_a": claim_a,
                    "claim_b": claim_b,
                }
            )

    return findings
