from core.models import ContradictionFinding
from core.utils.contradiction_accessors import (
    get_contradiction_category,
    get_contradiction_score,
    get_contradiction_source,
    get_contradiction_summary,
)
from engines.contradiction_report import build_contradiction_report

REPORT_FIELDS = (
    "rank",
    "narrative",
    "recommendation",
    "litigation_impact",
)


def _item_to_finding(item):
    if isinstance(item, ContradictionFinding) and item.comparison:
        return item.comparison

    if isinstance(item, dict) and (
        item.get("claim_a")
        or item.get("claim_b")
        or item.get("type")
    ):
        return item

    return None


def _report_fields_for_item(item):
    finding = _item_to_finding(item)

    if not finding:
        return {}

    entries = build_contradiction_report([finding])

    if not entries:
        return {}

    entry = entries[0]
    return {field: entry.get(field) for field in REPORT_FIELDS}


def build_contradiction_cards(items):
    cards = []

    for item in items:
        source = get_contradiction_source(item)
        report_fields = _report_fields_for_item(item)

        cards.append(
            {
                "category": get_contradiction_category(item),
                "summary": get_contradiction_summary(item),
                "score": get_contradiction_score(item),
                "source_document": source.filename,
                "source_snippet": source.source_snippet,
                "rank": report_fields.get("rank"),
                "narrative": report_fields.get("narrative"),
                "recommendation": report_fields.get("recommendation"),
                "litigation_impact": report_fields.get("litigation_impact"),
            }
        )

    return cards
