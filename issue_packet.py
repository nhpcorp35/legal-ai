"""Fail-closed sourced issue packets for attorney review.

This module does not research or decide a legal question.  It validates the
structure of a proposed packet so that legal authorities, record proof,
requested relief, and local-practice uncertainty stay visibly separated.
"""

from __future__ import annotations

from typing import Any, Mapping

from active_matter_review import ActiveMatterReviewError, validate_candidate


AUTHORITY_TYPES = {"statute", "regulation", "case", "local_practice"}


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


def _required(payload: Mapping[str, Any], field: str) -> str:
    value = _text(payload.get(field))
    if not value:
        raise ActiveMatterReviewError(f"issue packet {field} is required")
    return value


def validate_issue_packet(
    packet: Mapping[str, Any], page_index: Mapping[tuple[int, int], Mapping[str, Any]]
) -> dict[str, Any]:
    """Validate a packet without converting it into legal advice.

    Existing record-proof validation is reused.  Each asserted legal authority
    must include a citation, stable source URL, and a constrained proposition.
    Local-practice entries always remain attorney/clerk-confirmation items.
    """
    if not isinstance(packet, Mapping):
        raise ActiveMatterReviewError("issue packet must be an object")
    issue = _required(packet, "issue")
    candidate = validate_candidate(packet, page_index)
    raw_authorities = packet.get("authorities")
    if not isinstance(raw_authorities, list) or not raw_authorities:
        raise ActiveMatterReviewError("issue packet requires at least one authority")
    authorities: list[dict[str, Any]] = []
    for number, raw in enumerate(raw_authorities, start=1):
        if not isinstance(raw, Mapping):
            raise ActiveMatterReviewError(f"authority {number} must be an object")
        kind = _text(raw.get("type")).lower()
        if kind not in AUTHORITY_TYPES:
            raise ActiveMatterReviewError(f"authority {number} type is invalid")
        citation = _required(raw, "citation")
        source_url = _required(raw, "source_url")
        if not source_url.startswith("https://"):
            raise ActiveMatterReviewError(f"authority {number} source_url must use https")
        proposition = _required(raw, "proposition")
        authorities.append({
            "type": kind,
            "citation": citation,
            "source_url": source_url,
            "proposition": proposition,
            "pinpoint": _text(raw.get("pinpoint")),
            "attorney_clerk_confirmation_required": kind == "local_practice",
        })
    raw_relief = packet.get("relief")
    if not isinstance(raw_relief, list) or not raw_relief:
        raise ActiveMatterReviewError("issue packet requires at least one relief item")
    relief: list[dict[str, str]] = []
    for number, raw in enumerate(raw_relief, start=1):
        if not isinstance(raw, Mapping):
            raise ActiveMatterReviewError(f"relief {number} must be an object")
        relief.append({
            "requested_relief": _required(raw, "requested_relief"),
            "legal_prerequisites": _required(raw, "legal_prerequisites"),
            "record_support_or_gap": _required(raw, "record_support_or_gap"),
        })
    return {
        "schema_version": "sourced-issue-packet.v1",
        "issue": issue,
        "candidate": candidate,
        "authorities": authorities,
        "relief": relief,
        "attorney_confirmation_required": any(item["attorney_clerk_confirmation_required"] for item in authorities),
        "attorney_approved": False,
    }


def render_issue_packet(packet: Mapping[str, Any]) -> str:
    """Render a compact attorney-review packet from validated packet data."""
    candidate = packet["candidate"]
    lines = [
        "# Sourced Issue Packet",
        "",
        "> **Status: CANDIDATE — NOT ATTORNEY-APPROVED.** This packet organizes sources and record proof; it does not provide a legal conclusion.",
        "",
        "## Issue",
        "",
        str(packet["issue"]),
        "",
        "## Controlling Authorities",
        "",
    ]
    for item in packet["authorities"]:
        lines.append(f"- **{item['citation']}** ({item['type']}) — {item['proposition']} [source]({item['source_url']})")
        if item["pinpoint"]:
            lines.append(f"  - Pinpoint: {item['pinpoint']}")
        if item["attorney_clerk_confirmation_required"]:
            lines.append("  - **Attorney/clerk confirmation required; local-practice item.**")
    lines.extend(["", "## Record Proof", ""])
    for finding in candidate["findings"]:
        lines.append(f"- **{finding['statement']}** ({finding['confidence']})")
        for evidence in finding["evidence"]:
            lines.append(f"  - NYSCEF {evidence['nyscef_document_number']}, p. {evidence['page_number']}: {evidence['quote']}")
    lines.extend(["", "## Relief Mapping", ""])
    for item in packet["relief"]:
        lines.extend([
            f"- **{item['requested_relief']}**",
            f"  - Prerequisites: {item['legal_prerequisites']}",
            f"  - Record support / gap: {item['record_support_or_gap']}",
        ])
    lines.extend(["", "## Attorney Decision", "", "- [ ] Accept", "- [ ] Revise", "- [ ] Reject", "- [ ] Confirm local procedure with clerk", ""])
    return "\n".join(lines)
