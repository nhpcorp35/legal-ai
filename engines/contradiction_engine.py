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


def clean_text(value):
    if not value:
        return ""

    return re.sub(r"\s+", " ", str(value)).strip()


def build_summary(category, match_count):
    return (
        f"Potential {category.replace('_', ' ')} detected "
        f"({match_count} supporting indicators)."
    )


def detect_contradictions(documents):
    findings = []

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
                        filename=doc.get("filename", ""),
                        document_type=doc.get("type", ""),
                        source_snippet=text[:500],
                    ),
                )
            )

    findings.sort(
        key=lambda x: x.score,
        reverse=True,
    )

    return findings
