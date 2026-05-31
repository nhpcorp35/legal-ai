def clean_value(value):
    return str(value or "").strip().lower()


CREDIBILITY_SOURCES = {
    "affidavit",
    "affirmation",
    "deposition",
    "declaration",
    "testimony",
}


def claims_match(claim_a, claim_b):
    fact_a = clean_value(
        claim_a.get("fact_text", "")
    )

    fact_b = clean_value(
        claim_b.get("fact_text", "")
    )

    if not fact_a or not fact_b:
        return False

    return fact_a == fact_b


def timeline_claims_conflict(claim_a, claim_b):
    if (
        claim_a.get("claim_type") != "timeline"
        or claim_b.get("claim_type") != "timeline"
    ):
        return False

    event_a = clean_value(
        claim_a.get("timeline_event", "")
    )

    event_b = clean_value(
        claim_b.get("timeline_event", "")
    )

    date_a = clean_value(
        claim_a.get("timeline_date", "")
    )

    date_b = clean_value(
        claim_b.get("timeline_date", "")
    )

    relation_a = clean_value(
        claim_a.get("timeline_relation", "")
    )

    relation_b = clean_value(
        claim_b.get("timeline_relation", "")
    )

    if not event_a or not event_b:
        return False

    if event_a != event_b:
        return False

    if date_a and date_b and date_a != date_b:
        return False

    opposite_relations = {
        ("before", "after"),
        ("after", "before"),
    }

    return (
        relation_a,
        relation_b,
    ) in opposite_relations


def document_claims_conflict(claim_a, claim_b):
    if (
        claim_a.get("claim_type") != "document"
        or claim_b.get("claim_type") != "document"
    ):
        return False

    subject_a = clean_value(
        claim_a.get("document_subject", "")
    )

    subject_b = clean_value(
        claim_b.get("document_subject", "")
    )

    action_a = clean_value(
        claim_a.get("document_action", "")
    )

    action_b = clean_value(
        claim_b.get("document_action", "")
    )

    if not subject_a or not subject_b:
        return False

    if subject_a != subject_b:
        return False

    if (
        claim_a.get("polarity")
        !=
        claim_b.get("polarity")
    ):
        return True

    opposite_actions = {
        ("allow", "prohibit"),
        ("prohibit", "allow"),
    }

    return (
        action_a,
        action_b,
    ) in opposite_actions


def credibility_claims_conflict(claim_a, claim_b):
    source_a = clean_value(
        claim_a.get("source_type", "")
    )

    source_b = clean_value(
        claim_b.get("source_type", "")
    )

    if (
        source_a not in CREDIBILITY_SOURCES
        or source_b not in CREDIBILITY_SOURCES
    ):
        return False

    requirement_a = clean_value(
        claim_a.get(
            "document_requirement",
            ""
        )
    )

    requirement_b = clean_value(
        claim_b.get(
            "document_requirement",
            ""
        )
    )

    if requirement_a and requirement_b:
        if requirement_a != requirement_b:
            return False

        return (
            claim_a.get("polarity")
            !=
            claim_b.get("polarity")
        )

    witness_a = clean_value(
        claim_a.get("witness_name", "")
    )

    witness_b = clean_value(
        claim_b.get("witness_name", "")
    )

    if witness_a and witness_b:
        if witness_a != witness_b:
            return False

        if not claims_match(
            claim_a,
            claim_b,
        ):
            return False

        return (
            claim_a.get("polarity")
            !=
            claim_b.get("polarity")
        )

    speaker_a = clean_value(
        claim_a.get("speaker", "")
    )

    speaker_b = clean_value(
        claim_b.get("speaker", "")
    )

    if not speaker_a or not speaker_b:
        return False

    if speaker_a != speaker_b:
        return False

    if not claims_match(
        claim_a,
        claim_b,
    ):
        return False

    return (
        claim_a.get("polarity")
        !=
        claim_b.get("polarity")
    )


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

    if credibility_claims_conflict(
        claim_a,
        claim_b,
    ):
        return (
            "credibility_conflict",
            "Inconsistent statements across "
            "testimony or sworn evidence."
        )

    witness_a = clean_value(
        claim_a.get("witness_name", "")
    )

    witness_b = clean_value(
        claim_b.get("witness_name", "")
    )

    if (
        speaker_a != "unknown"
        and speaker_a == speaker_b
        and speaker_a != "witness"
    ):
        return (
            "position_shift",
            "Same speaker takes opposite "
            "positions on the same fact."
        )

    if (
        speaker_a == "witness"
        and speaker_b == "witness"
        and witness_a
        and witness_b
        and witness_a == witness_b
    ):
        return (
            "credibility_conflict",
            "Inconsistent statements across "
            "testimony or sworn evidence."
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

    if (
        claim_type == "witness"
        and clean_value(
            claim_a.get("witness_name", "")
        )
        and clean_value(
            claim_b.get("witness_name", "")
        )
        and clean_value(
            claim_a.get("witness_name", "")
        ) != clean_value(
            claim_b.get("witness_name", "")
        )
    ):
        return (
            "witness_conflict",
            "Different witness accounts "
            "or testimony detected."
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


def should_compare_as_conflict(claim_a, claim_b):
    if timeline_claims_conflict(
        claim_a,
        claim_b,
    ):
        return True

    if credibility_claims_conflict(
        claim_a,
        claim_b,
    ):
        return True

    if document_claims_conflict(
        claim_a,
        claim_b,
    ):
        return True

    if not claims_match(
        claim_a,
        claim_b,
    ):
        return False

    if (
        claim_a.get("polarity")
        ==
        claim_b.get("polarity")
    ):
        return False

    return True


def compare_claims(claims):
    findings = []

    for i, claim_a in enumerate(claims):

        for claim_b in claims[i + 1:]:

            if not should_compare_as_conflict(
                claim_a,
                claim_b,
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