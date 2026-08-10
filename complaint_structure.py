"""Deterministic complaint-structure extraction for derived-cache Phase 1.

Operates only on canonical page records. Emits a versioned structure map with
per-document provenance, exact observed markers, and explicit uncertainty.
Does not infer paragraph body text or fabricate unobserved paragraph numbers.

Schema ``complaint_structure_map.v1``
------------------------------------
Top-level object::

    {
      "schema_version": "complaint_structure_map.v1",
      "documents": [DocumentStructure, ...]  # sorted by nyscef_document_number
    }

``DocumentStructure``::

    {
      "document_id": "nyscef-003",
      "nyscef_document_number": 3,
      "source_pages": [
        {"page_id": "...", "page_number": 1, "nyscef_document_number": 3},
        ...
      ],
      "section_headings": [ObservedHeading, ...],
      "paragraph_numbers": [ObservedParagraph, ...],
      "contiguous_ranges": [ContiguousRange, ...],
      "missing_paragraph_numbers": [int, ...],
      "noncontiguous_sequences": [{"observed_numbers": [int, ...]}, ...],
      "uncertainties": [Uncertainty, ...]
    }

``ObservedHeading`` stores the exact ``observed_marker`` from the page text.
``match_key`` is a normalized known-heading family label used only for
classification; it is never substituted for the observed marker. Ambiguous or
OCR-uncertain hits set ``ambiguous`` / appear in ``uncertainties``.

``ContiguousRange`` is emitted only when every integer from ``start`` through
``end`` was observed in source records (endpoints and interior). Gaps become
``missing_paragraph_numbers`` and split ``noncontiguous_sequences``.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Optional, Sequence

SCHEMA_VERSION = "complaint_structure_map.v1"

# Known pleading section families (generic). Matching is case/OCR-tolerant;
# emitted markers remain exact observed surface forms.
_KNOWN_SECTION_PATTERNS: tuple[tuple[str, str], ...] = (
    ("overview", r"overview"),
    ("introduction", r"introduction"),
    ("preliminary_statement", r"preliminary\s+statement"),
    ("nature_of_the_action", r"nature\s+of\s+(?:the\s+)?action"),
    ("parties", r"(?:the\s+)?parties(?:\s+to\s+(?:this\s+)?(?:action|proceeding|litigation))?"),
    ("intervening_facts", r"intervening\s+facts?"),
    ("facts", r"facts?(?:\s+common\s+to\s+all\s+(?:counts|claims))?"),
    ("factual_background", r"factual\s+background"),
    ("background", r"background"),
    ("general_allegations", r"general\s+allegations"),
    ("jurisdiction_and_venue", r"jurisdiction\s+and\s+venue"),
    ("jurisdiction", r"jurisdiction"),
    ("venue", r"venue"),
    ("causes_of_action", r"causes?\s+of\s+action"),
    ("wherefore", r"wherefore"),
    ("prayer_for_relief", r"prayer\s+for\s+relief"),
)

_SECTION_PREFIX = (
    r"(?:"
    r"(?:section|article|part)\s+[ivxlcdm\d]+(?:\s*[.:=\-—–]\s*|\s+)|"
    r"(?:[ivxlcdm]+|\d+)(?:\.\d+)*[.)]?\s+"
    r")?"
)

# Line-oriented heading candidate: optional prefix + known name + optional colon.
_HEADING_LINE_RE = re.compile(
    r"(?im)^\s*"
    + _SECTION_PREFIX
    + r"(?P<body>"
    + r"|".join(f"(?:{pat})" for _, pat in _KNOWN_SECTION_PATTERNS)
    + r")"
    + r"\s*:?\s*$"
)

# Paragraph markers at line starts. Tolerates light OCR spacing around the
# delimiter (``1.``, ``1)``, ``1 .``) but requires a following non-space token.
_PARAGRAPH_MARKER_RE = re.compile(
    r"(?m)^[ \t]*(?P<marker>(?P<num>\d{1,4})[ \t]*[.)])[ \t]+\S"
)

# OCR: spaced-out single letters inside a heading token (``P A R T I E S``).
_OCR_LETTER_SPACED_RE = re.compile(
    r"\b(?:[A-Za-z](?:[ \t]+[A-Za-z]){2,})\b"
)


def document_id_for_nyscef(nyscef_document_number: int) -> str:
    return f"nyscef-{int(nyscef_document_number):03d}"


def is_current_structure_schema(payload: Any) -> bool:
    """True when ``payload`` carries the current structure-map schema version."""
    return (
        isinstance(payload, dict)
        and payload.get("schema_version") == SCHEMA_VERSION
        and isinstance(payload.get("documents"), list)
    )


def serialize_structure_map(payload: Mapping[str, Any]) -> str:
    """Deterministic JSON serialization for structure-map payloads."""
    import json

    return (
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
    )


def _collapse_ws(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text or "").strip()


def _heal_ocr_letter_spacing(text: str) -> str:
    """Join spaced-out letter runs for matching only; does not alter markers."""

    def _join(match: re.Match[str]) -> str:
        return re.sub(r"\s+", "", match.group(0))

    return _OCR_LETTER_SPACED_RE.sub(_join, text or "")


def _normalize_heading_match_text(text: str) -> str:
    healed = _heal_ocr_letter_spacing(text)
    healed = re.sub(r"\s+", " ", healed).strip().lower()
    healed = healed.rstrip(":").strip()
    return healed


def _match_key_for_heading_body(body: str) -> Optional[str]:
    normalized = _normalize_heading_match_text(body)
    if not normalized:
        return None
    for key, pat in _KNOWN_SECTION_PATTERNS:
        if re.fullmatch(pat, normalized, flags=re.IGNORECASE):
            return key
    # Retry after stripping a leading "the ".
    if normalized.startswith("the "):
        trimmed = normalized[4:]
        for key, pat in _KNOWN_SECTION_PATTERNS:
            if re.fullmatch(pat, trimmed, flags=re.IGNORECASE):
                return key
    return None


def _iter_page_records(
    page_records: Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if isinstance(page_records, Mapping):
        pages = page_records.get("pages") or []
    else:
        pages = page_records
    out: list[dict[str, Any]] = []
    for page in pages:
        if isinstance(page, dict):
            out.append(page)
    return out


def _page_provenance(page: Mapping[str, Any]) -> dict[str, Any]:
    nyscef = int(page["nyscef_document_number"])
    page_number = int(page["page_number"])
    page_id = page.get("page_id") or f"nyscef-{nyscef:03d}-page-{page_number:04d}"
    return {
        "nyscef_document_number": nyscef,
        "page_id": str(page_id),
        "page_number": page_number,
    }


def _extract_headings_from_page(
    page: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    text = page.get("text") if isinstance(page.get("text"), str) else ""
    prov = _page_provenance(page)
    headings: list[dict[str, Any]] = []
    uncertainties: list[dict[str, Any]] = []
    if not text:
        return headings, uncertainties

    # Match against OCR-healed text for detection, but slice exact markers from
    # the original line so observed_marker stays faithful to source records.
    original_lines = text.splitlines()
    healed_lines = [_heal_ocr_letter_spacing(line) for line in original_lines]
    # Optional numeric section prefix only (article/section/part) — not pleading
    # paragraph markers like ``10. Overview ...``.
    _heading_label_prefix = (
        r"(?:"
        r"(?:section|article|part)\s+[ivxlcdm\d]+(?:\s*[.:=\-—–]\s*|\s+)|"
        r"(?:[ivxlcdm]+)[.)]?\s+"
        r")?"
    )
    _ambiguous_heading_re = re.compile(
        r"(?i)^\s*"
        + _heading_label_prefix
        + r"(?P<body>"
        + r"|".join(f"(?:{pat})" for _, pat in _KNOWN_SECTION_PATTERNS)
        + r")\b"
    )

    for idx, healed_line in enumerate(healed_lines):
        match = _HEADING_LINE_RE.match(healed_line)
        if match:
            body = match.group("body")
            key = _match_key_for_heading_body(body)
            observed = _collapse_ws(original_lines[idx])
            ocr_healed = _heal_ocr_letter_spacing(original_lines[idx])
            ambiguous = False
            ambiguity_note = None
            if _collapse_ws(ocr_healed) != observed and key is not None:
                # OCR spacing differed; marker preserved, uncertainty recorded.
                uncertainties.append(
                    {
                        "kind": "ocr_heading_variation",
                        "observed_marker": observed,
                        "page_id": prov["page_id"],
                        "page_number": prov["page_number"],
                        "detail": "matched_after_ocr_letter_spacing_heal",
                    }
                )
            if key is None:
                ambiguous = True
                ambiguity_note = "unclassified_heading_shape"
                uncertainties.append(
                    {
                        "kind": "ambiguous_heading",
                        "observed_marker": observed,
                        "page_id": prov["page_id"],
                        "page_number": prov["page_number"],
                        "detail": ambiguity_note,
                    }
                )

            headings.append(
                {
                    "ambiguous": ambiguous,
                    "ambiguity_note": ambiguity_note,
                    "match_key": key,
                    "observed_marker": observed,
                    "page_id": prov["page_id"],
                    "page_number": prov["page_number"],
                    "line_index": idx,
                }
            )
            continue

        # Numbered allegation lines are paragraph observations, not headings.
        if _PARAGRAPH_MARKER_RE.match(healed_line):
            continue

        # Ambiguous: line looks like a known heading family but has trailing
        # prose (not a clean heading line).
        stripped = healed_line.strip()
        if not stripped:
            continue
        body_guess = _ambiguous_heading_re.match(stripped)
        if body_guess:
            rest = stripped[body_guess.end() :].strip().lstrip(":").strip()
            if rest:
                key = _match_key_for_heading_body(body_guess.group("body"))
                observed = _collapse_ws(original_lines[idx])
                headings.append(
                    {
                        "ambiguous": True,
                        "ambiguity_note": "heading_token_with_trailing_prose",
                        "match_key": key,
                        "observed_marker": observed,
                        "page_id": prov["page_id"],
                        "page_number": prov["page_number"],
                        "line_index": idx,
                    }
                )
                uncertainties.append(
                    {
                        "kind": "ambiguous_heading",
                        "observed_marker": observed,
                        "page_id": prov["page_id"],
                        "page_number": prov["page_number"],
                        "detail": "heading_token_with_trailing_prose",
                    }
                )

    return headings, uncertainties


def _extract_paragraphs_from_page(
    page: Mapping[str, Any],
) -> list[dict[str, Any]]:
    text = page.get("text") if isinstance(page.get("text"), str) else ""
    prov = _page_provenance(page)
    found: list[dict[str, Any]] = []
    if not text:
        return found

    seen_on_page: set[int] = set()
    for match in _PARAGRAPH_MARKER_RE.finditer(text):
        line_start = text.rfind("\n", 0, match.start()) + 1
        line_end = text.find("\n", match.start())
        if line_end < 0:
            line_end = len(text)
        line = text[line_start:line_end]
        # Skip numbered section-heading lines (``14. PARTIES``) — those are
        # headings, not allegation paragraph markers.
        if _HEADING_LINE_RE.match(_heal_ocr_letter_spacing(line)):
            continue
        try:
            number = int(match.group("num"))
        except (TypeError, ValueError):
            continue
        if number in seen_on_page:
            continue
        seen_on_page.add(number)
        marker = _collapse_ws(match.group("marker"))
        # Normalize light OCR spacing inside the marker for the observed form
        # while keeping the delimiter character (``1.`` / ``1)``).
        marker = re.sub(r"\s+", "", marker)
        found.append(
            {
                "number": number,
                "observed_marker": marker,
                "page_id": prov["page_id"],
                "page_number": prov["page_number"],
            }
        )
    return found


def _contiguous_ranges_and_gaps(
    numbers: Sequence[int],
) -> tuple[list[dict[str, Any]], list[int], list[dict[str, Any]]]:
    """Build supported contiguous ranges; never invent unobserved numbers."""
    unique = sorted({int(n) for n in numbers})
    if not unique:
        return [], [], []

    ranges: list[dict[str, Any]] = []
    missing: list[int] = []
    sequences: list[dict[str, Any]] = []

    run: list[int] = [unique[0]]
    for num in unique[1:]:
        prev = run[-1]
        if num == prev + 1:
            run.append(num)
            continue
        # Gap between prev and num — record missing interiors only.
        for gap in range(prev + 1, num):
            missing.append(gap)
        ranges.append(
            {
                "start": run[0],
                "end": run[-1],
                "observed_numbers": list(run),
            }
        )
        sequences.append({"observed_numbers": list(run)})
        run = [num]

    ranges.append(
        {
            "start": run[0],
            "end": run[-1],
            "observed_numbers": list(run),
        }
    )
    sequences.append({"observed_numbers": list(run)})

    # A single contiguous span is not "noncontiguous".
    if len(sequences) == 1:
        noncontiguous: list[dict[str, Any]] = []
    else:
        noncontiguous = sequences

    return ranges, missing, noncontiguous


def extract_document_structure(
    document_pages: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Extract structure for one document's canonical pages (already grouped)."""
    pages = sorted(
        [p for p in document_pages if isinstance(p, dict)],
        key=lambda p: int(p.get("page_number") or 0),
    )
    if not pages:
        raise ValueError("document_pages must be non-empty")

    nyscef = int(pages[0]["nyscef_document_number"])
    source_pages = [_page_provenance(p) for p in pages]

    section_headings: list[dict[str, Any]] = []
    paragraph_numbers: list[dict[str, Any]] = []
    uncertainties: list[dict[str, Any]] = []

    for page in pages:
        if int(page.get("nyscef_document_number") or -1) != nyscef:
            raise ValueError(
                "extract_document_structure received mixed document pages"
            )
        headings, heading_uncertainties = _extract_headings_from_page(page)
        section_headings.extend(headings)
        uncertainties.extend(heading_uncertainties)
        paragraph_numbers.extend(_extract_paragraphs_from_page(page))

    # Deterministic ordering: page, then source line order.
    section_headings.sort(
        key=lambda h: (
            int(h["page_number"]),
            int(h.get("line_index") or 0),
            str(h["observed_marker"]),
            bool(h.get("ambiguous")),
        )
    )
    # Drop internal line_index from public schema payload.
    for heading in section_headings:
        heading.pop("line_index", None)

    paragraph_numbers.sort(
        key=lambda p: (
            int(p["page_number"]),
            int(p["number"]),
            str(p["observed_marker"]),
        )
    )

    # Deduplicate identical paragraph number observations across pages by first
    # occurrence order (already sorted); keep first provenance only.
    deduped_paragraphs: list[dict[str, Any]] = []
    seen_nums: set[int] = set()
    for item in paragraph_numbers:
        num = int(item["number"])
        if num in seen_nums:
            uncertainties.append(
                {
                    "kind": "duplicate_paragraph_number",
                    "observed_marker": item["observed_marker"],
                    "page_id": item["page_id"],
                    "page_number": item["page_number"],
                    "detail": f"paragraph_{num}_already_observed",
                }
            )
            continue
        seen_nums.add(num)
        deduped_paragraphs.append(item)

    observed_nums = [int(p["number"]) for p in deduped_paragraphs]
    contiguous_ranges, missing, noncontiguous = _contiguous_ranges_and_gaps(
        observed_nums
    )
    if missing:
        uncertainties.append(
            {
                "kind": "missing_paragraph_numbers",
                "detail": "unobserved_interior_numbers",
                "missing_paragraph_numbers": list(missing),
            }
        )
    if noncontiguous:
        uncertainties.append(
            {
                "kind": "noncontiguous_paragraph_sequence",
                "detail": "observed_numbers_are_not_a_single_contiguous_span",
                "sequences": list(noncontiguous),
            }
        )

    return {
        "document_id": document_id_for_nyscef(nyscef),
        "nyscef_document_number": nyscef,
        "source_pages": source_pages,
        "section_headings": section_headings,
        "paragraph_numbers": deduped_paragraphs,
        "contiguous_ranges": contiguous_ranges,
        "missing_paragraph_numbers": missing,
        "noncontiguous_sequences": noncontiguous,
        "uncertainties": uncertainties,
    }


def build_complaint_structure_map(
    page_records: Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a deterministic multi-document complaint structure map."""
    pages = _iter_page_records(page_records)
    by_doc: dict[int, list[dict[str, Any]]] = {}
    for page in pages:
        nyscef = page.get("nyscef_document_number")
        if nyscef is None:
            continue
        by_doc.setdefault(int(nyscef), []).append(page)

    documents = [
        extract_document_structure(by_doc[nyscef])
        for nyscef in sorted(by_doc.keys())
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "documents": documents,
    }


def empty_complaint_structure_map() -> dict[str, Any]:
    """Empty but schema-valid structure map (for validation fixtures)."""
    return {"schema_version": SCHEMA_VERSION, "documents": []}
