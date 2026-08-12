"""Privacy-safe Q2 production evidence-routing diagnostics.

Observes the production path from restored derived-cache evidence through
relief synthesis, OCR readability rejection/scrub, canonicalization, and
acceptance validation. Emits machine-readable metadata only:

- stage names
- Python/container type names
- allowlisted field names and nesting shape
- record counts
- category/kind labels
- citation/page IDs already safe for audit
- boolean flags for verified support and semantic detections
- excerpt/page_text presence booleans and character lengths
- readability-gate reason codes
- selection/handoff/fallback reason codes
- nonreversible SHA-256 hashes for correlation

Never records raw source text, OCR text, excerpts, proposed-answer text,
party/person names, emails, credentials, environment values, or full private
object payloads. Does not alter synthesis, matching, fallback, acceptance
criteria, or output prose.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Optional, Sequence

from engines import drafting_engine as de

DIAGNOSTIC_SCHEMA_VERSION = "q2_production_evidence_diagnostics.v1"
DIAGNOSTIC_RESULT_KEY = "q2_production_evidence_diagnostics"

# Public correlation salt (not a secret). Prevents trivial rainbow lookup of
# common phrases while remaining stable across runs for the same payload.
_HASH_SALT = "q2-prod-evidence-diag-v1"

_RELIEF_CATEGORIES = (
    "rescission_void_ab_initio",
    "no_defense_or_indemnity",
    "catch_all_relief",
)

# Allowlisted keys that may appear on restored-cache / evidence-packet hits.
_HIT_FIELD_ALLOWLIST = frozenset(
    {
        "result_id",
        "page_id",
        "nyscef_document_number",
        "pdf_page",
        "source_filename",
        "document_type",
        "excerpt",
        "page_text",
        "full_page_text",
        "classifications",
        "assertion_kind",
        "case_map_linkage",
        "exhibit_segment",
        "score",
    }
)

# Quote pattern mirrors the generator scrubber (text never retained).
_CITED_PLEADING_LANGUAGE_QUOTE_RE = re.compile(
    r'as reflected in the cited pleading language:\s*"((?:[^"\\]|\\.)*)"'
    r'(?P<cite>\s*\(\s*page_id\s+[^)]+\))?',
    flags=re.IGNORECASE | re.DOTALL,
)

# String values permitted in the serialized diagnostic (keys are separate).
# Anything else that looks like free text is rejected by the sanitizer.
_SAFE_STRING_KEYS = frozenset(
    {
        "schema_version",
        "stage",
        "python_type",
        "container_type",
        "category",
        "kind",
        "page_id",
        "result_id",
        "document_type",
        "assertion_kind",
        "criterion_id",
        "presence",
        "evidence",
        "semantic",
        "result_code",
        "duplication_result",
        "fallback_action",
        "selection_reason_code",
        "handoff_reason_code",
        "readability_gate_reason_code",
        "sha256",
        "field_name",
        "corpus_source",
        "display_path",
        "lead_category",
    }
)

# List keys whose string members are reason codes / field names / diagnostics.
_SAFE_STRING_LIST_KEYS = frozenset(
    {
        "allowlisted_fields_present",
        "readability_gate_reason_codes",
        "sibling_verified_categories",
        "q2_no_defense_focus_reason_codes",
        "relief_supported_categories",
        "diagnostics",
        "fallback_actions",
    }
)

_REASON_OR_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


def _type_name(value: Any) -> str:
    return type(value).__name__


def _sha256_salted(text: str) -> str:
    payload = f"{_HASH_SALT}:{text}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _text_meta(value: Any) -> dict[str, Any]:
    """Presence + length + optional hash; never the text itself."""
    if value is None:
        return {
            "present": False,
            "char_length": 0,
            "sha256": None,
        }
    text = str(value)
    stripped = text.strip()
    return {
        "present": bool(stripped),
        "char_length": len(text),
        "sha256": _sha256_salted(text) if stripped else None,
    }


def _field_nesting_shape(hit: Mapping[str, Any]) -> dict[str, str]:
    shape: dict[str, str] = {}
    for key in sorted(_HIT_FIELD_ALLOWLIST):
        if key not in hit:
            continue
        shape[key] = _type_name(hit.get(key))
    return shape


def diagnose_restored_cache_evidence(
    evidence_packet: Optional[Mapping[str, Any]],
) -> dict[str, Any]:
    """Stage: restored derived-cache / evidence-packet hit shape."""
    packet = evidence_packet or {}
    hits_raw = packet.get("retrieval_hits") or []
    hits = [h for h in hits_raw if isinstance(h, Mapping)]
    records: list[dict[str, Any]] = []
    for hit in hits:
        excerpt_meta = _text_meta(hit.get("excerpt"))
        page_text_meta = _text_meta(
            hit.get("page_text") if hit.get("page_text") is not None else hit.get("full_page_text")
        )
        corpus = de._relief_hit_corpus(hit)  # noqa: SLF001 — observational only
        corpus_meta = _text_meta(corpus)
        excerpt = de.normalize_whitespace(hit.get("excerpt") or "")
        page_text = de.normalize_whitespace(
            hit.get("page_text") or hit.get("full_page_text") or ""
        )
        if excerpt and page_text and excerpt in page_text:
            corpus_source = "excerpt_slice_of_page"
            if corpus_meta["char_length"] == page_text_meta["char_length"] and (
                page_text_meta["char_length"] > excerpt_meta["char_length"]
            ):
                corpus_source = "full_page_preferred_over_truncated_excerpt"
        elif page_text and (not excerpt or len(page_text) > len(excerpt)):
            corpus_source = "page_text"
        elif excerpt:
            corpus_source = "excerpt"
        else:
            corpus_source = "empty"

        allowlisted_present = sorted(
            key for key in hit.keys() if key in _HIT_FIELD_ALLOWLIST
        )
        records.append(
            {
                "python_type": _type_name(hit),
                "allowlisted_fields_present": allowlisted_present,
                "field_nesting_shape": [
                    {"field_name": name, "python_type": typ}
                    for name, typ in _field_nesting_shape(hit).items()
                ],
                "page_id": hit.get("page_id"),
                "result_id": hit.get("result_id"),
                "document_type": hit.get("document_type"),
                "assertion_kind": hit.get("assertion_kind"),
                "nyscef_document_number": hit.get("nyscef_document_number"),
                "pdf_page": hit.get("pdf_page"),
                "excerpt": excerpt_meta,
                "page_text": page_text_meta,
                "corpus": corpus_meta,
                "corpus_source": corpus_source,
                "excerpt_equals_page_text": bool(
                    excerpt and page_text and excerpt == page_text
                ),
            }
        )
    return {
        "stage": "restored_derived_cache_evidence",
        "container_type": _type_name(packet),
        "retrieval_hit_count": int(packet.get("retrieval_hit_count") or len(hits)),
        "hit_record_count": len(hits),
        "hits": records,
    }


def diagnose_relief_synthesis(
    evidence_packet: Optional[Mapping[str, Any]],
    reasoner_result: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Stage: extract_supported_complaint_relief + synthesis audit flags."""
    supported = de.extract_supported_complaint_relief(evidence_packet)
    categories: dict[str, Any] = {}
    for key in _RELIEF_CATEGORIES:
        meta = supported.get(key) or {}
        snippet = str(meta.get("evidence_snippet") or "")
        snippet_meta = _text_meta(snippet)
        gate_codes = list(de.readability_gate_reason_codes(snippet)) if snippet else []
        clean = (
            de.prefer_clean_relief_display_excerpt(snippet, category=key)
            if snippet
            else ""
        )
        clean_meta = _text_meta(clean)
        categories[key] = {
            "category": key,
            "supported": bool(meta.get("supported")),
            "page_id": meta.get("page_id"),
            "nyscef_document_number": meta.get("nyscef_document_number"),
            "pdf_page": meta.get("pdf_page"),
            "evidence_snippet": snippet_meta,
            "readability_gate_failed": bool(gate_codes),
            "readability_gate_reason_codes": gate_codes,
            "clean_excerpt_available": bool(clean.strip()),
            "clean_excerpt": clean_meta,
            "selection_reason_code": (
                "supported_with_clean_excerpt"
                if meta.get("supported") and clean.strip()
                else (
                    "supported_needs_paraphrase"
                    if meta.get("supported") and gate_codes
                    else (
                        "supported_readable_snippet"
                        if meta.get("supported")
                        else "unsupported"
                    )
                )
            ),
        }

    audit = {}
    if isinstance(reasoner_result, Mapping):
        raw_audit = reasoner_result.get("audit") or {}
        if isinstance(raw_audit, Mapping):
            audit = {
                "relief_synthesis_applied": bool(
                    raw_audit.get("relief_synthesis_applied")
                ),
                "relief_supported_categories": [
                    str(c)
                    for c in (raw_audit.get("relief_supported_categories") or [])
                    if str(c) in _RELIEF_CATEGORIES
                ],
            }

    return {
        "stage": "relief_synthesis",
        "category_count": len(_RELIEF_CATEGORIES),
        "supported_category_count": sum(
            1 for c in categories.values() if c.get("supported")
        ),
        "categories": categories,
        "audit_flags": audit,
    }


def _decode_literal_escape_artifacts(text: str) -> str:
    raw = str(text or "")
    if "\\n" in raw or "\\t" in raw or "\\r" in raw:
        return (
            raw.replace("\\r\\n", "\n")
            .replace("\\n", "\n")
            .replace("\\r", "\n")
            .replace("\\t", "\t")
        )
    return raw


def diagnose_ocr_scrub_and_handoff(proposed_answer: str) -> dict[str, Any]:
    """Stage: OCR readability rejection / scrub / handoff (observational)."""
    source = str(proposed_answer or "")
    quotes: list[dict[str, Any]] = []
    for match in _CITED_PLEADING_LANGUAGE_QUOTE_RE.finditer(source):
        quote = match.group(1)
        cite = match.group("cite") or ""
        quote_text = _decode_literal_escape_artifacts(quote)
        page_id = None
        cite_match = re.search(
            r"page_id\s+([^)]+)", cite or "", flags=re.IGNORECASE
        )
        if cite_match:
            page_id = cite_match.group(1).strip()

        lead_start = max(0, match.start() - 240)
        lead_text = source[lead_start : match.start()]
        lead_category = de.infer_relief_lead_category(lead_text)
        gate_codes = list(de.readability_gate_reason_codes(quote_text))
        gate_failed = bool(gate_codes)
        verified = de.extract_verified_relief_support_from_text(
            quote_text, page_id=page_id
        )
        verified_flags = {
            key: bool((verified.get(key) or {}).get("supported"))
            for key in _RELIEF_CATEGORIES
        }
        clean = ""
        if lead_category:
            clean = de.prefer_clean_relief_display_excerpt(
                quote_text, category=lead_category
            )
        clean_meta = _text_meta(clean)
        if not gate_failed and clean and not de.displayed_quote_fails_readability_gate(
            clean
        ):
            handoff_reason = "clean_excerpt_retained"
            display_path = "quoted_clean_excerpt"
        elif gate_failed and clean and not de.displayed_quote_fails_readability_gate(
            clean
        ):
            handoff_reason = "ocr_rejected_clean_excerpt_selected"
            display_path = "quoted_clean_excerpt"
        elif any(verified_flags.values()):
            handoff_reason = "ocr_rejected_paraphrase_originating_page"
            display_path = "paraphrase_originating_page"
        else:
            handoff_reason = "fail_closed_no_verified_support"
            display_path = "paraphrase_originating_page"

        sibling_verified = [
            key
            for key, flag in verified_flags.items()
            if flag and key != lead_category
        ]
        quotes.append(
            {
                "page_id": page_id,
                "lead_category": lead_category,
                "quote": _text_meta(quote_text),
                "readability_gate_failed": gate_failed,
                "readability_gate_reason_codes": gate_codes,
                "verified_support_flags": verified_flags,
                "clean_excerpt_available": bool(str(clean).strip()),
                "clean_excerpt": clean_meta,
                "handoff_reason_code": handoff_reason,
                "display_path": display_path,
                "sibling_verified_categories": sibling_verified,
                "sibling_append_candidate_count": len(sibling_verified),
            }
        )

    return {
        "stage": "ocr_readability_scrub_handoff",
        "proposed_answer": _text_meta(source),
        "cited_quote_count": len(quotes),
        "quotes": quotes,
    }


def diagnose_canonical_and_acceptance(
    *,
    proposed_before_canonical: Optional[str] = None,
    canonical: Optional[str] = None,
    validation: Any = None,
) -> dict[str, Any]:
    """Stage: canonical_proposed_answer + acceptance validation (safe fields)."""
    criterion_rows: list[dict[str, Any]] = []
    fallback_actions: dict[str, str] = {}
    diagnostics: list[str] = []
    duplication_result = None
    validation_ok = None
    if validation is not None:
        validation_ok = bool(getattr(validation, "ok", None))
        duplication_result = getattr(validation, "duplication_result", None)
        diagnostics = [
            str(d) for d in (getattr(validation, "diagnostics", None) or [])
        ]
        raw_fallback = getattr(validation, "fallback_actions", None) or {}
        if isinstance(raw_fallback, Mapping):
            fallback_actions = {str(k): str(v) for k, v in raw_fallback.items()}
        for row in getattr(validation, "criterion_results", None) or []:
            criterion_rows.append(
                {
                    "criterion_id": getattr(row, "criterion_id", None),
                    "presence": getattr(row, "presence", None),
                    "evidence": getattr(row, "evidence", None),
                    "semantic": getattr(row, "semantic", None),
                    "result_code": getattr(row, "result_code", None),
                    "diagnostics": [
                        str(d) for d in (getattr(row, "diagnostics", None) or [])
                    ],
                }
            )

    no_defense = next(
        (
            r
            for r in criterion_rows
            if r.get("criterion_id") == "q2-no-defense-or-indemnity"
        ),
        None,
    )
    focus_reason_codes: list[str] = []
    if no_defense is not None:
        if no_defense.get("presence") in {None, "absent"} or str(
            no_defense.get("result_code") or ""
        ).endswith("missing"):
            focus_reason_codes.append("criterion_absent_or_missing")
        if no_defense.get("evidence") == "evidence_unsupported" or str(
            no_defense.get("result_code") or ""
        ).endswith("unsupported"):
            focus_reason_codes.append("evidence_unsupported")
        skipped = fallback_actions.get("q2-no-defense-or-indemnity")
        if skipped == "fallback_skipped_unsupported" or any(
            d == "fallback_skipped_unsupported:q2-no-defense-or-indemnity"
            for d in diagnostics
        ):
            focus_reason_codes.append("fallback_skipped_unsupported")

    return {
        "stage": "canonical_proposed_answer_and_acceptance",
        "proposed_before_canonical": _text_meta(proposed_before_canonical),
        "canonical": _text_meta(canonical),
        "canonical_changed": bool(
            str(proposed_before_canonical or "") != str(canonical or "")
        ),
        "validation_ok": validation_ok,
        "duplication_result": duplication_result,
        "diagnostics": diagnostics,
        # List form keeps criterion_id / fallback_action under allowlisted keys.
        "fallback_actions": [
            {"criterion_id": cid, "fallback_action": action}
            for cid, action in sorted(fallback_actions.items())
        ],
        "criterion_results": criterion_rows,
        "q2_no_defense_or_indemnity": no_defense,
        "q2_no_defense_focus_reason_codes": focus_reason_codes,
    }


def _sanitize_value(key: Optional[str], value: Any) -> Any:
    """Fail-closed sanitizer: drop non-allowlisted free-text strings."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if _SHA256_RE.fullmatch(value):
            return value
        if key in _SAFE_STRING_KEYS:
            if len(value) > 200:
                return None
            if not _REASON_OR_ID_RE.fullmatch(value):
                return None
            return value
        if key in _SAFE_STRING_LIST_KEYS:
            if len(value) <= 160 and _REASON_OR_ID_RE.fullmatch(value):
                return value
            return None
        # Unknown key holding a string → drop (fail closed).
        return None
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for raw_k, raw_v in value.items():
            k = str(raw_k)
            cleaned = _sanitize_value(k, raw_v)
            if cleaned is None and raw_v is not None and not isinstance(
                raw_v, (bool, int, float)
            ):
                continue
            out[k] = cleaned
        return out
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        out_list: list[Any] = []
        for item in value:
            if isinstance(item, str):
                cleaned_str = _sanitize_value(key, item)
                if cleaned_str is not None:
                    out_list.append(cleaned_str)
                continue
            cleaned_item = _sanitize_value(key, item)
            if cleaned_item is None and item is not None and not isinstance(
                item, (bool, int, float)
            ):
                continue
            out_list.append(cleaned_item)
        return out_list
    # Unknown objects → type name only
    return _type_name(value)


def sanitize_diagnostic(diagnostic: Mapping[str, Any]) -> dict[str, Any]:
    """Return a sanitizer-filtered copy safe for stdout / JSON artifacts."""
    cleaned = _sanitize_value(None, dict(diagnostic))
    if not isinstance(cleaned, dict):
        return {
            "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
            "stage": "sanitizer_fail_closed",
        }
    cleaned["schema_version"] = DIAGNOSTIC_SCHEMA_VERSION
    return cleaned


PREFLIGHT_REPLAY_SCHEMA_VERSION = "q2_production_boundary_preflight_replay.v1"


def build_sanitized_preflight_replay(
    evidence_packet: Optional[Mapping[str, Any]],
    *,
    question_id: str = "Q2",
) -> dict[str, Any]:
    """Build a privacy-safe preflight replay from a live evidence packet.

    Invokes the same restored-cache + relief-synthesis observers used by
    production diagnostics, then fail-closed sanitizes. The replay retains only
    allowlisted structure, safe citation/page IDs, booleans, reason codes,
    counts, lengths, and nonreversible hashes — never source or answer text.
    """
    qid = str(question_id or "Q2").strip() or "Q2"
    raw = {
        "schema_version": PREFLIGHT_REPLAY_SCHEMA_VERSION,
        "question_id": qid,
        "cache_evidence": diagnose_restored_cache_evidence(evidence_packet),
        "relief_synthesis": diagnose_relief_synthesis(evidence_packet),
    }
    cleaned = _sanitize_value(None, raw)
    if not isinstance(cleaned, dict):
        return {
            "schema_version": PREFLIGHT_REPLAY_SCHEMA_VERSION,
            "stage": "sanitizer_fail_closed",
            "question_id": qid,
        }
    cleaned["schema_version"] = PREFLIGHT_REPLAY_SCHEMA_VERSION
    cleaned["question_id"] = qid
    return cleaned


def build_q2_production_evidence_diagnostics(
    *,
    evidence_packet: Optional[Mapping[str, Any]] = None,
    reasoner_result: Optional[Mapping[str, Any]] = None,
    proposed_before_canonical: Optional[str] = None,
    canonical: Optional[str] = None,
    validation: Any = None,
) -> dict[str, Any]:
    """Assemble the full multi-stage privacy-safe diagnostic record."""
    proposed = proposed_before_canonical
    if proposed is None and isinstance(reasoner_result, Mapping):
        proposed = str(reasoner_result.get("proposed_answer") or "")
    if canonical is None:
        canonical = proposed

    record = {
        "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "stages": [
            diagnose_restored_cache_evidence(evidence_packet),
            diagnose_relief_synthesis(evidence_packet, reasoner_result),
            diagnose_ocr_scrub_and_handoff(str(proposed or "")),
            diagnose_canonical_and_acceptance(
                proposed_before_canonical=proposed,
                canonical=canonical,
                validation=validation,
            ),
        ],
    }
    return sanitize_diagnostic(record)


def diagnostic_json_bytes(diagnostic: Mapping[str, Any]) -> bytes:
    """Canonical JSON serialization for artifacts / leak assertions."""
    return json.dumps(
        sanitize_diagnostic(diagnostic),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def assert_no_forbidden_substrings(
    diagnostic: Mapping[str, Any],
    forbidden: Sequence[str],
) -> None:
    """Raise AssertionError if any forbidden private string appears."""
    blob = diagnostic_json_bytes(diagnostic).decode("utf-8")
    for item in forbidden:
        if item and item in blob:
            raise AssertionError(
                "privacy-safe diagnostic leaked forbidden substring"
            )
