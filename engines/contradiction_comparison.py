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

    claim_type = claim_a.get(
        "claim_type",
        "assertion",
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

    if claim_type == "notice":
        return (
            "notice_conflict",
            "Different parties dispute "
            "notice or knowledge."
        )

    if claim_type == "timeline":
        return (
            "timeline_conflict",
            "Different parties dispute "
            "timing or sequence of events."
        )

    if claim_type == "causation":
        return (
            "causation_conflict",
            "Different parties dispute "
            "cause and effect."
        )

    if claim_type == "witness":
        return (
            "witness_conflict",
            "Different witness accounts "
            "or testimony detected."
        )

    if claim_type == "document":
        return (
            "document_conflict",
            "Different interpretations "
            "of documentary evidence."
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
