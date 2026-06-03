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


def _statement_fields_for_item(item):
    finding = _item_to_finding(item)

    if not finding:
        return {}

    claim_a = finding.get("claim_a") or finding.get("claim_1") or {}
    claim_b = finding.get("claim_b") or finding.get("claim_2") or {}

    return {
        "statement_a": claim_a.get("text", ""),
        "statement_b": claim_b.get("text", ""),
    }


def _source_fields_for_item(item):
    finding = _item_to_finding(item)

    if not finding:
        return {}

    claim_a = finding.get("claim_a") or finding.get("claim_1") or {}
    claim_b = finding.get("claim_b") or finding.get("claim_2") or {}

    return {
        "source_a": claim_a.get("source_document", ""),
        "source_b": claim_b.get("source_document", ""),
    }


def _assertion_strength_fields_for_item(item):
    finding = _item_to_finding(item)

    if not finding:
        return {}

    claim_a = finding.get("claim_a") or finding.get("claim_1") or {}
    claim_b = finding.get("claim_b") or finding.get("claim_2") or {}

    return {
        "assertion_strength_a": claim_a.get("assertion_strength", ""),
        "assertion_strength_b": claim_b.get("assertion_strength", ""),
    }


def _similar_cases_for_item(item):
    finding = _item_to_finding(item)

    if not finding:
        return []

    return list(finding.get("similar_cases") or [])


def _contradiction_scope_for_item(item):
    finding = _item_to_finding(item)

    if not finding:
        return ""

    return finding.get("contradiction_scope") or ""


def build_contradiction_cards(items):
    cards = []

    for item in items:
        source = get_contradiction_source(item)
        report_fields = _report_fields_for_item(item)
        statement_fields = _statement_fields_for_item(item)
        source_fields = _source_fields_for_item(item)
        assertion_strength_fields = _assertion_strength_fields_for_item(item)
        similar_cases = _similar_cases_for_item(item)
        contradiction_scope = _contradiction_scope_for_item(item)

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
                "statement_a": statement_fields.get("statement_a"),
                "statement_b": statement_fields.get("statement_b"),
                "source_a": source_fields.get("source_a"),
                "source_b": source_fields.get("source_b"),
                "assertion_strength_a": assertion_strength_fields.get(
                    "assertion_strength_a"
                ),
                "assertion_strength_b": assertion_strength_fields.get(
                    "assertion_strength_b"
                ),
                "contradiction_scope": contradiction_scope,
                "similar_cases": similar_cases,
            }
        )

    return cards
