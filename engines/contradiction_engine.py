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

from engines.contradiction_comparison import compare_claims
from engines.contradiction_cross_document import (
    detect_cross_document_conflicts,
)
from engines.contradiction_document_claims import extract_document_claims
from engines.similar_case_enrichment import enrich_similar_cases

INTERNAL_DOCUMENT_SCOPE = "internal_document"
CROSS_DOCUMENT_SCOPE = "cross_document"


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


def _derive_contradiction_scope(conflict):
    claim_a = conflict.get("claim_a") or conflict.get("claim_1") or {}
    claim_b = conflict.get("claim_b") or conflict.get("claim_2") or {}
    source_a = claim_a.get("source_document", "")
    source_b = claim_b.get("source_document", "")

    if source_a and source_b and source_a != source_b:
        return CROSS_DOCUMENT_SCOPE

    return INTERNAL_DOCUMENT_SCOPE


def build_claim_finding(conflict):
    conflict = enrich_similar_cases(conflict)
    conflict["contradiction_scope"] = _derive_contradiction_scope(conflict)

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


def analyze_contradictions(documents):
    results = []

    for document in documents or []:
        claims = extract_document_claims(document)

        for conflict in compare_claims(claims):
            result = dict(conflict)
            result["contradiction_scope"] = INTERNAL_DOCUMENT_SCOPE
            results.append(result)

    if len(documents or []) < 2:
        return results

    cross_document_claims = []
    for document in documents:
        cross_document_claims.extend(
            extract_document_claims(document)
        )

    for conflict in compare_claims(cross_document_claims):
        claim_a = conflict.get("claim_a") or conflict.get("claim_1") or {}
        claim_b = conflict.get("claim_b") or conflict.get("claim_2") or {}
        source_a = claim_a.get("source_document", "")
        source_b = claim_b.get("source_document", "")

        if not source_a or not source_b or source_a == source_b:
            continue

        result = dict(conflict)
        result["contradiction_scope"] = CROSS_DOCUMENT_SCOPE
        results.append(result)

    return results


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
