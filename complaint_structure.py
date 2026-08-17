"""Deterministic complaint-structure extraction and party-role roadmap context.

Operates only on canonical page records. Emits a versioned structure map with
per-document provenance, exact observed markers, and explicit uncertainty.
Does not infer paragraph body text or fabricate unobserved paragraph numbers.

Before extraction, selects a single controlling complaint from authoritative
filing metadata and document provenance (document_type / title /
classification / source_filename, optionally filing-inventory fields). Answers,
amended answers, affidavits, motions, exhibits, and other response pleadings
are excluded even when they quote complaint headings or paragraph numbers.
Ambiguous or absent complaint metadata fails closed with an explicit selection
status and an empty documents list — never a merged multi-pleading roadmap.

Phase 2 consumers build a compact, provenance-backed party-role roadmap from
``complaint_structure_map.v2`` (overview, intervening factual/background, and
party-identification sections). Stale or absent schema fails closed at cache
validation and degrades explicitly in evidence packets — never fabricated.

Schema ``complaint_structure_map.v2``
------------------------------------
Top-level object::

    {
      "schema_version": "complaint_structure_map.v2",
      "selection": {
        "status": "selected|ambiguous|unavailable",
        "reason": null | str,
        "controlling_nyscef_document_number": int | null,
        "candidate_nyscef_document_numbers": [int, ...],
        "excluded_nyscef_document_numbers": [int, ...]
      },
      "documents": [DocumentStructure, ...]  # controlling complaint only
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
      "sections": [StructureSection, ...],  # heading-bound observed paras
      "contiguous_ranges": [ContiguousRange, ...],
      "missing_paragraph_numbers": [int, ...],
      "noncontiguous_sequences": [{"observed_numbers": [int, ...]}, ...],
      "uncertainties": [Uncertainty, ...]
    }

``ObservedHeading`` stores the exact ``observed_marker`` from the page text.
``match_key`` is a normalized known-heading family label used only for
classification; it is never substituted for the observed marker. Ambiguous or
OCR-uncertain hits set ``ambiguous`` / appear in ``uncertainties``.

``StructureSection`` binds observed paragraph numbers to the preceding section
heading using source page/line order. ``paragraph_range`` is emitted only when
the section's observed numbers form a contiguous sequence; gaps and
heading-only sections record explicit uncertainty instead of inventing ranges.

``ContiguousRange`` is emitted only when every integer from ``start`` through
``end`` was observed in source records (endpoints and interior). Gaps become
``missing_paragraph_numbers`` and split ``noncontiguous_sequences``.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Optional, Sequence

SCHEMA_VERSION = "complaint_structure_map.v2"

# Selection statuses for the controlling complaint document.
SELECTION_STATUS_SELECTED = "selected"
SELECTION_STATUS_AMBIGUOUS = "ambiguous"
SELECTION_STATUS_UNAVAILABLE = "unavailable"

# Non-complaint filings that may quote complaint headings/paragraph numbers.
_EXCLUDED_FILING_TYPE_TOKENS = frozenset(
    {
        "answer",
        "amended_answer",
        "affidavit",
        "affirmation",
        "declaration",
        "motion",
        "exhibit",
        "opposition",
        "reply",
        "memo",
        "memorandum",
        "order",
        "decision",
        "judgment",
        "stipulation",
        "rji",
        "letter",
        "notice",
        "subpoena",
        "transcript",
    }
)

# Known pleading section families (generic). Matching is case/OCR-tolerant;
# emitted markers remain exact observed surface forms.
# More specific factual/overview labels precede generic ``facts`` / ``background``.
# Bare ``facts`` requires the plural form so allegation lines like ``2. Fact.``
# are not stolen as section headings.
_KNOWN_SECTION_PATTERNS: tuple[tuple[str, str], ...] = (
    ("overview", r"overview"),
    ("introduction", r"introduction"),
    ("preliminary_statement", r"preliminary\s+statement"),
    ("nature_of_the_action", r"nature\s+of\s+(?:the\s+)?action"),
    ("parties", r"(?:the\s+)?parties(?:\s+to\s+(?:this\s+)?(?:action|proceeding|litigation))?"),
    ("intervening_facts", r"intervening\s+facts?"),
    ("statement_of_facts", r"statement\s+of\s+facts?"),
    ("relevant_facts", r"relevant\s+facts?"),
    ("factual_background", r"factual\s+background(?:\s+and\s+general\s+allegations)?"),
    ("general_background", r"general\s+background"),
    ("factual_allegations", r"factual\s+allegations?"),
    ("general_allegations", r"general\s+allegations"),
    ("allegations", r"allegations?"),
    ("facts", r"facts(?:\s+common\s+to\s+all\s+(?:counts|claims))?"),
    ("background", r"background"),
    ("jurisdiction_and_venue", r"jurisdiction\s+and\s+venue"),
    ("jurisdiction", r"jurisdiction"),
    ("venue", r"venue"),
    ("causes_of_action", r"causes?\s+of\s+action"),
    ("wherefore", r"wherefore"),
    ("prayer_for_relief", r"prayer\s+for\s+relief"),
)

# Coarse roadmap kinds used by party-role evidence routing.
_OVERVIEW_MATCH_KEYS = frozenset(
    {
        "overview",
        "introduction",
        "preliminary_statement",
        "nature_of_the_action",
    }
)
_FACTUAL_LAYOUT_MATCH_KEYS = frozenset(
    {
        "intervening_facts",
        "statement_of_facts",
        "relevant_facts",
        "facts",
        "factual_background",
        "general_background",
        "factual_allegations",
        "background",
        "general_allegations",
        "allegations",
    }
)
_PARTIES_MATCH_KEYS = frozenset({"parties"})
_PROCEDURAL_LAYOUT_MATCH_KEYS = frozenset(
    {"jurisdiction_and_venue", "jurisdiction", "venue"}
)
_CLAIMS_MATCH_KEYS = frozenset(
    {"causes_of_action", "wherefore", "prayer_for_relief", "pleaded_count"}
)

# Collapsed alphabetic forms for OCR that destroyed word boundaries
# (``FACTUALBACKGROUND`` after over-joining). Exact match only.
_KNOWN_SECTION_COLLAPSED_LABELS: tuple[tuple[str, str], ...] = tuple(
    (key, re.sub(r"[^a-z]+", "", label.lower()))
    for key, label in (
        ("overview", "overview"),
        ("introduction", "introduction"),
        ("preliminary_statement", "preliminary statement"),
        ("nature_of_the_action", "nature of the action"),
        ("nature_of_the_action", "nature of action"),
        ("parties", "the parties"),
        ("parties", "parties"),
        ("parties", "parties to this action"),
        ("intervening_facts", "intervening facts"),
        ("intervening_facts", "intervening fact"),
        ("statement_of_facts", "statement of facts"),
        ("statement_of_facts", "statement of fact"),
        ("relevant_facts", "relevant facts"),
        ("relevant_facts", "relevant fact"),
        ("factual_background", "factual background"),
        (
            "factual_background",
            "factual background and general allegations",
        ),
        ("general_background", "general background"),
        ("factual_allegations", "factual allegations"),
        ("factual_allegations", "factual allegation"),
        ("general_allegations", "general allegations"),
        ("allegations", "allegations"),
        ("allegations", "allegation"),
        ("facts", "facts common to all counts"),
        ("facts", "facts common to all claims"),
        ("facts", "facts"),
        ("background", "background"),
        ("jurisdiction_and_venue", "jurisdiction and venue"),
        ("jurisdiction", "jurisdiction"),
        ("venue", "venue"),
        ("causes_of_action", "causes of action"),
        ("causes_of_action", "cause of action"),
        ("wherefore", "wherefore"),
        ("prayer_for_relief", "prayer for relief"),
    )
)

PARTY_ROLE_ROADMAP_NOTE = (
    "Complaint structure roadmap is supplemental metadata derived from "
    "source records with page provenance; it is not a substitute for "
    "substantive retrieval hits and must not invent paragraph ranges."
)

# Optional section/article/part or Roman-numeral prefix — not arabic pleading
# paragraph markers like ``10. Overview ...`` / ``2. Fact.``. Those arabic
# forms are handled by ``_NUMBERED_SECTION_HEADING_RE`` with distinctive labels.
_SECTION_PREFIX = (
    r"(?:"
    r"(?:section|article|part)\s+[ivxlcdm\d]+(?:\s*[.:=\-—–]\s*|\s+)|"
    r"(?:[ivxlcdm]+)[.)]?\s+"
    r")?"
)

# Arabic-numeral prefixed major section headings (``14. PARTIES``, ``17. FACTS``).
# Uses distinctive labels only — excludes bare short tokens that commonly open
# ordinary allegation sentences (``Fact``, ``Background``, ``Venue``).
_NUMBERED_SECTION_PATTERNS: tuple[tuple[str, str], ...] = (
    ("overview", r"overview"),
    ("introduction", r"introduction"),
    ("preliminary_statement", r"preliminary\s+statement"),
    ("nature_of_the_action", r"nature\s+of\s+(?:the\s+)?action"),
    ("parties", r"(?:the\s+)?parties(?:\s+to\s+(?:this\s+)?(?:action|proceeding|litigation))?"),
    ("intervening_facts", r"intervening\s+facts?"),
    ("statement_of_facts", r"statement\s+of\s+facts?"),
    ("relevant_facts", r"relevant\s+facts?"),
    ("factual_background", r"factual\s+background(?:\s+and\s+general\s+allegations)?"),
    ("general_background", r"general\s+background"),
    ("factual_allegations", r"factual\s+allegations?"),
    ("general_allegations", r"general\s+allegations"),
    ("allegations", r"allegations?"),
    ("facts", r"facts(?:\s+common\s+to\s+all\s+(?:counts|claims))?"),
    ("jurisdiction_and_venue", r"jurisdiction\s+and\s+venue"),
    ("causes_of_action", r"causes?\s+of\s+action"),
    ("wherefore", r"wherefore"),
    ("prayer_for_relief", r"prayer\s+for\s+relief"),
)

# Optional trailing punctuation / colon noise after a clean heading label.
_HEADING_TRAILING_PUNCT = r"[:.\-—–_•·]?"

_KNOWN_BODY_ALTERNATION = r"|".join(
    f"(?:{pat})" for _, pat in _KNOWN_SECTION_PATTERNS
)
_NUMBERED_BODY_ALTERNATION = r"|".join(
    f"(?:{pat})" for _, pat in _NUMBERED_SECTION_PATTERNS
)

# Line-oriented heading candidate: optional prefix + known name + light punct.
_HEADING_LINE_RE = re.compile(
    r"(?im)^\s*"
    + _SECTION_PREFIX
    + r"(?P<body>"
    + _KNOWN_BODY_ALTERNATION
    + r")"
    + r"\s*"
    + _HEADING_TRAILING_PUNCT
    + r"\s*$"
)

# ``14. PARTIES`` / ``17. FACTS`` — arabic prefix + distinctive section label.
_NUMBERED_SECTION_HEADING_RE = re.compile(
    r"(?im)^\s*(?P<num>\d{1,4})[.)]\s*"
    + r"(?P<body>"
    + _NUMBERED_BODY_ALTERNATION
    + r")"
    + r"\s*"
    + _HEADING_TRAILING_PUNCT
    + r"\s*$"
)

# Paragraph markers at line starts. Tolerates light OCR spacing around the
# delimiter (``1.``, ``1)``, ``1 .``) but requires a following non-space token.
_PARAGRAPH_MARKER_RE = re.compile(
    r"(?m)^[ \t]*(?P<marker>(?P<num>\d{1,4})[ \t]*[.)])[ \t]+\S"
)

# Heading label + same-line allegation marker (``PARTIES 1. Plaintiff...``).
_HEADING_THEN_PARAGRAPH_RE = re.compile(
    r"(?im)^\s*"
    + _SECTION_PREFIX
    + r"(?:"
    + _KNOWN_BODY_ALTERNATION
    + r")\b\s*"
    + _HEADING_TRAILING_PUNCT
    + r"\s*(?P<marker>(?P<num>\d{1,4})[ \t]*[.)])[ \t]+\S"
)

# Numbered section heading with same-line first allegation
# (``14. PARTIES 15. Plaintiff...`` is rare; ``PARTIES 1.`` is the common form).
_NUMBERED_HEADING_THEN_PARAGRAPH_RE = re.compile(
    r"(?im)^\s*(?P<num>\d{1,4})[.)]\s*"
    + r"(?:"
    + _NUMBERED_BODY_ALTERNATION
    + r")\b\s*"
    + _HEADING_TRAILING_PUNCT
    + r"\s*(?P<marker>(?P<pnum>\d{1,4})[ \t]*[.)])[ \t]+\S"
)

# Repeated filing stamp / NYSCEF docket chrome (skipped for heading candidates).
_FILING_CHROME_LINE_RE = re.compile(
    r"(?i)^\s*(?:"
    r"filed:\s*.*|"
    r"nyscef\s+doc(?:ument)?\.?\s*no\.?\s*:?\s*\d+.*|"
    r"index\s+no\.?\s*:?\s*\S+.*|"
    r"received\s+nyscef\s*:?\s*.*|"
    r"doc(?:ument)?\s*#?\s*\d+\s*$|"
    r"page\s+\d+\s*(?:of\s*\d+)?\s*$|"
    r"\d+\s+of\s+\d+\s*$"
    r")"
)

# OCR: spaced-out single letters inside a heading token (``P A R T I E S``).
_OCR_LETTER_SPACED_RE = re.compile(
    r"\b(?:[A-Za-z](?:[ \t]+[A-Za-z]){2,})\b"
)

# Mid-line WHEREFORE / prayer markers on collapsed OCR pages (often after a
# glued page-number chrome prefix such as ``26 WHEREFORE ...``).
_MIDLINE_RELIEF_HEADING_RE = re.compile(
    r"(?i)(?P<body>\bwherefore\b|\bprayer\s+for\s+relief\b)"
)

# Pleaded count headings (``COUNT I``, ``COUNT II``, ``Count 1``). Observed
# ordinal only — never invents a cause-of-action title from mashed OCR.
_COUNT_ORDINAL_TOKEN = r"(?:[IVXLC]{1,8}|\d{1,2})"
_COUNT_HEADING_LINE_RE = re.compile(
    r"(?im)^\s*(?P<body>COUNT\s+(?P<ordinal>"
    + _COUNT_ORDINAL_TOKEN
    + r"))\s*"
    + _HEADING_TRAILING_PUNCT
    + r"\s*$"
)
_MIDLINE_COUNT_HEADING_RE = re.compile(
    r"(?i)(?P<body>\bCOUNT\s+(?P<ordinal>" + _COUNT_ORDINAL_TOKEN + r")\b)"
)
# Same-line verified title tail after COUNT <ordinal> (letters-led; bounded).
_COUNT_TITLE_TAIL_RE = re.compile(
    r"(?i)\bCOUNT\s+(?P<ordinal>"
    + _COUNT_ORDINAL_TOKEN
    + r")\b(?P<title_tail>\s+[A-Za-z][A-Za-z0-9 ,;:'\"/\-]{3,120})?"
)
_PLEADED_COUNT_MATCH_KEY = "pleaded_count"
# Source-grounded substance cues used only to populate coverage phrases.
_COUNT_SUBSTANCE_CUE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\bvoid\s+ab\s+initio\b"), "void ab initio"),
    (re.compile(r"(?i)\brescission\b|\brescind(?:s|ed|ing)?\b"), "rescission"),
    (
        re.compile(
            r"(?i)\bno\s+duty\s+to\s+defend\b|\bno\s+defense\s+or\s+indemnity\b|"
            r"\bneither\s+defense\s+nor\s+indemnity\b|"
            r"\bhave\s+no\s+obligations?\s+to\s+provide\s+defense\b"
        ),
        "no duty to defend",
    ),
    (re.compile(r"(?i)\bindemnif(?:y|ies|ied|ying|ication)\b|\bindemnity\b"), "indemnify"),
    (
        re.compile(r"(?i)\bdeclar(?:e|es|ing|ation)\b|\bdeclarations?\b"),
        "declaration",
    ),
)
_COUNT_SUBSTANCE_STOPWORDS = frozenset(
    {
        "count",
        "the",
        "and",
        "for",
        "that",
        "this",
        "with",
        "from",
        "under",
        "have",
        "has",
        "had",
        "are",
        "was",
        "were",
        "been",
        "being",
        "into",
        "onto",
        "upon",
        "such",
        "other",
        "further",
        "plaintiff",
        "defendant",
        "defendants",
        "complaint",
        "policies",
        "policy",
        "herein",
        "thereof",
        "therein",
    }
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


def controlling_complaint_structure_is_empty(payload: Any) -> bool:
    """
    True when a selected controlling complaint has zero sections and headings.

    Empty unavailable/ambiguous maps (no selected controlling complaint) are not
    treated as silently-empty caches — only a selected document that contributes
    no structure can fail closed at derived-cache validation.
    """
    if not is_current_structure_schema(payload):
        return False
    selection = payload.get("selection")
    if not isinstance(selection, dict):
        return False
    if selection.get("status") != SELECTION_STATUS_SELECTED:
        return False
    documents = [
        doc for doc in (payload.get("documents") or []) if isinstance(doc, dict)
    ]
    if not documents:
        return True
    for doc in documents:
        sections = doc.get("sections") or []
        headings = doc.get("section_headings") or []
        if sections or headings:
            return False
    return True


def _empty_selection(
    *,
    status: str,
    reason: Optional[str] = None,
    controlling: Optional[int] = None,
    candidates: Optional[Sequence[int]] = None,
    excluded: Optional[Sequence[int]] = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "controlling_nyscef_document_number": controlling,
        "candidate_nyscef_document_numbers": [
            int(n) for n in (candidates or [])
        ],
        "excluded_nyscef_document_numbers": [
            int(n) for n in (excluded or [])
        ],
    }


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


def _meta_token(value: Any) -> str:
    if value is None:
        return ""
    return _collapse_ws(str(value)).lower()


def _filing_metadata_from_pages(
    pages: Sequence[Mapping[str, Any]],
) -> dict[str, str]:
    """Collect explicit filing metadata / provenance from a document's pages."""
    meta = {
        "document_type": "",
        "document_title": "",
        "document_classification": "",
        "source_filename": "",
    }
    for page in pages:
        if not isinstance(page, Mapping):
            continue
        for key, dest in (
            ("document_type", "document_type"),
            ("type", "document_type"),
            ("category", "document_type"),
            ("document_title", "document_title"),
            ("title", "document_title"),
            ("document_classification", "document_classification"),
            ("classification", "document_classification"),
            ("source_filename", "source_filename"),
            ("filename", "source_filename"),
        ):
            if meta[dest]:
                continue
            raw = page.get(key)
            if isinstance(raw, str) and raw.strip():
                meta[dest] = raw.strip()
    return meta


def _filing_haystack(meta: Mapping[str, str]) -> str:
    return " ".join(
        _meta_token(meta.get(key))
        for key in (
            "document_type",
            "document_title",
            "document_classification",
            "source_filename",
        )
        if meta.get(key)
    )


def _has_answer_filing_signal(hay: str) -> bool:
    if not hay:
        return False
    if re.search(r"\bamended\s+answers?\b", hay):
        return True
    if re.search(r"\banswers?\s+to\s+(?:the\s+)?(?:complaint|petition)\b", hay):
        return True
    if re.search(r"\b(?:verified\s+)?answers?\b", hay):
        return True
    return False


def _has_excluded_non_complaint_signal(hay: str) -> bool:
    """True for answers, affidavits, motions, exhibits, and similar filings."""
    if not hay:
        return False
    if _has_answer_filing_signal(hay):
        return True
    if re.search(
        r"\b(?:affidavits?|affirmations?|declarations?)\b",
        hay,
    ):
        return True
    if re.search(r"\b(?:notice\s+of\s+)?motions?\b", hay):
        return True
    if re.search(r"\b(?:exhibits?|exh)\b", hay):
        return True
    if re.search(
        r"\b(?:oppositions?|replies|reply|memorand(?:um|a)|memos?)\b",
        hay,
    ):
        return True
    if re.search(r"\b(?:orders?|decisions?|judgments?)\b", hay):
        return True
    if re.search(
        r"\b(?:stipulations?|subpoenas?|transcripts?|letters?)\b",
        hay,
    ):
        return True
    if re.search(r"\brji\b|\brequest\s+for\s+judicial\s+intervention\b", hay):
        return True
    # Explicit typed exclusions from normalized document_type tokens.
    tokens = set(re.findall(r"[a-z0-9_]+", hay))
    if tokens.intersection(_EXCLUDED_FILING_TYPE_TOKENS):
        # Avoid treating bare "notice" inside "summons and complaint" captions
        # as exclusion when complaint signals dominate — handled by caller order.
        if "notice" in tokens and not tokens.intersection(
            _EXCLUDED_FILING_TYPE_TOKENS - {"notice"}
        ):
            if re.search(r"\bnotice\s+of\s+(?:motion|appearance|entry)\b", hay):
                return True
            return False
        return True
    return False


def _has_complaint_filing_signal(hay: str, meta: Mapping[str, str]) -> bool:
    """True when metadata/provenance identifies an initiating complaint filing."""
    doc_type = _meta_token(meta.get("document_type"))
    classification = _meta_token(meta.get("document_classification"))
    if doc_type == "complaint" or classification == "complaint":
        return True
    if classification in {
        "summons_and_complaint",
        "summons___complaint",
        "initiating_complaint",
        "amended_complaint",
    }:
        return True
    if not hay:
        return False
    if re.search(r"\bamended\s+complaints?\b", hay):
        return True
    if re.search(r"\bsummons(?:\s+and|&|\s*/\s*|\s+_+)?\s*complaints?\b", hay):
        return True
    if re.search(r"\bcomplaints?\b", hay):
        return True
    if re.search(r"\bpetitions?\b", hay) and "answer" not in hay:
        return True
    return False


def classify_filing_role_for_structure(
    meta: Mapping[str, Any] | None,
) -> str:
    """
    Classify a filing as ``complaint``, ``excluded``, or ``unknown``.

    Prefers explicit document_type / title / classification metadata and
    source filename provenance. Answers and other response pleadings are
    excluded even when they mention complaint paragraph numbers.
    """
    normalized = {
        "document_type": _meta_token((meta or {}).get("document_type")),
        "document_title": _meta_token((meta or {}).get("document_title")),
        "document_classification": _meta_token(
            (meta or {}).get("document_classification")
        ),
        "source_filename": _meta_token((meta or {}).get("source_filename")),
    }
    # Preserve originals for signal helpers that expect raw-ish strings.
    raw_meta = {
        "document_type": str((meta or {}).get("document_type") or ""),
        "document_title": str((meta or {}).get("document_title") or ""),
        "document_classification": str(
            (meta or {}).get("document_classification") or ""
        ),
        "source_filename": str((meta or {}).get("source_filename") or ""),
    }
    hay = _filing_haystack(raw_meta)
    if not hay.strip():
        return "unknown"
    # Exclusions win over generic "complaint" tokens ("answer to complaint").
    if _has_answer_filing_signal(hay):
        return "excluded"
    if _has_excluded_non_complaint_signal(hay):
        # Summons/complaint filings can include "notice" boilerplate in titles;
        # only exclude when complaint signals are absent.
        if _has_complaint_filing_signal(hay, raw_meta) and not re.search(
            r"\b(?:answers?|affidavits?|affirmations?|motions?|exhibits?)\b",
            hay,
        ):
            return "complaint"
        return "excluded"
    if _has_complaint_filing_signal(hay, raw_meta):
        return "complaint"
    if normalized["document_type"] in _EXCLUDED_FILING_TYPE_TOKENS:
        return "excluded"
    return "unknown"


def select_controlling_complaint(
    page_records: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    *,
    filing_inventory: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Select the controlling complaint using filing metadata / provenance.

    Returns a selection object. Never merges multiple filings. When more than
    one complaint candidate exists, status is ``ambiguous``. When none can be
    identified, status is ``unavailable``.
    """
    pages = _iter_page_records(page_records)
    by_doc: dict[int, list[dict[str, Any]]] = {}
    for page in pages:
        nyscef = page.get("nyscef_document_number")
        if nyscef is None:
            continue
        by_doc.setdefault(int(nyscef), []).append(page)

    inventory_meta_by_nyscef: dict[int, dict[str, str]] = {}
    filings: Sequence[Any]
    if isinstance(filing_inventory, Mapping):
        filings = filing_inventory.get("filings") or []
    elif isinstance(filing_inventory, Sequence) and not isinstance(
        filing_inventory, (str, bytes)
    ):
        filings = filing_inventory
    else:
        filings = []
    for filing in filings:
        if not isinstance(filing, Mapping):
            continue
        try:
            nyscef = int(filing.get("nyscef_document_number"))
        except (TypeError, ValueError):
            continue
        inventory_meta_by_nyscef[nyscef] = {
            "document_type": str(
                filing.get("document_type")
                or filing.get("type")
                or filing.get("category")
                or ""
            ),
            "document_title": str(
                filing.get("document_title")
                or filing.get("title")
                or filing.get("filename")
                or ""
            ),
            "document_classification": str(
                filing.get("document_classification")
                or filing.get("classification")
                or ""
            ),
            "source_filename": str(filing.get("filename") or ""),
        }

    if not by_doc:
        return _empty_selection(
            status=SELECTION_STATUS_UNAVAILABLE,
            reason="no_page_records",
        )

    candidates: list[int] = []
    excluded: list[int] = []
    unknown: list[int] = []
    for nyscef in sorted(by_doc.keys()):
        meta = _filing_metadata_from_pages(by_doc[nyscef])
        inv = inventory_meta_by_nyscef.get(nyscef) or {}
        for key, value in inv.items():
            if value and not meta.get(key):
                meta[key] = value
        role = classify_filing_role_for_structure(meta)
        if role == "complaint":
            candidates.append(nyscef)
        elif role == "excluded":
            excluded.append(nyscef)
        else:
            unknown.append(nyscef)

    if len(candidates) == 1:
        return _empty_selection(
            status=SELECTION_STATUS_SELECTED,
            reason=None,
            controlling=candidates[0],
            candidates=candidates,
            excluded=excluded,
        )
    if len(candidates) > 1:
        return _empty_selection(
            status=SELECTION_STATUS_AMBIGUOUS,
            reason="multiple_complaint_candidates",
            candidates=candidates,
            excluded=excluded,
        )
    if excluded and not unknown:
        return _empty_selection(
            status=SELECTION_STATUS_UNAVAILABLE,
            reason="complaint_metadata_absent_answer_or_motion_only_corpus",
            excluded=excluded,
        )
    if unknown and not excluded:
        return _empty_selection(
            status=SELECTION_STATUS_UNAVAILABLE,
            reason="complaint_metadata_absent",
            excluded=excluded,
        )
    return _empty_selection(
        status=SELECTION_STATUS_UNAVAILABLE,
        reason="controlling_complaint_unavailable",
        excluded=excluded,
    )


def _heal_ocr_letter_spacing(text: str) -> str:
    """Join spaced-out letter runs for matching only; does not alter markers.

    Wider gaps between OCR-spaced words are preserved as word boundaries
    (``F A C T U A L   B A C K G R O U N D`` → ``FACTUAL BACKGROUND``).
    """

    def _join(match: re.Match[str]) -> str:
        chunk = match.group(0)
        # Two or more whitespace characters mark an OCR word boundary.
        pieces = re.split(r"[ \t]{2,}", chunk)
        healed = [re.sub(r"[ \t]+", "", piece) for piece in pieces if piece]
        return " ".join(healed)

    return _OCR_LETTER_SPACED_RE.sub(_join, text or "")


def _normalize_heading_match_text(text: str) -> str:
    healed = _heal_ocr_letter_spacing(text)
    healed = re.sub(r"\s+", " ", healed).strip().lower()
    healed = healed.rstrip(" :.-—–_•·").strip()
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
    # OCR may have destroyed word boundaries entirely.
    collapsed = re.sub(r"[^a-z]+", "", normalized)
    if collapsed:
        for key, label in _KNOWN_SECTION_COLLAPSED_LABELS:
            if collapsed == label:
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


def _is_filing_chrome_line(line: str) -> bool:
    """True for repeated filing stamps / NYSCEF headers / page footers."""
    collapsed = _collapse_ws(line)
    if not collapsed:
        return False
    return bool(_FILING_CHROME_LINE_RE.match(collapsed))


def _bounded_observed_heading_marker(
    original_line: str,
    *,
    healed_match_end: int,
    body: str,
    label_span: str,
) -> str:
    """Preserve exact source marker text without absorbing trailing prose."""
    bounded = _collapse_ws(original_line[:healed_match_end])
    if not bounded:
        bounded = _collapse_ws(label_span)
    bounded = bounded.rstrip(" :.-—–_•·").strip()
    if not bounded:
        bounded = _collapse_ws(body)
    return bounded


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
        # Skip docket chrome so repeated headers/footers never become headings.
        if _is_filing_chrome_line(original_lines[idx]) or _is_filing_chrome_line(
            healed_line
        ):
            continue

        match = _HEADING_LINE_RE.match(healed_line)
        if not match:
            match = _NUMBERED_SECTION_HEADING_RE.match(healed_line)
        count_line = _COUNT_HEADING_LINE_RE.match(healed_line)
        if match or count_line:
            if count_line:
                key = _PLEADED_COUNT_MATCH_KEY
                # Bound marker to ``COUNT <ordinal>`` only — never absorb title OCR.
                start, end = count_line.start("body"), count_line.end("body")
                if 0 <= start < end <= len(original_lines[idx]):
                    observed = _collapse_ws(original_lines[idx][start:end])
                else:
                    observed = _collapse_ws(count_line.group("body"))
            else:
                body = match.group("body")
                key = _match_key_for_heading_body(body)
                observed = _collapse_ws(original_lines[idx]).rstrip(" :.-—–_•·").strip()
            ocr_healed = _heal_ocr_letter_spacing(original_lines[idx])
            ambiguous = False
            ambiguity_note = None
            if _collapse_ws(ocr_healed) != _collapse_ws(original_lines[idx]) and key is not None:
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

        # Numbered allegation lines are paragraph observations, not headings —
        # except mid-line COUNT / WHEREFORE markers mashed into allegation prose.
        is_paragraph_line = bool(_PARAGRAPH_MARKER_RE.match(healed_line))
        if is_paragraph_line:
            emitted_midline = False
            for count_match in _MIDLINE_COUNT_HEADING_RE.finditer(healed_line):
                body = count_match.group("body")
                original_line = original_lines[idx]
                start, end = count_match.start("body"), count_match.end("body")
                if 0 <= start < end <= len(original_line):
                    bounded = _collapse_ws(original_line[start:end])
                else:
                    bounded = _collapse_ws(body)
                if not bounded:
                    bounded = _collapse_ws(body)
                headings.append(
                    {
                        "ambiguous": True,
                        "ambiguity_note": (
                            "mid_line_count_heading_after_paragraph_marker"
                        ),
                        "match_key": _PLEADED_COUNT_MATCH_KEY,
                        "observed_marker": bounded,
                        "page_id": prov["page_id"],
                        "page_number": prov["page_number"],
                        "line_index": idx,
                    }
                )
                uncertainties.append(
                    {
                        "kind": "ambiguous_heading",
                        "observed_marker": bounded,
                        "page_id": prov["page_id"],
                        "page_number": prov["page_number"],
                        "detail": "mid_line_count_heading_after_paragraph_marker",
                    }
                )
                emitted_midline = True
                break
            if not emitted_midline:
                for relief_match in _MIDLINE_RELIEF_HEADING_RE.finditer(healed_line):
                    body = relief_match.group("body")
                    key = _match_key_for_heading_body(body)
                    if key not in {"wherefore", "prayer_for_relief"}:
                        continue
                    original_line = original_lines[idx]
                    start, end = relief_match.start("body"), relief_match.end("body")
                    if 0 <= start < end <= len(original_line):
                        bounded = _collapse_ws(original_line[start:end])
                    else:
                        bounded = _collapse_ws(body)
                    if not bounded:
                        bounded = _collapse_ws(body)
                    headings.append(
                        {
                            "ambiguous": True,
                            "ambiguity_note": (
                                "mid_line_relief_heading_after_paragraph_marker"
                            ),
                            "match_key": key,
                            "observed_marker": bounded,
                            "page_id": prov["page_id"],
                            "page_number": prov["page_number"],
                            "line_index": idx,
                        }
                    )
                    uncertainties.append(
                        {
                            "kind": "ambiguous_heading",
                            "observed_marker": bounded,
                            "page_id": prov["page_id"],
                            "page_number": prov["page_number"],
                            "detail": (
                                "mid_line_relief_heading_after_paragraph_marker"
                            ),
                        }
                    )
                    break
            continue

        # Ambiguous: line looks like a known heading family but has trailing
        # prose (not a clean heading line), including same-line paragraphs.
        stripped = healed_line.strip()
        if not stripped:
            continue
        body_guess = _ambiguous_heading_re.match(stripped)
        if body_guess:
            rest = stripped[body_guess.end() :].strip()
            rest = rest.lstrip(" :.-—–_•·").strip()
            if rest:
                key = _match_key_for_heading_body(body_guess.group("body"))
                # Bound the observed marker to the heading label only — never
                # absorb trailing page prose or responsive allegation language.
                original_line = original_lines[idx]
                label_span = body_guess.group(0)
                bounded = _bounded_observed_heading_marker(
                    original_line,
                    healed_match_end=body_guess.end(),
                    body=body_guess.group("body"),
                    label_span=label_span,
                )
                ambiguity_note = "heading_token_with_trailing_prose"
                if _HEADING_THEN_PARAGRAPH_RE.match(
                    healed_line
                ) or _NUMBERED_HEADING_THEN_PARAGRAPH_RE.match(healed_line):
                    ambiguity_note = "heading_adjacent_to_paragraph_text"
                headings.append(
                    {
                        "ambiguous": True,
                        "ambiguity_note": ambiguity_note,
                        "match_key": key,
                        "observed_marker": bounded,
                        "page_id": prov["page_id"],
                        "page_number": prov["page_number"],
                        "line_index": idx,
                    }
                )
                uncertainties.append(
                    {
                        "kind": "ambiguous_heading",
                        "observed_marker": bounded,
                        "page_id": prov["page_id"],
                        "page_number": prov["page_number"],
                        "detail": ambiguity_note,
                    }
                )
                continue

        # Collapsed OCR pages often glue page-number chrome onto WHEREFORE /
        # prayer text (``26 WHEREFORE ...``), defeating line-start anchors.
        # Emit a bounded mid-line relief heading so structure-backed routing
        # still receives page provenance without inventing private prose.
        # Also emit mid-line COUNT headings (``...at law. COUNT II ...``).
        emitted_midline = False
        for relief_match in _MIDLINE_RELIEF_HEADING_RE.finditer(healed_line):
            body = relief_match.group("body")
            key = _match_key_for_heading_body(body)
            if key not in {"wherefore", "prayer_for_relief"}:
                continue
            original_line = original_lines[idx]
            # Prefer the exact original span when lengths align; otherwise keep
            # the healed relief token as the observed marker.
            start, end = relief_match.start("body"), relief_match.end("body")
            if 0 <= start < end <= len(original_line):
                bounded = _collapse_ws(original_line[start:end])
            else:
                bounded = _collapse_ws(body)
            if not bounded:
                bounded = _collapse_ws(body)
            ambiguity_note = "mid_line_relief_heading_on_collapsed_page"
            headings.append(
                {
                    "ambiguous": True,
                    "ambiguity_note": ambiguity_note,
                    "match_key": key,
                    "observed_marker": bounded,
                    "page_id": prov["page_id"],
                    "page_number": prov["page_number"],
                    "line_index": idx,
                }
            )
            uncertainties.append(
                {
                    "kind": "ambiguous_heading",
                    "observed_marker": bounded,
                    "page_id": prov["page_id"],
                    "page_number": prov["page_number"],
                    "detail": ambiguity_note,
                }
            )
            emitted_midline = True
            # One relief heading per collapsed line is enough for page routing.
            break

        for count_match in _MIDLINE_COUNT_HEADING_RE.finditer(healed_line):
            body = count_match.group("body")
            original_line = original_lines[idx]
            start, end = count_match.start("body"), count_match.end("body")
            if 0 <= start < end <= len(original_line):
                bounded = _collapse_ws(original_line[start:end])
            else:
                bounded = _collapse_ws(body)
            if not bounded:
                bounded = _collapse_ws(body)
            ambiguity_note = "mid_line_count_heading_on_collapsed_page"
            headings.append(
                {
                    "ambiguous": True,
                    "ambiguity_note": ambiguity_note,
                    "match_key": _PLEADED_COUNT_MATCH_KEY,
                    "observed_marker": bounded,
                    "page_id": prov["page_id"],
                    "page_number": prov["page_number"],
                    "line_index": idx,
                }
            )
            uncertainties.append(
                {
                    "kind": "ambiguous_heading",
                    "observed_marker": bounded,
                    "page_id": prov["page_id"],
                    "page_number": prov["page_number"],
                    "detail": ambiguity_note,
                }
            )
            emitted_midline = True
            break

        if emitted_midline:
            continue

    return headings, uncertainties


def _append_paragraph_observation(
    found: list[dict[str, Any]],
    seen_on_page: set[int],
    *,
    number: int,
    marker: str,
    prov: Mapping[str, Any],
    line_index: int,
) -> None:
    if number in seen_on_page:
        return
    seen_on_page.add(number)
    cleaned = re.sub(r"\s+", "", _collapse_ws(marker))
    found.append(
        {
            "number": number,
            "observed_marker": cleaned,
            "page_id": prov["page_id"],
            "page_number": prov["page_number"],
            "line_index": line_index,
        }
    )


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
        if _is_filing_chrome_line(line):
            continue
        # Skip numbered section-heading lines (``14. PARTIES``) — those are
        # headings, not allegation paragraph markers.
        healed_line = _heal_ocr_letter_spacing(line)
        if _HEADING_LINE_RE.match(healed_line) or _NUMBERED_SECTION_HEADING_RE.match(
            healed_line
        ):
            continue
        try:
            number = int(match.group("num"))
        except (TypeError, ValueError):
            continue
        line_index = text.count("\n", 0, line_start)
        _append_paragraph_observation(
            found,
            seen_on_page,
            number=number,
            marker=match.group("marker"),
            prov=prov,
            line_index=line_index,
        )

    # Same-line heading + allegation (``PARTIES 1. Plaintiff...``).
    original_lines = text.splitlines()
    for line_index, line in enumerate(original_lines):
        if _is_filing_chrome_line(line):
            continue
        healed = _heal_ocr_letter_spacing(line)
        adjacent = _HEADING_THEN_PARAGRAPH_RE.match(healed)
        numbered_adjacent = None
        if not adjacent:
            numbered_adjacent = _NUMBERED_HEADING_THEN_PARAGRAPH_RE.match(healed)
        if not adjacent and not numbered_adjacent:
            continue
        if numbered_adjacent is not None:
            try:
                number = int(numbered_adjacent.group("pnum"))
            except (TypeError, ValueError):
                continue
            marker = numbered_adjacent.group("marker")
        else:
            assert adjacent is not None
            try:
                number = int(adjacent.group("num"))
            except (TypeError, ValueError):
                continue
            marker = adjacent.group("marker")
        _append_paragraph_observation(
            found,
            seen_on_page,
            number=number,
            marker=marker,
            prov=prov,
            line_index=line_index,
        )
    return found


def section_kind_for_match_key(match_key: Optional[str]) -> str:
    """Map a normalized heading match_key to a coarse roadmap kind."""
    key = (match_key or "").strip().lower()
    if key in _PARTIES_MATCH_KEYS:
        return "parties"
    if key in _OVERVIEW_MATCH_KEYS:
        return "overview"
    if key in _FACTUAL_LAYOUT_MATCH_KEYS:
        return "factual_layout"
    if key in _PROCEDURAL_LAYOUT_MATCH_KEYS:
        return "procedural_layout"
    if key in _CLAIMS_MATCH_KEYS:
        return "claims"
    return "other"


def _paragraph_range_from_observed_numbers(
    numbers: Sequence[int],
) -> tuple[Optional[dict[str, Any]], list[str]]:
    """
    Build a contiguous range only when endpoints and full sequence are observed.

    Never invents missing paragraph numbers.
    """
    ordered: list[int] = []
    seen: set[int] = set()
    for raw in numbers or []:
        try:
            num = int(raw)
        except (TypeError, ValueError):
            continue
        if num in seen:
            continue
        seen.add(num)
        ordered.append(num)
    ordered.sort()
    if not ordered:
        return None, ["no_paragraph_markers"]
    for idx in range(len(ordered) - 1):
        if ordered[idx + 1] != ordered[idx] + 1:
            return None, ["noncontiguous_paragraph_numbers"]
    return (
        {
            "start": int(ordered[0]),
            "end": int(ordered[-1]),
            "contiguous": True,
        },
        [],
    )


def _empty_structure_section(
    heading: Mapping[str, Any],
    *,
    document_id: str,
    nyscef: int,
) -> dict[str, Any]:
    observed = str(heading.get("observed_marker") or "")
    page_id = heading.get("page_id")
    page_ids = [str(page_id)] if page_id else []
    page_numbers: list[int] = []
    try:
        page_numbers.append(int(heading["page_number"]))
    except (KeyError, TypeError, ValueError):
        pass
    match_key = heading.get("match_key")
    return {
        "heading": observed,
        "heading_normalized": _collapse_ws(observed).lower().rstrip(":").strip(),
        "match_key": match_key,
        "kind": section_kind_for_match_key(
            str(match_key) if isinstance(match_key, str) else None
        ),
        "ambiguous": bool(heading.get("ambiguous")),
        "page_ids": page_ids,
        "page_numbers": page_numbers,
        "paragraph_numbers": [],
        "paragraph_range": None,
        "uncertainty": [],
        "provenance": {
            "page_ids": list(page_ids),
            "heading_marker": observed,
            "document_id": document_id,
            "nyscef_document_number": nyscef,
        },
    }


def _finalize_structure_section(section: dict[str, Any]) -> dict[str, Any]:
    nums = list(section.get("paragraph_numbers") or [])
    paragraph_range, uncertainty = _paragraph_range_from_observed_numbers(nums)
    section["paragraph_range"] = paragraph_range
    existing = list(section.get("uncertainty") or [])
    for flag in uncertainty:
        if flag not in existing:
            existing.append(flag)
    if not nums and section.get("heading"):
        if "range_not_inferred_from_heading_alone" not in existing:
            existing.append("range_not_inferred_from_heading_alone")
    if section.get("ambiguous"):
        if "ambiguous_heading" not in existing:
            existing.append("ambiguous_heading")
    section["uncertainty"] = existing
    return section


def _build_document_sections(
    *,
    headings: Sequence[Mapping[str, Any]],
    paragraphs: Sequence[Mapping[str, Any]],
    document_id: str,
    nyscef: int,
) -> list[dict[str, Any]]:
    """Bind observed paragraphs to preceding headings by page/line order."""
    events: list[tuple[str, int, int, Mapping[str, Any]]] = []
    for heading in headings:
        try:
            page_no = int(heading.get("page_number") or 0)
            line_idx = int(heading.get("line_index") or 0)
        except (TypeError, ValueError):
            continue
        events.append(("heading", page_no, line_idx, heading))
    for para in paragraphs:
        try:
            page_no = int(para.get("page_number") or 0)
            line_idx = int(para.get("line_index") or 0)
        except (TypeError, ValueError):
            continue
        events.append(("paragraph", page_no, line_idx, para))
    events.sort(key=lambda item: (item[1], item[2], 0 if item[0] == "heading" else 1))

    sections: list[dict[str, Any]] = []
    current: Optional[dict[str, Any]] = None

    def _close() -> None:
        nonlocal current
        if current is None:
            return
        sections.append(_finalize_structure_section(current))
        current = None

    for kind, _page, _line, payload in events:
        if kind == "heading":
            _close()
            current = _empty_structure_section(
                payload, document_id=document_id, nyscef=nyscef
            )
            continue
        # paragraph
        if current is None:
            current = _empty_structure_section(
                {
                    "observed_marker": "",
                    "match_key": None,
                    "page_id": payload.get("page_id"),
                    "page_number": payload.get("page_number"),
                    "ambiguous": False,
                },
                document_id=document_id,
                nyscef=nyscef,
            )
            current["kind"] = "unknown"
            current["uncertainty"] = ["paragraphs_before_section_heading"]
        try:
            num = int(payload["number"])
        except (KeyError, TypeError, ValueError):
            continue
        if num not in current["paragraph_numbers"]:
            current["paragraph_numbers"].append(num)
        page_id = payload.get("page_id")
        if page_id and str(page_id) not in current["page_ids"]:
            current["page_ids"].append(str(page_id))
            current["provenance"]["page_ids"].append(str(page_id))
        try:
            page_no = int(payload["page_number"])
        except (KeyError, TypeError, ValueError):
            page_no = None
        if page_no is not None and page_no not in current["page_numbers"]:
            current["page_numbers"].append(page_no)

    _close()
    return sections


def _compact_structure_section_for_roadmap(
    section: Mapping[str, Any],
) -> Optional[dict[str, Any]]:
    """Strip internal fields; keep citation-ready roadmap metadata only."""
    if not isinstance(section, dict):
        return None
    heading = section.get("heading")
    if not isinstance(heading, str):
        heading = str(heading or "")
    compact = {
        "heading": heading,
        "heading_normalized": section.get("heading_normalized")
        or _collapse_ws(heading).lower().rstrip(":").strip(),
        "match_key": section.get("match_key"),
        "kind": section.get("kind") or "unknown",
        "page_ids": list(section.get("page_ids") or []),
        "page_numbers": list(section.get("page_numbers") or []),
        "paragraph_numbers": list(section.get("paragraph_numbers") or []),
        "paragraph_range": section.get("paragraph_range"),
        "uncertainty": list(section.get("uncertainty") or []),
        "provenance": {
            "page_ids": list(
                (section.get("provenance") or {}).get("page_ids")
                or section.get("page_ids")
                or []
            ),
            "heading_marker": (section.get("provenance") or {}).get("heading_marker")
            or heading,
            "document_id": (section.get("provenance") or {}).get("document_id"),
            "nyscef_document_number": (section.get("provenance") or {}).get(
                "nyscef_document_number"
            ),
        },
    }
    return compact


def sections_from_document_structure(
    document: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """
    Return section records for a DocumentStructure.

    Prefers stored ``sections``. When absent (older caches), degrades to
    heading-only sections without inventing paragraph ranges.
    """
    if not isinstance(document, Mapping):
        return []
    stored = document.get("sections")
    if isinstance(stored, list) and stored:
        return [sec for sec in stored if isinstance(sec, dict)]

    # Explicit degradation: headings only — never invent paragraph bindings.
    document_id = str(document.get("document_id") or "")
    try:
        nyscef = int(document.get("nyscef_document_number"))
    except (TypeError, ValueError):
        nyscef = 0
    sections: list[dict[str, Any]] = []
    for heading in document.get("section_headings") or []:
        if not isinstance(heading, dict):
            continue
        section = _empty_structure_section(
            heading, document_id=document_id, nyscef=nyscef
        )
        section["uncertainty"] = [
            "section_paragraphs_unbound_in_structure_map",
            "range_not_inferred_from_heading_alone",
        ]
        if heading.get("ambiguous"):
            section["uncertainty"].append("ambiguous_heading")
        sections.append(section)
    return sections


# WHEREFORE / prayer-for-relief match keys used by complaint-relief routing.
_RELIEF_MATCH_KEYS = frozenset({"wherefore", "prayer_for_relief"})
# Relief structure context also surfaces pleaded-count / causes-of-action
# sections so completeness validation can enumerate source-identified counts.
_RELIEF_EVIDENCE_MATCH_KEYS = frozenset(
    {"wherefore", "prayer_for_relief", "causes_of_action", "pleaded_count"}
)

COMPLAINT_RELIEF_STRUCTURE_NOTE = (
    "Complaint relief structure metadata identifies observed WHEREFORE / "
    "prayer-for-relief sections with page provenance; it is not a substitute "
    "for substantive retrieval hits and must not invent paragraph ranges or "
    "private pleading text."
)


def _iter_structure_documents(
    structure_map: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
    *,
    require_current_schema: bool = True,
) -> list[Mapping[str, Any]]:
    """Normalize a structure map or document list into document structures."""
    documents_in: list[Mapping[str, Any]] = []
    if isinstance(structure_map, Mapping):
        if require_current_schema and not is_current_structure_schema(structure_map):
            return []
        selection = structure_map.get("selection")
        if isinstance(selection, dict):
            sel_status = selection.get("status")
            if sel_status in {
                SELECTION_STATUS_AMBIGUOUS,
                SELECTION_STATUS_UNAVAILABLE,
            }:
                return []
        documents_in = [
            doc for doc in (structure_map.get("documents") or []) if isinstance(doc, dict)
        ]
    elif isinstance(structure_map, Sequence) and not isinstance(
        structure_map, (str, bytes)
    ):
        for item in structure_map:
            if isinstance(item, dict):
                documents_in.append(item)
    return documents_in


def collect_complaint_relief_page_ids(
    structure_map: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
) -> list[str]:
    """
    Return ordered unique page_ids for observed WHEREFORE / prayer sections.

    Uses structural match_key / kind labels only. Does not invent pages.
    Preceding pleaded-count pages are attached by relief routing lookback
    (drafting_engine), not by broadening this WHEREFORE page set.
    """
    ordered: list[str] = []
    seen: set[str] = set()
    for smap in _iter_structure_documents(structure_map):
        for sec in sections_from_document_structure(smap):
            match_key = str(sec.get("match_key") or "").strip().lower()
            if match_key not in _RELIEF_MATCH_KEYS:
                continue
            for page_id in sec.get("page_ids") or []:
                pid = str(page_id or "").strip()
                if not pid or pid in seen:
                    continue
                seen.add(pid)
                ordered.append(pid)
    return ordered


def _clean_verified_count_title(title_tail: str) -> Optional[str]:
    """Return a bounded same-line title when it is source-readable; else None."""
    title = _collapse_ws(title_tail or "").strip(" :.-—–_•·")
    if len(title) < 4 or len(title) > 120:
        return None
    # Reject mashed OCR (many single-letter tokens / extreme spacing).
    tokens = [t for t in re.split(r"\s+", title) if t]
    if not tokens:
        return None
    short = sum(1 for t in tokens if len(re.sub(r"[^A-Za-z0-9]", "", t)) <= 1)
    if short >= max(2, len(tokens) // 2):
        return None
    if not re.search(r"[A-Za-z]{3,}", title):
        return None
    return title


def _bounded_substantive_excerpt_after_count(text: str, start_at: int) -> Optional[str]:
    """Bounded allegation excerpt after a COUNT marker (no invented prose)."""
    if not text or start_at < 0 or start_at >= len(text):
        return None
    tail = text[start_at:]
    # Skip residual heading punctuation / whitespace.
    tail = re.sub(r"^[\s:.\-—–_•·]+", "", tail)
    # Drop a same-line title already captured; prefer following allegation prose.
    lines = [ln.strip() for ln in tail.splitlines() if ln.strip()]
    chunks: list[str] = []
    for ln in lines[:4]:
        # Skip pure COUNT restatement lines.
        if _COUNT_HEADING_LINE_RE.match(ln):
            continue
        # Strip leading paragraph numbers (``180.`` / ``186.``).
        ln = re.sub(r"^\d{1,4}\.\s*", "", ln)
        ln = _collapse_ws(ln)
        if len(ln) < 12:
            continue
        chunks.append(ln)
        joined = _collapse_ws(" ".join(chunks))
        if len(joined) >= 40:
            break
    if not chunks:
        return None
    excerpt = _collapse_ws(" ".join(chunks))
    if len(excerpt) > 240:
        excerpt = excerpt[:240].rsplit(" ", 1)[0].strip()
    if len(excerpt) < 12:
        return None
    return excerpt


def _substance_phrases_from_count_fields(
    *,
    title: Optional[str],
    substantive_excerpt: Optional[str],
) -> list[str]:
    """Derive coverage phrases from verified title/excerpt only."""
    phrases: list[str] = []
    seen: set[str] = set()

    def _add(phrase: str) -> None:
        cleaned = _collapse_ws(phrase or "")
        key = cleaned.lower()
        if len(cleaned) < 4 or key in seen:
            return
        seen.add(key)
        phrases.append(cleaned)

    if title:
        _add(title)
        for token in re.findall(r"[A-Za-z][A-Za-z\-]{3,}", title):
            if token.lower() not in _COUNT_SUBSTANCE_STOPWORDS:
                _add(token)
    corpus = _collapse_ws(f"{title or ''} {substantive_excerpt or ''}")
    for pattern, canonical in _COUNT_SUBSTANCE_CUE_PATTERNS:
        if pattern.search(corpus):
            _add(canonical)
    if substantive_excerpt and not phrases:
        # Fail-closed fallback: retain a short verbatim span when cues absent.
        span = substantive_excerpt[:80].rsplit(" ", 1)[0].strip()
        _add(span)
    return phrases


def _enrich_pleaded_count_row_from_text(
    row: dict[str, Any],
    text: str,
) -> dict[str, Any]:
    """Preserve verified title or bounded excerpt + phrases from page text."""
    if not text:
        return row
    ordinal = str(row.get("ordinal") or "").strip().upper()
    if not ordinal:
        return row
    title = row.get("title")
    excerpt = row.get("substantive_excerpt")
    for m in _COUNT_TITLE_TAIL_RE.finditer(text):
        if str(m.group("ordinal") or "").strip().upper() != ordinal:
            continue
        if not title:
            title = _clean_verified_count_title(m.group("title_tail") or "")
        if not excerpt:
            excerpt = _bounded_substantive_excerpt_after_count(text, m.end())
        break
    phrases = list(row.get("substance_phrases") or [])
    if not phrases:
        phrases = _substance_phrases_from_count_fields(
            title=title if isinstance(title, str) else None,
            substantive_excerpt=excerpt if isinstance(excerpt, str) else None,
        )
    out = dict(row)
    out["title"] = title if title else None
    out["substantive_excerpt"] = excerpt if excerpt else None
    out["substance_phrases"] = phrases
    return out


def enumerate_source_identified_pleaded_counts(
    structure_map: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
    *,
    page_texts: Optional[Sequence[Mapping[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """
    Enumerate source-grounded pleaded counts separately from prayer for relief.

    Emits one row per distinct observed ``COUNT <ordinal>`` marker with page
    provenance. Preserves a verified same-line heading title when readable, or a
    bounded substantive excerpt from the count page — never invents titles from
    mashed OCR. Deterministic order follows first-seen ordinal appearance.
    """
    rows: list[dict[str, Any]] = []
    seen_ordinals: set[str] = set()
    page_text_by_id: dict[str, str] = {}
    for entry in page_texts or []:
        if not isinstance(entry, Mapping):
            continue
        pid = str(entry.get("page_id") or "").strip()
        text = str(entry.get("text") or entry.get("page_text") or "")
        if pid and text and pid not in page_text_by_id:
            page_text_by_id[pid] = text

    def _take(
        *,
        ordinal: str,
        observed_marker: str,
        page_id: Any,
        page_number: Any,
        title: Any = None,
        substantive_excerpt: Any = None,
        substance_phrases: Optional[Sequence[str]] = None,
    ) -> None:
        ord_key = str(ordinal or "").strip().upper()
        if not ord_key or ord_key in seen_ordinals:
            return
        marker = _collapse_ws(observed_marker or "") or f"COUNT {ord_key}"
        # Canonical display label preserves Roman/arabic ordinal from source.
        label = f"Count {ord_key}"
        row = {
            "ordinal": ord_key,
            "label": label,
            "observed_marker": marker,
            "title": _collapse_ws(title) if title else None,
            "substantive_excerpt": (
                _collapse_ws(substantive_excerpt) if substantive_excerpt else None
            ),
            "substance_phrases": [
                _collapse_ws(p)
                for p in (substance_phrases or [])
                if _collapse_ws(p)
            ],
            "page_id": str(page_id).strip() if page_id else None,
            "page_number": page_number,
            "match_key": _PLEADED_COUNT_MATCH_KEY,
        }
        pid = row["page_id"]
        if pid and pid in page_text_by_id:
            row = _enrich_pleaded_count_row_from_text(row, page_text_by_id[pid])
        rows.append(row)
        seen_ordinals.add(ord_key)

    for smap in _iter_structure_documents(structure_map, require_current_schema=False):
        for heading in smap.get("section_headings") or []:
            if not isinstance(heading, dict):
                continue
            if (
                str(heading.get("match_key") or "").strip().lower()
                != _PLEADED_COUNT_MATCH_KEY
            ):
                continue
            marker = str(heading.get("observed_marker") or "")
            m = _MIDLINE_COUNT_HEADING_RE.search(marker) or _COUNT_HEADING_LINE_RE.match(
                marker
            )
            if not m:
                continue
            _take(
                ordinal=m.group("ordinal"),
                observed_marker=marker,
                page_id=heading.get("page_id"),
                page_number=heading.get("page_number"),
            )
        for sec in sections_from_document_structure(smap):
            if (
                str(sec.get("match_key") or "").strip().lower()
                != _PLEADED_COUNT_MATCH_KEY
            ):
                continue
            marker = str(sec.get("heading") or sec.get("heading_normalized") or "")
            m = _MIDLINE_COUNT_HEADING_RE.search(marker)
            if not m:
                continue
            page_ids = list(sec.get("page_ids") or [])
            page_numbers = list(sec.get("page_numbers") or [])
            _take(
                ordinal=m.group("ordinal"),
                observed_marker=marker,
                page_id=page_ids[0] if page_ids else None,
                page_number=page_numbers[0] if page_numbers else None,
            )

    for entry in page_texts or []:
        if not isinstance(entry, Mapping):
            continue
        text = str(entry.get("text") or entry.get("page_text") or "")
        if not text:
            continue
        for m in _COUNT_TITLE_TAIL_RE.finditer(text):
            title = _clean_verified_count_title(m.group("title_tail") or "")
            excerpt = _bounded_substantive_excerpt_after_count(text, m.end())
            phrases = _substance_phrases_from_count_fields(
                title=title, substantive_excerpt=excerpt
            )
            _take(
                ordinal=m.group("ordinal"),
                observed_marker=f"COUNT {str(m.group('ordinal') or '').strip()}",
                page_id=entry.get("page_id"),
                page_number=entry.get("page_number") or entry.get("pdf_page"),
                title=title,
                substantive_excerpt=excerpt,
                substance_phrases=phrases,
            )

    return rows


def select_complaint_relief_structure_context(
    structure_map: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
) -> Optional[dict[str, Any]]:
    """
    Build compact, source-cited WHEREFORE / prayer / pleaded-count metadata.

    Emits observed relief-section and pleaded-count records with page provenance.
    Supplemental routing signal for complaint-relief questions — never invents
    ranges or pleading prose. Returns None when schema is stale/absent,
    controlling-complaint selection failed, or no relief/count sections exist.
    """
    documents_out: list[dict[str, Any]] = []
    for smap in _iter_structure_documents(structure_map):
        selected: list[dict[str, Any]] = []
        for sec in sections_from_document_structure(smap):
            match_key = str(sec.get("match_key") or "").strip().lower()
            if match_key not in _RELIEF_EVIDENCE_MATCH_KEYS:
                continue
            compact = _compact_structure_section_for_roadmap(sec)
            if not compact:
                continue
            compact["provenance"] = dict(compact.get("provenance") or {})
            compact["provenance"]["nyscef_document_number"] = smap.get(
                "nyscef_document_number"
            )
            compact["provenance"]["document_id"] = smap.get("document_id")
            selected.append(compact)
        if not selected:
            continue
        documents_out.append(
            {
                "document_id": smap.get("document_id"),
                "nyscef_document_number": smap.get("nyscef_document_number"),
                "schema_version": SCHEMA_VERSION,
                "sections": selected,
            }
        )
    if not documents_out:
        return None
    return {
        "note": COMPLAINT_RELIEF_STRUCTURE_NOTE,
        "schema_version": SCHEMA_VERSION,
        "documents": documents_out,
        "source_identified_pleaded_counts": enumerate_source_identified_pleaded_counts(
            structure_map
        ),
    }


def select_party_role_complaint_roadmap_context(
    structure_map: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
) -> Optional[dict[str, Any]]:
    """
    Build compact, source-cited complaint roadmap metadata for party-role packets.

    Emits the three-part party-role roadmap when supported by observed structure:
    (1) overview/introduction section(s); (2) intervening factual/background/
    allegation section(s) grouped as ``factual_layout`` without inventing a
    heading or continuous range; (3) party-identification section(s).
    Intervening procedural layout between overview and parties is included when
    present. Supplemental only — never a replacement for substantive retrieval
    hits. Returns None when schema is stale/absent, controlling-complaint
    selection failed, or no relevant structure is available.
    """
    documents_in: list[Mapping[str, Any]] = []
    if isinstance(structure_map, Mapping):
        if not is_current_structure_schema(structure_map):
            return None
        selection = structure_map.get("selection")
        if isinstance(selection, dict):
            sel_status = selection.get("status")
            if sel_status in {
                SELECTION_STATUS_AMBIGUOUS,
                SELECTION_STATUS_UNAVAILABLE,
            }:
                return None
        documents_in = [
            doc for doc in (structure_map.get("documents") or []) if isinstance(doc, dict)
        ]
    elif isinstance(structure_map, Sequence) and not isinstance(
        structure_map, (str, bytes)
    ):
        # Accept a list of DocumentStructure objects (or legacy per-doc maps).
        for item in structure_map:
            if isinstance(item, dict):
                documents_in.append(item)
    else:
        return None

    documents_out: list[dict[str, Any]] = []
    for smap in documents_in:
        sections = sections_from_document_structure(smap)
        if not sections:
            continue
        overview_idxs = [
            i for i, sec in enumerate(sections) if sec.get("kind") == "overview"
        ]
        parties_idxs = [
            i for i, sec in enumerate(sections) if sec.get("kind") == "parties"
        ]
        # Intervening procedural layout is attached only between overview and
        # parties when both exist; factual / overview / parties always attach.
        lo = min(overview_idxs) if overview_idxs else None
        hi = min(parties_idxs) if parties_idxs else None
        selected: list[dict[str, Any]] = []
        selected_indexes: set[int] = set()

        def _take(idx: int) -> None:
            if idx in selected_indexes or idx < 0 or idx >= len(sections):
                return
            compact = _compact_structure_section_for_roadmap(sections[idx])
            if not compact:
                return
            compact["provenance"] = dict(compact.get("provenance") or {})
            compact["provenance"]["nyscef_document_number"] = smap.get(
                "nyscef_document_number"
            )
            compact["provenance"]["document_id"] = smap.get("document_id")
            selected.append(compact)
            selected_indexes.add(idx)

        # Walk in source order so disjoint roadmap sections keep pleading order.
        for idx, sec in enumerate(sections):
            kind = sec.get("kind")
            if kind in {"overview", "factual_layout", "parties"}:
                _take(idx)
                continue
            if (
                kind == "procedural_layout"
                and lo is not None
                and hi is not None
                and lo < idx < hi
            ):
                _take(idx)

        if not selected:
            continue
        doc_uncertainties = [
            u for u in (smap.get("uncertainties") or []) if isinstance(u, dict)
        ]
        documents_out.append(
            {
                "document_id": smap.get("document_id"),
                "nyscef_document_number": smap.get("nyscef_document_number"),
                "schema_version": SCHEMA_VERSION,
                "sections": selected,
                "missing_paragraph_numbers": list(
                    smap.get("missing_paragraph_numbers") or []
                ),
                "noncontiguous_sequences": list(
                    smap.get("noncontiguous_sequences") or []
                ),
                "uncertainties": doc_uncertainties,
            }
        )

    if not documents_out:
        return None
    return {
        "note": PARTY_ROLE_ROADMAP_NOTE,
        "schema_version": SCHEMA_VERSION,
        "documents": documents_out,
    }


def merge_contract_structure_requirements(
    structure_context: Mapping[str, Any] | None,
    structure_requirements: Mapping[str, Any] | None,
) -> Optional[dict[str, Any]]:
    """Merge runtime contract-required ranges/categories into roadmap context.

    Ensures every supplied ``required_ranges`` entry (including ``factual_layout``)
    is retained on the context. Never invents Case-00-specific ranges; only
    carries through values supplied at runtime. Returns None when both inputs
    are empty/absent.
    """
    base: dict[str, Any]
    if isinstance(structure_context, Mapping):
        base = {
            "note": structure_context.get("note") or PARTY_ROLE_ROADMAP_NOTE,
            "schema_version": structure_context.get("schema_version") or SCHEMA_VERSION,
            "documents": [
                dict(doc)
                for doc in (structure_context.get("documents") or [])
                if isinstance(doc, dict)
            ],
        }
    else:
        base = {
            "note": PARTY_ROLE_ROADMAP_NOTE,
            "schema_version": SCHEMA_VERSION,
            "documents": [],
        }

    req = structure_requirements if isinstance(structure_requirements, Mapping) else {}
    # Acceptance contracts may describe the output packet itself (for example,
    # answer_text/supporting_evidence/limitations).  Those are not complaint
    # sections and must never be injected into complaint_structure_context.
    complaint_roadmap_kinds = {
        "overview",
        "procedural_layout",
        "factual_layout",
        "parties",
    }
    all_required_kinds = [
        str(k) for k in (req.get("required_kinds") or []) if str(k).strip()
    ]
    required_kinds = [
        kind for kind in all_required_kinds if kind in complaint_roadmap_kinds
    ]
    required_categories = [
        str(c) for c in (req.get("required_categories") or []) if str(c).strip()
    ]
    required_ranges = [
        dict(r)
        for r in (req.get("required_ranges") or [])
        if isinstance(r, dict)
        and str(r.get("kind") or "").strip() in complaint_roadmap_kinds
    ]

    # Preserve contract-required metadata without discarding existing sections.
    base["contract_required_kinds"] = list(required_kinds)
    base["contract_required_categories"] = list(required_categories)

    if not required_ranges and not required_kinds and not required_categories:
        if not base["documents"]:
            return None
        return base

    # Ensure each required range appears as a section marker; never drop
    # factual_layout (or any other kind) supplied by the contract.
    if base["documents"]:
        doc0 = dict(base["documents"][0])
        sections = [
            dict(s) for s in (doc0.get("sections") or []) if isinstance(s, dict)
        ]
    else:
        doc0 = {
            "document_id": "contract-structure-requirements",
            "nyscef_document_number": None,
            "schema_version": SCHEMA_VERSION,
            "sections": [],
            "missing_paragraph_numbers": [],
            "noncontiguous_sequences": [],
            "uncertainties": [],
        }
        sections = []

    def _range_key(kind: str, start: Any, end: Any) -> tuple:
        return (str(kind), start, end)

    existing_keys = set()
    for sec in sections:
        pr = sec.get("paragraph_range")
        if isinstance(pr, dict) and pr.get("start") is not None and pr.get("end") is not None:
            existing_keys.add(_range_key(sec.get("kind"), pr.get("start"), pr.get("end")))
        elif sec.get("kind"):
            # Heading-only / noncontiguous markers still count by kind+nums.
            nums = tuple(sec.get("paragraph_numbers") or [])
            existing_keys.add((str(sec.get("kind")), nums))

    for raw in required_ranges:
        kind = str(raw.get("kind") or "").strip()
        if not kind:
            continue
        try:
            start = int(raw["start"])
            end = int(raw["end"])
        except (KeyError, TypeError, ValueError):
            continue
        key = _range_key(kind, start, end)
        if key in existing_keys:
            continue
        section = {
            "heading": str(raw.get("heading") or kind.replace("_", " ").title()),
            "heading_normalized": kind.replace("_", " "),
            "match_key": kind,
            "kind": kind,
            "page_ids": list(raw.get("page_ids") or []),
            "page_numbers": list(raw.get("page_numbers") or []),
            "paragraph_numbers": list(range(start, end + 1)),
            "paragraph_range": {
                "start": start,
                "end": end,
                "contiguous": True,
            },
            "uncertainty": [],
            "provenance": {
                "page_ids": list(raw.get("page_ids") or []),
                "heading_marker": kind,
                "document_id": doc0.get("document_id"),
                "nyscef_document_number": doc0.get("nyscef_document_number"),
                "source": "acceptance_contract_structure_requirements",
            },
            "contract_category": str(raw.get("category") or ""),
        }
        sections.append(section)
        existing_keys.add(key)

    # Also ensure required_kinds without explicit ranges still have a marker
    # so downstream consumers do not silently drop the kind.
    present_kinds = {str(s.get("kind") or "") for s in sections}
    for kind in required_kinds:
        if kind in present_kinds:
            continue
        sections.append(
            {
                "heading": kind.replace("_", " ").title(),
                "heading_normalized": kind.replace("_", " "),
                "match_key": kind,
                "kind": kind,
                "page_ids": [],
                "page_numbers": [],
                "paragraph_numbers": [],
                "paragraph_range": None,
                "uncertainty": ["range_supplied_as_kind_only"],
                "provenance": {
                    "page_ids": [],
                    "heading_marker": kind,
                    "document_id": doc0.get("document_id"),
                    "nyscef_document_number": doc0.get("nyscef_document_number"),
                    "source": "acceptance_contract_structure_requirements",
                },
            }
        )
        present_kinds.add(kind)

    doc0["sections"] = sections
    if base["documents"]:
        base["documents"][0] = doc0
    else:
        base["documents"] = [doc0]
    return base


def structure_map_status(
    payload: Any,
) -> dict[str, Any]:
    """Explicit ok/degraded status for structure-map consumption."""
    if payload is None:
        return {
            "ok": False,
            "attached": False,
            "reason": "complaint_structure_map_absent",
            "schema_version": None,
            "required_schema_version": SCHEMA_VERSION,
        }
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "attached": False,
            "reason": "complaint_structure_map_invalid_type",
            "schema_version": None,
            "required_schema_version": SCHEMA_VERSION,
        }
    version = payload.get("schema_version")
    if not is_current_structure_schema(payload):
        return {
            "ok": False,
            "attached": False,
            "reason": "complaint_structure_map_stale_or_invalid_schema",
            "schema_version": version if isinstance(version, str) else None,
            "required_schema_version": SCHEMA_VERSION,
        }
    selection = payload.get("selection")
    if isinstance(selection, dict):
        sel_status = selection.get("status")
        if sel_status == SELECTION_STATUS_AMBIGUOUS:
            return {
                "ok": False,
                "attached": False,
                "reason": "controlling_complaint_ambiguous",
                "schema_version": SCHEMA_VERSION,
                "required_schema_version": SCHEMA_VERSION,
                "selection": selection,
            }
        if sel_status == SELECTION_STATUS_UNAVAILABLE:
            return {
                "ok": False,
                "attached": False,
                "reason": selection.get("reason")
                or "controlling_complaint_unavailable",
                "schema_version": SCHEMA_VERSION,
                "required_schema_version": SCHEMA_VERSION,
                "selection": selection,
            }
    return {
        "ok": True,
        "attached": False,
        "reason": None,
        "schema_version": SCHEMA_VERSION,
        "required_schema_version": SCHEMA_VERSION,
        "selection": selection if isinstance(selection, dict) else None,
    }


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
    paragraph_numbers.sort(
        key=lambda p: (
            int(p["page_number"]),
            int(p.get("line_index") or 0),
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

    document_id = document_id_for_nyscef(nyscef)
    sections = _build_document_sections(
        headings=section_headings,
        paragraphs=deduped_paragraphs,
        document_id=document_id,
        nyscef=nyscef,
    )

    # Drop internal line_index from public schema payload.
    for heading in section_headings:
        heading.pop("line_index", None)
    for para in deduped_paragraphs:
        para.pop("line_index", None)

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
        "document_id": document_id,
        "nyscef_document_number": nyscef,
        "source_pages": source_pages,
        "section_headings": section_headings,
        "paragraph_numbers": deduped_paragraphs,
        "sections": sections,
        "contiguous_ranges": contiguous_ranges,
        "missing_paragraph_numbers": missing,
        "noncontiguous_sequences": noncontiguous,
        "uncertainties": uncertainties,
    }


def build_complaint_structure_map(
    page_records: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    *,
    filing_inventory: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Build a deterministic complaint structure map for the controlling complaint.

    Uses authoritative filing metadata / document provenance to select a single
    controlling complaint before extraction. Answers, affidavits, motions,
    exhibits, and other response pleadings are never merged into the roadmap.
    """
    pages = _iter_page_records(page_records)
    selection = select_controlling_complaint(
        pages, filing_inventory=filing_inventory
    )
    if selection.get("status") != SELECTION_STATUS_SELECTED:
        return {
            "schema_version": SCHEMA_VERSION,
            "documents": [],
            "selection": selection,
        }

    controlling = int(selection["controlling_nyscef_document_number"])
    by_doc: dict[int, list[dict[str, Any]]] = {}
    for page in pages:
        nyscef = page.get("nyscef_document_number")
        if nyscef is None:
            continue
        nyscef_int = int(nyscef)
        if nyscef_int != controlling:
            continue
        by_doc.setdefault(nyscef_int, []).append(page)

    documents = [
        extract_document_structure(by_doc[nyscef])
        for nyscef in sorted(by_doc.keys())
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "documents": documents,
        "selection": selection,
    }


def empty_complaint_structure_map() -> dict[str, Any]:
    """Empty but schema-valid structure map (for validation fixtures)."""
    return {
        "schema_version": SCHEMA_VERSION,
        "documents": [],
        "selection": _empty_selection(
            status=SELECTION_STATUS_UNAVAILABLE,
            reason="no_documents",
        ),
    }
