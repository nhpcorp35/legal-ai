# engines/contradiction_comparison.py

"""
Contradiction Comparison Engine

Purpose:
- Compare extracted claims and identify direct contradictions.
- Preserve litigation-facing metadata used by regression tests:
  severity, impeachment_candidate, and attack_priority.

This file is intentionally conservative. No new feature expansion should be
added here until the contradiction regression test suite is stable.
"""


def _normalize_text(value):
    if value is None:
        return ""
    return str(value).strip().lower()


def _same_subject(a, b):
    """
    Conservative subject matching.

    Prefer explicit normalized_fact if available, then fact_text.
    This keeps comparison stable across claim extractor changes.
    """
    a_subject = _normalize_text(
        a.get("normalized_fact")
        or a.get("fact_text")
        or a.get("text")
    )
    b_subject = _normalize_text(
        b.get("normalized_fact")
        or b.get("fact_text")
        or b.get("text")
    )

    if not a_subject or not b_subject:
        return False

    return a_subject == b_subject


def _opposite_polarity(a, b):
    a_polarity = _normalize_text(a.get("polarity"))
    b_polarity = _normalize_text(b.get("polarity"))

    return (
        a_polarity in {"positive", "negative"}
        and b_polarity in {"positive", "negative"}
        and a_polarity != b_polarity
    )


def _speaker_identity(claim):
    return _normalize_text(
        claim.get("witness_name")
        or claim.get("speaker")
    )


def _timeline_conflict(a, b):
    a_type = _normalize_text(a.get("claim_type"))
    b_type = _normalize_text(b.get("claim_type"))

    if a_type != "timeline" or b_type != "timeline":
        return False

    a_fact = _normalize_text(a.get("fact_text"))
    b_fact = _normalize_text(b.get("fact_text"))

    if not a_fact or not b_fact:
        return False

    before_after = (
        (" before " in a_fact and " after " in b_fact)
        or (" after " in a_fact and " before " in b_fact)
    )

    same_anchor = False
    for token in [
        "january", "february", "march", "april",
        "may", "june", "july", "august",
        "september", "october", "november", "december"
    ]:
        if token in a_fact and token in b_fact:
            same_anchor = True
            break

    if not same_anchor:
        a_tokens = set(a_fact.replace(".", "").replace(",", "").split())
        b_tokens = set(b_fact.replace(".", "").replace(",", "").split())

        shared_numbers = {
            token for token in a_tokens.intersection(b_tokens)
            if any(ch.isdigit() for ch in token)
        }

        same_anchor = bool(shared_numbers)

    return before_after and same_anchor


def _causation_conflict(a, b):
    a_type = _normalize_text(a.get("claim_type"))
    b_type = _normalize_text(b.get("claim_type"))

    if a_type != "causation" or b_type != "causation":
        return False

    a_fact = _normalize_text(a.get("fact_text"))
    b_fact = _normalize_text(b.get("fact_text"))

    if not a_fact or not b_fact:
        return False

    same_core = (
        a_fact.replace(" did not ", " ").replace(" not ", " ")
        == b_fact.replace(" did not ", " ").replace(" not ", " ")
    )

    return same_core and _opposite_polarity(a, b)


def _document_conflict(a, b):
    a_type = _normalize_text(a.get("claim_type"))
    b_type = _normalize_text(b.get("claim_type"))

    if a_type != "document" or b_type != "document":
        return False

    a_subject = _normalize_text(a.get("document_subject"))
    b_subject = _normalize_text(b.get("document_subject"))

    if a_subject and b_subject and a_subject == b_subject:
        return _opposite_polarity(a, b)

    return _same_subject(a, b) and _opposite_polarity(a, b)


def _conflict_type(a, b):
    if _timeline_conflict(a, b):
        return "timeline_conflict"

    if _document_conflict(a, b):
        return "document_conflict"

    if _causation_conflict(a, b):
        return "credibility_conflict"

    if _same_subject(a, b) and _opposite_polarity(a, b):
        a_identity = _speaker_identity(a)
        b_identity = _speaker_identity(b)

        if a_identity and b_identity and a_identity != b_identity:
            return "witness_conflict"

        return "credibility_conflict"

    return None


def _is_conflict(a, b):
    return _conflict_type(a, b) is not None


def _derive_severity(a, b):
    explicit = a.get("severity") or b.get("severity")
    if explicit:
        return explicit

    conflict_type = _conflict_type(a, b)

    if conflict_type in {
        "credibility_conflict",
        "witness_conflict",
        "document_conflict",
        "timeline_conflict",
    }:
        return 9

    return 7


def _derive_impeachment_candidate(a, b):
    explicit = a.get("impeachment_candidate")
    if explicit is not None:
        return bool(explicit)

    explicit = b.get("impeachment_candidate")
    if explicit is not None:
        return bool(explicit)

    return True


def _derive_attack_priority(a, b):
    explicit = a.get("attack_priority") or b.get("attack_priority")
    if explicit:
        return explicit

    severity = _derive_severity(a, b)

    if severity >= 9:
        return "high"

    return "medium"


def _build_finding(a, b):
    severity = _derive_severity(a, b)
    impeachment_candidate = _derive_impeachment_candidate(a, b)
    attack_priority = _derive_attack_priority(a, b)

    return {
        "type": _conflict_type(a, b),
        "claim_a": a,
        "claim_b": b,
        "claim_1": a,
        "claim_2": b,
        "speaker_a": a.get("speaker", "unknown"),
        "speaker_b": b.get("speaker", "unknown"),
        "fact_a": a.get("fact_text") or a.get("text", ""),
        "fact_b": b.get("fact_text") or b.get("text", ""),
        "claim_type_a": a.get("claim_type", "unknown"),
        "claim_type_b": b.get("claim_type", "unknown"),
        "severity": severity,
        "impeachment_candidate": impeachment_candidate,
        "attack_priority": attack_priority,
        "reason": "Conflicting claims detected.",
    }


def compare_claims(claims):
    findings = []

    if not claims:
        return findings

    for i, claim_a in enumerate(claims):
        for claim_b in claims[i + 1:]:
            if _is_conflict(claim_a, claim_b):
                findings.append(_build_finding(claim_a, claim_b))

    return findings


def find_contradictions(claims):
    return compare_claims(claims)


def build_contradiction_comparison(claims):
    return compare_claims(claims)
