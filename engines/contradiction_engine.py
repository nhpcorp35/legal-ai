import re

from core.models import (
    ContradictionFinding,
    DocumentReference,
)

from core.utils.scoring import clamp_score

from engines.contradiction_constants import (
    CONTRADICTION_PATTERNS,
    ENGINE_VERSION,
)

from engines.contradiction_cross_document import (
    detect_cross_document_conflicts,
)


def clean_text(value):
    if not value:
        return ""

    return re.sub(r"\s+", " ", str(value)).strip()


def build_summary(category, match_count):
    return (
        f"Potential {category.replace('_', ' ')} detected "
        f"({match_count} supporting indicators)."
    )


def build_claim_summary(conflict):
    summary = conflict.get("summary")
    if summary:
        return clean_text(summary)

    cluster_summary = conflict.get("cluster_summary")
    if cluster_summary:
        return clean_text(cluster_summary)

    claim_a = conflict.get("claim_a", {})
    claim_b = conflict.get("claim_b", {})
    text_a = clean_text(claim_a.get("text", ""))
    text_b = clean_text(claim_b.get("text", ""))

    if text_a and text_b:
        return f"{text_a} However, {text_b}"

    conflict_type = conflict.get("type", "contradiction")
    return f"Potential {conflict_type.replace('_', ' ')} detected."


def build_claim_finding(conflict):
    claim_a = conflict.get("claim_a", {})
    claim_b = conflict.get("claim_b", {})

    score = 85

    return ContradictionFinding(
        category=conflict.get(
            "type",
            "position_conflict",
        ),
        summary=build_claim_summary(conflict),
        score=score,
        comparison=conflict,
        source=DocumentReference(
            filename=claim_a.get(
                "source_document",
                "",
            ),
            document_type=claim_a.get(
                "source_type",
                "",
            ),
            source_snippet=claim_a.get(
                "text",
                "",
            )[:500],
        ),
    )


def detect_contradictions(documents):
    findings = []

    #
    # Legacy keyword detector
    #

    for doc in documents:
        text = clean_text(doc.get("text"))

        if not text:
            continue

        lowered = text.lower()

        for category, patterns in CONTRADICTION_PATTERNS:

            matched_patterns = []

            for pattern in patterns:
                if re.search(pattern, lowered):
                    matched_patterns.append(pattern)

            if len(matched_patterns) < 2:
                continue

            score = clamp_score(
                60 + (len(matched_patterns) * 8)
            )

            findings.append(
                ContradictionFinding(
                    category=category,
                    summary=build_summary(
                        category,
                        len(matched_patterns),
                    ),
                    score=score,
                    source=DocumentReference(
                        filename=doc.get(
                            "filename",
                            "",
                        ),
                        document_type=doc.get(
                            "type",
                            "",
                        ),
                        source_snippet=text[:500],
                    ),
                )
            )

    #
    # Claim-based detector
    #

    for conflict in detect_cross_document_conflicts(
        documents
    ):
        findings.append(
            build_claim_finding(
                conflict
            )
        )

    findings.sort(
        key=lambda x: x.score,
        reverse=True,
    )

    return findings
