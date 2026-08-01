# matter_builder.py
from pathlib import Path
import hashlib
import json
import os
import re

from engines.issue_engine import build_issue_analysis
from engines.entity_graph_engine import build_entity_graph
from engines.contradiction_index import build_contradiction_analysis

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

try:
    from docx import Document
except Exception:
    Document = None

try:
    import pytesseract
except Exception:
    pytesseract = None

try:
    from pdf2image import convert_from_path
except Exception:
    convert_from_path = None


DEFAULT_MATTER_FOLDER = Path("matter_docs")

# Configurable corpus / inventory roots (Railway / executor).
LEGALAI_MATTER_FOLDER_ENV = "LEGALAI_MATTER_FOLDER"
LEGALAI_NYSCEF_INVENTORY_PATH_ENV = "LEGALAI_NYSCEF_INVENTORY_PATH"

# Safe default inventory path for Case-00 when that corpus is explicitly selected
# via LEGALAI_NYSCEF_INVENTORY_PATH (or an explicit inventory_path argument).
CASE_00_TRIBOROUGH_INVENTORY_PATH = Path(
    "data/case-00-triborough/nyscef_filing_inventory.json"
)


DOCUMENT_GROUPS = {
    "selected_case": "Selected Case",
    "complaint": "Complaint",
    "answer": "Answer",
    "motion": "Motions",
    "affirmation": "Affirmations",
    "opposition": "Oppositions",
    "reply": "Replies",
    "exhibit": "Exhibits",
    "memo": "Memoranda of Law",
    "order": "Orders / Decisions",
    "other": "Other Documents",
}


ALLOWED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".doc",
    ".txt",
    ".rtf",
}


SKIP_FOLDERS = {
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    "node_modules",
}


COURT_HEADER_WORDS = {
    "supreme court",
    "civil court",
    "county court",
    "surrogate",
    "appellate division",
    "state of new york",
    "united states",
}


OCR_MIN_TEXT_LENGTH = 120

# Sparse cover pages used as a conservative exhibit-boundary signal.
EXHIBIT_SPARSE_COVER_MAX_CHARS = 220

# Minimum confidence required to assert an embedded exhibit boundary.
# Weaker candidates are retained as uncertain_exhibit_boundaries.
EXHIBIT_BOUNDARY_ASSERT_CONFIDENCE = {"high", "medium"}

# Used only for deterministic page_id formatting when no verified NYSCEF
# document number is available. Never invents a provenance document number.
UNKNOWN_NYSCEF_DOCUMENT_NUMBER = 0

# Conservative exhibit cover / heading detectors (page-local).
EXHIBIT_COVER_HEADING_RE = re.compile(
    r"(?is)^\s*(?:EXHIBIT|EXH\.?|EX\.)\s+([A-Z0-9]{1,4})\b"
    r"(?:\s*[-–—:;]\s*|\s+)(?P<title>[^\n]{0,120})?"
)
EXHIBIT_COVER_ONLY_RE = re.compile(
    r"(?is)^\s*(?:EXHIBIT|EXH\.?|EX\.)\s+([A-Z0-9]{1,4})\b\s*$"
)
EXHIBIT_NEAR_TOP_RE = re.compile(
    r"(?i)^(?:.{0,80}?)(?:EXHIBIT|EXH\.?|EX\.)\s+([A-Z]|[0-9]{1,3})\b"
)
EXHIBIT_PROSE_REFERENCE_RE = re.compile(
    r"(?i)\b(?:see|attached|annexed|marked|true\s+copy\s+of|copy\s+of)\s+"
    r"(?:as\s+)?(?:EXHIBIT|EXH\.?|EX\.)\s+[A-Z0-9]{1,4}\b"
)
EXHIBIT_BARE_WORD_RE = re.compile(r"(?is)^\s*EXHIBITS?\b\s*$")

# Benchmark folder naming from scraper/utils.js buildFilename:
#   {caseNumber}__{docType}__{date}.pdf
# That pattern carries an index/case id, not a NYSCEF document number.
BENCHMARK_FILENAME_RE = re.compile(
    r"^\d{4}-\d+__.+__\d{4}-\d{2}-\d{2}$",
    re.IGNORECASE,
)

NYSCEF_FILENAME_PATTERNS = [
    re.compile(
        r"(?i)\bnyscef[\s_-]*(?:doc(?:ument)?[\s_-]*)?(?:no\.?[\s_-]*)?(\d+)(?!\d)"
    ),
    re.compile(r"(?i)\bdoc(?:ument)?[\s_-]*no\.?[\s_-]*(\d+)(?!\d)"),
    re.compile(r"(?i)^(?:nyscef|doc)[\s_-]*(\d+)(?!\d)"),
]


def clean_text(value):
    return " ".join(str(value or "").split()).strip()


def coerce_nyscef_document_number(value):
    if value is None or value == "":
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_nyscef_document_number_from_filename(filename):
    """
    Conservatively parse a NYSCEF document number from a filename.

    Matches explicit NYSCEF / Doc No patterns only. Does not treat the
    repository benchmark pattern {case}__{type}__{date}.pdf as a document
    number.
    """
    name = Path(str(filename or "")).name
    stem = Path(name).stem

    if not stem:
        return None

    if BENCHMARK_FILENAME_RE.match(stem):
        return None

    if "__" in stem and re.match(r"^\d{4}-\d+", stem):
        return None

    for pattern in NYSCEF_FILENAME_PATTERNS:
        match = pattern.search(stem)
        if match:
            return coerce_nyscef_document_number(match.group(1))

    return None


def resolve_nyscef_document_number(document=None, filename=None):
    """Prefer explicit metadata; otherwise try a conservative filename parse."""
    if isinstance(document, dict) and "nyscef_document_number" in document:
        return coerce_nyscef_document_number(document.get("nyscef_document_number"))

    name = filename
    if name is None and isinstance(document, dict):
        name = document.get("filename") or document.get("name") or document.get("title")

    return parse_nyscef_document_number_from_filename(name)


def resolve_matter_folder(matter_folder=None):
    """
    Resolve the matter/corpus root.

    Precedence: explicit argument > LEGALAI_MATTER_FOLDER > matter_docs.
    """
    if matter_folder is not None:
        return Path(matter_folder)

    env_value = os.environ.get(LEGALAI_MATTER_FOLDER_ENV)
    if env_value:
        return Path(env_value)

    return DEFAULT_MATTER_FOLDER


def resolve_inventory_path(inventory_path=None):
    """
    Resolve an optional NYSCEF filing inventory path.

    Precedence: explicit argument > LEGALAI_NYSCEF_INVENTORY_PATH > None.
    Unrelated matters stay inventory-free unless configuration selects one.
    The Case-00 aliases `case-00-triborough` / `case-00` resolve to
    CASE_00_TRIBOROUGH_INVENTORY_PATH when that corpus is explicitly selected.
    """
    if inventory_path is not None:
        raw = inventory_path
    else:
        raw = os.environ.get(LEGALAI_NYSCEF_INVENTORY_PATH_ENV)

    if raw is None or raw == "":
        return None

    text = str(raw).strip()
    if text in {"case-00-triborough", "case-00", "triborough"}:
        return CASE_00_TRIBOROUGH_INVENTORY_PATH

    return Path(text)


def load_nyscef_filing_inventory(inventory_path):
    """Load a canonical NYSCEF filing inventory JSON, or None if unavailable."""
    if not inventory_path:
        return None

    path = Path(inventory_path)
    if not path.is_file():
        print(f"INVENTORY MISSING [{path}]")
        return None

    try:
        payload = json.loads(path.read_text())
    except Exception as exc:
        print(f"INVENTORY LOAD FAILED [{path}] -> {exc}")
        return None

    if not isinstance(payload, dict):
        print(f"INVENTORY INVALID [{path}] expected object")
        return None

    filings = payload.get("filings")
    if not isinstance(filings, list):
        print(f"INVENTORY INVALID [{path}] missing filings list")
        return None

    return payload


def index_inventory_by_filename(inventory):
    """Map exact filename -> list of filing records."""
    index = {}
    if not inventory:
        return index

    for entry in inventory.get("filings") or []:
        if not isinstance(entry, dict):
            continue
        filename = entry.get("filename")
        if not filename:
            continue
        index.setdefault(str(filename), []).append(entry)

    return index


def compute_file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def lookup_inventory_provenance(path, inventory_by_filename):
    """
    Match a physical file to inventory by exact filename and verify SHA-256.

    Never invents a NYSCEF number from an unverified filename. Returns a
    provenance dict with status:
      verified | non_canonical_duplicate | hash_mismatch | missing | ambiguous
    """
    path = Path(path)
    filename = path.name
    entries = list(inventory_by_filename.get(filename) or [])

    if not entries:
        return {
            "status": "missing",
            "nyscef_document_number": None,
            "ingest_canonical": None,
            "inventory_entry": None,
        }

    if len(entries) > 1:
        return {
            "status": "ambiguous",
            "nyscef_document_number": None,
            "ingest_canonical": None,
            "inventory_entry": None,
        }

    entry = entries[0]
    expected_sha = str(entry.get("sha256") or "").lower()
    try:
        actual_sha = compute_file_sha256(path).lower()
    except Exception as exc:
        print(f"INVENTORY HASH FAILED [{filename}] -> {exc}")
        return {
            "status": "hash_mismatch",
            "nyscef_document_number": None,
            "ingest_canonical": bool(entry.get("ingest_canonical"))
            if "ingest_canonical" in entry
            else None,
            "inventory_entry": entry,
        }

    if not expected_sha or actual_sha != expected_sha:
        print(
            f"INVENTORY HASH MISMATCH [{filename}] "
            f"expected={expected_sha or '—'} actual={actual_sha}"
        )
        return {
            "status": "hash_mismatch",
            "nyscef_document_number": None,
            "ingest_canonical": bool(entry.get("ingest_canonical"))
            if "ingest_canonical" in entry
            else None,
            "inventory_entry": entry,
        }

    ingest_canonical = bool(entry.get("ingest_canonical", True))
    if not ingest_canonical:
        return {
            "status": "non_canonical_duplicate",
            "nyscef_document_number": coerce_nyscef_document_number(
                entry.get("nyscef_document_number")
            ),
            "ingest_canonical": False,
            "inventory_entry": entry,
        }

    return {
        "status": "verified",
        "nyscef_document_number": coerce_nyscef_document_number(
            entry.get("nyscef_document_number")
        ),
        "ingest_canonical": True,
        "inventory_entry": entry,
    }


def make_page_id(nyscef_document_number, page_number):
    doc_no = coerce_nyscef_document_number(nyscef_document_number)
    if doc_no is None:
        doc_no = UNKNOWN_NYSCEF_DOCUMENT_NUMBER

    return f"nyscef-{doc_no:03d}-page-{int(page_number):04d}"


def build_page_record(page_number, text, extraction_method, nyscef_document_number=None):
    return {
        "page_number": int(page_number),
        "page_id": make_page_id(nyscef_document_number, page_number),
        "text": text if isinstance(text, str) else str(text or ""),
        "extraction_method": extraction_method,
    }


def aggregate_page_text(pages):
    return clean_text("\n".join(
        (page.get("text") or "") if isinstance(page, dict) else ""
        for page in (pages or [])
    ))


def normalize_page_record(page, nyscef_document_number=None):
    page = page or {}
    page_number = int(page.get("page_number") or 0)
    raw_text = page.get("text", "")
    text = clean_text(raw_text) if raw_text else ""

    extraction_method = page.get("extraction_method")
    if extraction_method not in {"native", "ocr", "empty"}:
        if text:
            extraction_method = "native"
        else:
            extraction_method = "empty"

    page_id = page.get("page_id") or make_page_id(nyscef_document_number, page_number)

    return {
        "page_number": page_number,
        "page_id": page_id,
        "text": text,
        "extraction_method": extraction_method,
    }


def make_segment_id(nyscef_document_number, segment_index):
    """Deterministic segment ID aligned with NYSCEF page_id formatting."""
    doc_no = coerce_nyscef_document_number(nyscef_document_number)
    if doc_no is None:
        doc_no = UNKNOWN_NYSCEF_DOCUMENT_NUMBER

    return f"nyscef-{doc_no:03d}-segment-{int(segment_index):04d}"


def normalize_exhibit_label(value):
    value = clean_text(value).upper()
    value = value.replace("EXHIBIT", "").replace("EXH.", "").replace("EXH", "")
    value = re.sub(r"[^A-Z0-9]", "", value)
    if value:
        return value[:8]
    return None


def normalize_exhibit_title(value):
    title = clean_text(value)
    if not title:
        return None
    title = re.sub(r"(?i)^(to|:|-|–|—)\s*", "", title).strip()
    if not title or title.upper() in {"EXHIBIT", "EXH", "EX"}:
        return None
    return title[:160]


def _page_raw_text(page):
    if not isinstance(page, dict):
        return ""
    text = page.get("text")
    return text if isinstance(text, str) else str(text or "")


def detect_page_exhibit_signals(page):
    """
    Collect conservative exhibit-boundary signals for a single page.

    Strong signals favor cover/heading patterns. Prose references alone are
    ignored so we do not invent boundaries from weak evidence.
    """
    raw = _page_raw_text(page)
    if not raw or not raw.strip():
        return []

    # Preserve line structure when present; cleaned aggregates still work.
    stripped = raw.strip()
    first_line = stripped.splitlines()[0].strip() if stripped else ""
    cleaned = clean_text(raw)
    char_count = len(cleaned)
    signals = []

    # Prose citations ("see Exhibit A") are not boundary evidence unless the
    # page itself opens with an exhibit cover/heading line.
    prose_ref = EXHIBIT_PROSE_REFERENCE_RE.search(cleaned)
    opens_with_cover = bool(
        EXHIBIT_COVER_HEADING_RE.match(first_line)
        or EXHIBIT_COVER_ONLY_RE.match(stripped)
        or EXHIBIT_COVER_HEADING_RE.match(stripped)
    )
    if prose_ref and not opens_with_cover:
        return []

    cover_only = EXHIBIT_COVER_ONLY_RE.match(stripped) or EXHIBIT_COVER_ONLY_RE.match(
        cleaned
    )
    if cover_only:
        label = normalize_exhibit_label(cover_only.group(1))
        if label:
            signals.append(
                {
                    "kind": "cover_label",
                    "strength": "strong",
                    "exhibit_label": label,
                    "exhibit_title": None,
                    "detail": f"Sparse/cover page labeled Exhibit {label}",
                }
            )

    heading = EXHIBIT_COVER_HEADING_RE.match(stripped) or EXHIBIT_COVER_HEADING_RE.match(
        first_line
    )
    if heading and not cover_only:
        label = normalize_exhibit_label(heading.group(1))
        title = normalize_exhibit_title(heading.group("title"))
        if label:
            strength = (
                "strong" if char_count <= EXHIBIT_SPARSE_COVER_MAX_CHARS else "medium"
            )
            kind = "titled_cover" if title else "heading_label"
            signals.append(
                {
                    "kind": kind,
                    "strength": strength,
                    "exhibit_label": label,
                    "exhibit_title": title,
                    "detail": (
                        f"Exhibit {label} heading at page start"
                        + (f" titled '{title}'" if title else "")
                    ),
                }
            )

    if char_count <= EXHIBIT_SPARSE_COVER_MAX_CHARS and EXHIBIT_BARE_WORD_RE.match(
        stripped
    ):
        signals.append(
            {
                "kind": "separator_cover",
                "strength": "weak",
                "exhibit_label": None,
                "exhibit_title": None,
                "detail": "Sparse separator page containing only 'Exhibit(s)'",
            }
        )

    if not signals:
        # Near-top mention without clear cover heading → uncertain candidate only.
        near = EXHIBIT_NEAR_TOP_RE.search(cleaned[:300])
        if near and not EXHIBIT_PROSE_REFERENCE_RE.search(cleaned[:300]):
            label = normalize_exhibit_label(near.group(1))
            if label:
                signals.append(
                    {
                        "kind": "near_top_mention",
                        "strength": "weak",
                        "exhibit_label": label,
                        "exhibit_title": None,
                        "detail": (
                            f"Exhibit {label} mentioned near top without cover pattern"
                        ),
                    }
                )

    # Reinforce sparseness only for cover/heading hits — never for weak
    # near-top mentions, which would otherwise inflate confidence to assert.
    cover_kinds = {"cover_label", "titled_cover", "heading_label"}
    if char_count <= EXHIBIT_SPARSE_COVER_MAX_CHARS and any(
        s.get("kind") in cover_kinds and s.get("exhibit_label") for s in signals
    ):
        if not any(s["kind"] == "sparse_cover_context" for s in signals):
            label = next(
                s["exhibit_label"]
                for s in signals
                if s.get("kind") in cover_kinds and s.get("exhibit_label")
            )
            signals.append(
                {
                    "kind": "sparse_cover_context",
                    "strength": "medium",
                    "exhibit_label": label,
                    "exhibit_title": None,
                    "detail": "Short page consistent with an exhibit cover sheet",
                }
            )

    return signals


def score_exhibit_boundary_confidence(signals):
    if not signals:
        return None

    strengths = {s.get("strength") for s in signals}
    kinds = {s.get("kind") for s in signals}

    if "strong" in strengths and (
        "cover_label" in kinds
        or "titled_cover" in kinds
        or "heading_label" in kinds
    ):
        if "sparse_cover_context" in kinds or "cover_label" in kinds:
            return "high"
        return "high" if "strong" in strengths else "medium"

    if "medium" in strengths and (
        "heading_label" in kinds
        or "titled_cover" in kinds
        or "sparse_cover_context" in kinds
    ):
        return "medium"

    if strengths.intersection({"strong", "medium", "weak"}):
        return "low"

    return None


def _primary_signal_label_title(signals):
    label = None
    title = None
    for signal in signals:
        if label is None and signal.get("exhibit_label"):
            label = signal["exhibit_label"]
        if title is None and signal.get("exhibit_title"):
            title = signal["exhibit_title"]
    return label, title


def segment_embedded_exhibits(pages, nyscef_document_number=None):
    """
    Segment a filing's pages into parent material and embedded exhibits.

    Conservative: only assert boundaries with medium/high confidence.
    Weak candidates are returned under uncertain_boundaries and do not split
    segments. Every page is assigned to exactly one primary segment; pages are
    never dropped or duplicated.
    """
    normalized_pages = [
        normalize_page_record(page, nyscef_document_number) for page in (pages or [])
    ]

    uncertain_boundaries = []
    asserted_starts = []  # list of (page_index, label, title, confidence, signals)

    for index, page in enumerate(normalized_pages):
        signals = detect_page_exhibit_signals(page)
        if not signals:
            continue

        confidence = score_exhibit_boundary_confidence(signals)
        label, title = _primary_signal_label_title(signals)
        page_number = page["page_number"]
        evidence = [
            {
                "kind": s.get("kind"),
                "strength": s.get("strength"),
                "detail": s.get("detail"),
                "exhibit_label": s.get("exhibit_label"),
            }
            for s in signals
        ]

        candidate = {
            "page_number": page_number,
            "page_id": page["page_id"],
            "exhibit_label": label,
            "exhibit_title": title,
            "boundary_confidence": confidence,
            "boundary_evidence": evidence,
        }

        if confidence in EXHIBIT_BOUNDARY_ASSERT_CONFIDENCE and label:
            # Avoid re-asserting the same label on the immediately continued page
            # when the heading merely repeats with no new cover evidence change.
            if asserted_starts:
                prev = asserted_starts[-1]
                if prev["exhibit_label"] == label and prev["page_index"] == index - 1:
                    # Treat repeated label on next page as continuation noise unless
                    # this page is itself a sparse cover for a *different* span.
                    if not any(s.get("kind") == "cover_label" for s in signals):
                        uncertain_boundaries.append(candidate)
                        continue
            asserted_starts.append(
                {
                    "page_index": index,
                    "exhibit_label": label,
                    "exhibit_title": title,
                    "boundary_confidence": confidence,
                    "boundary_evidence": evidence,
                }
            )
        else:
            uncertain_boundaries.append(candidate)

    segments = []
    segment_index = 1
    page_count = len(normalized_pages)

    def _emit_segment(start_idx, end_idx, segment_type, label, title, confidence, evidence):
        nonlocal segment_index
        if start_idx > end_idx or start_idx < 0 or end_idx >= page_count:
            return

        slice_pages = normalized_pages[start_idx : end_idx + 1]
        segment = {
            "segment_id": make_segment_id(nyscef_document_number, segment_index),
            "nyscef_document_number": coerce_nyscef_document_number(
                nyscef_document_number
            ),
            "segment_type": segment_type,
            "exhibit_label": label,
            "exhibit_title": title,
            "start_page": slice_pages[0]["page_number"],
            "end_page": slice_pages[-1]["page_number"],
            "page_ids": [p["page_id"] for p in slice_pages],
            "boundary_confidence": confidence,
            "boundary_evidence": list(evidence or []),
        }
        segments.append(segment)
        segment_index += 1

    if not asserted_starts:
        if page_count:
            _emit_segment(
                0,
                page_count - 1,
                "parent",
                None,
                None,
                "high",
                [
                    {
                        "kind": "no_embedded_exhibit",
                        "strength": "strong",
                        "detail": "No evidence-backed embedded exhibit boundary detected",
                        "exhibit_label": None,
                    }
                ],
            )
        return {
            "segments": segments,
            "uncertain_boundaries": uncertain_boundaries,
        }

    # Parent material before the first asserted exhibit, if any.
    first_start = asserted_starts[0]["page_index"]
    if first_start > 0:
        _emit_segment(
            0,
            first_start - 1,
            "parent",
            None,
            None,
            "high",
            [
                {
                    "kind": "parent_prefix",
                    "strength": "strong",
                    "detail": "Filing material preceding first embedded exhibit",
                    "exhibit_label": None,
                }
            ],
        )

    for i, start in enumerate(asserted_starts):
        start_idx = start["page_index"]
        if i + 1 < len(asserted_starts):
            end_idx = asserted_starts[i + 1]["page_index"] - 1
        else:
            end_idx = page_count - 1

        _emit_segment(
            start_idx,
            end_idx,
            "exhibit",
            start["exhibit_label"],
            start["exhibit_title"],
            start["boundary_confidence"],
            start["boundary_evidence"],
        )

    # Integrity: every page id appears exactly once across primary segments.
    assigned = [page_id for seg in segments for page_id in seg["page_ids"]]
    expected = [p["page_id"] for p in normalized_pages]
    if assigned != expected:
        # Repair by collapsing to a single parent segment rather than dropping
        # or duplicating pages. Uncertain candidates are still returned.
        segments = []
        segment_index = 1
        _emit_segment(
            0,
            page_count - 1,
            "parent",
            None,
            None,
            "low",
            [
                {
                    "kind": "integrity_repair",
                    "strength": "strong",
                    "detail": "Segment boundaries repaired to preserve page coverage",
                    "exhibit_label": None,
                }
            ],
        )

    return {
        "segments": segments,
        "uncertain_boundaries": uncertain_boundaries,
    }


def clean_case_party(value):
    value = clean_text(value)

    value = re.sub(r"(?i)\bSUPREME COURT OF THE STATE OF NEW YORK\b", "", value)
    value = re.sub(r"(?i)\bSTATE OF NEW YORK\b", "", value)
    value = re.sub(r"(?i)\bCOUNTY OF [A-Z\s]+\b", "", value)
    value = re.sub(r"(?i)\bINDEX\s*(NO\.?|NUMBER)?\s*[:#]?\s*[0-9]{4,8}/?[0-9]{0,4}\b", "", value)
    value = re.sub(r"(?i)\bPlaintiff[s]?\b", "", value)
    value = re.sub(r"(?i)\bDefendant[s]?\b", "", value)
    value = re.sub(r"(?i)\bPetitioner[s]?\b", "", value)
    value = re.sub(r"(?i)\bRespondent[s]?\b", "", value)

    value = value.replace(" -against- ", " ")
    value = value.replace(" against ", " ")

    value = re.sub(r"[_|]+", " ", value)
    value = re.sub(r"\s+", " ", value)

    return value.strip(" ,.-")


def classify_by_filename(filename):
    name = filename.lower()

    if "selected case" in name or "search result" in name:
        return "selected_case"

    if "complaint" in name:
        return "complaint"

    if "answer" in name:
        return "answer"

    if "notice of motion" in name or "motion" in name:
        return "motion"

    if "affirmation" in name or "affidavit" in name or "declaration" in name:
        return "affirmation"

    if "opposition" in name or "opp" in name:
        return "opposition"

    if "reply" in name:
        return "reply"

    if "exhibit" in name or "exh" in name:
        return "exhibit"

    if "memo" in name or "memorandum" in name or "memorandum of law" in name:
        return "memo"

    if "order" in name or "decision" in name or "judgment" in name:
        return "order"

    return "other"


def extract_txt(path):
    try:
        return path.read_text(errors="ignore")
    except Exception:
        return ""


def extract_pdf_native_pages(path):
    """Return one native text entry per physical PDF page (including empties)."""
    if PdfReader is None:
        return []

    try:
        reader = PdfReader(str(path))
        pages = []

        for index, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            pages.append({"page_number": index, "text": text})

        print(f"PDF NATIVE [{Path(path).name}] pages={len(pages)}")
        return pages

    except Exception as e:
        print(f"PDF NATIVE FAILED [{Path(path).name}] -> {e}")
        return []


def extract_pdf_ocr_page(path, page_number):
    """OCR a single physical PDF page. No document-wide page cap."""
    if pytesseract is None or convert_from_path is None:
        print(f"OCR UNAVAILABLE [{Path(path).name}]")
        return ""

    try:
        print(f"OCR PAGE {page_number} [{Path(path).name}]")

        images = convert_from_path(
            str(path),
            dpi=250,
            first_page=page_number,
            last_page=page_number,
        )

        if not images:
            return ""

        return pytesseract.image_to_string(images[0]) or ""

    except Exception as e:
        print(f"OCR FAILED [{Path(path).name} page={page_number}] -> {e}")
        return ""


def extract_pdf_document(path, nyscef_document_number=None, *, allow_filename_nyscef_parse=True):
    """
    Extract every physical PDF page with per-page OCR fallback.

    Returns text, pages, page_count, and nyscef_document_number.
    """
    path = Path(path)

    if nyscef_document_number is not None:
        nyscef_document_number = coerce_nyscef_document_number(nyscef_document_number)
    elif allow_filename_nyscef_parse:
        nyscef_document_number = parse_nyscef_document_number_from_filename(path.name)
    else:
        nyscef_document_number = None

    native_pages = extract_pdf_native_pages(path)
    page_records = []

    for native in native_pages:
        page_number = native["page_number"]
        native_text = clean_text(native.get("text"))

        if len(native_text) >= OCR_MIN_TEXT_LENGTH:
            page_records.append(
                build_page_record(
                    page_number,
                    native_text,
                    "native",
                    nyscef_document_number,
                )
            )
            continue

        print(
            f"PDF LOW TEXT [{path.name}] page={page_number} "
            f"chars={len(native_text)} attempting OCR fallback"
        )

        ocr_text = clean_text(extract_pdf_ocr_page(path, page_number))

        if len(ocr_text) > len(native_text):
            print(f"PDF OCR SUCCESS [{path.name}] page={page_number}")
            page_records.append(
                build_page_record(
                    page_number,
                    ocr_text,
                    "ocr",
                    nyscef_document_number,
                )
            )
        elif native_text:
            page_records.append(
                build_page_record(
                    page_number,
                    native_text,
                    "native",
                    nyscef_document_number,
                )
            )
        else:
            page_records.append(
                build_page_record(
                    page_number,
                    "",
                    "empty",
                    nyscef_document_number,
                )
            )

    aggregate = aggregate_page_text(page_records)

    if page_records:
        print(
            f"PDF OK [{path.name}] pages={len(page_records)} "
            f"chars={len(aggregate)}"
        )

    return {
        "text": aggregate,
        "pages": page_records,
        "page_count": len(page_records),
        "nyscef_document_number": nyscef_document_number,
    }


def extract_pdf(path):
    """Backward-compatible aggregate text extraction."""
    return extract_pdf_document(path)["text"]


def extract_docx(path):
    if Document is None:
        return ""

    try:
        doc = Document(str(path))
        paragraphs = []

        for paragraph in doc.paragraphs:
            text = paragraph.text.strip()

            if text:
                paragraphs.append(text)

        return "\n".join(paragraphs)

    except Exception:
        return ""


def extract_text(path):
    suffix = path.suffix.lower()

    if suffix == ".txt":
        return extract_txt(path)

    if suffix == ".pdf":
        return extract_pdf(path)

    if suffix == ".docx":
        return extract_docx(path)

    return ""


def should_skip_path(path):
    parts = set(path.parts)

    for folder in SKIP_FOLDERS:
        if folder in parts:
            return True

    if path.name.startswith("."):
        return True

    return False


def find_matter_files(folder_path):
    folder = Path(folder_path)

    if not folder.exists() or not folder.is_dir():
        return []

    files = []

    for path in folder.rglob("*"):
        if should_skip_path(path):
            continue

        if not path.is_file():
            continue

        if path.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue

        files.append(path)

    return sorted(files, key=lambda p: str(p).lower())


def read_matter_folder(folder_path=None, inventory_path=None):
    folder = resolve_matter_folder(folder_path)
    files = find_matter_files(folder)

    resolved_inventory_path = resolve_inventory_path(inventory_path)
    inventory = load_nyscef_filing_inventory(resolved_inventory_path)
    inventory_by_filename = index_inventory_by_filename(inventory)
    inventory_enabled = inventory is not None

    documents = []

    for path in files:
        print(f"\nPROCESSING FILE: {path.name}")

        provenance = None
        verified_nyscef = None

        if inventory_enabled and path.suffix.lower() == ".pdf":
            provenance = lookup_inventory_provenance(path, inventory_by_filename)

            if provenance["status"] == "non_canonical_duplicate":
                print(
                    f"INVENTORY SKIP DUPLICATE [{path.name}] "
                    f"nyscef={provenance.get('nyscef_document_number')}"
                )
                continue

            if provenance["status"] == "verified":
                verified_nyscef = provenance.get("nyscef_document_number")
            else:
                print(
                    f"INVENTORY PROVENANCE UNRESOLVED [{path.name}] "
                    f"status={provenance['status']}"
                )
                # Do not assign a guessed NYSCEF number from the filename.
                verified_nyscef = None

        doc_type = classify_by_filename(path.name)

        document = {
            "filename": path.name,
            "title": path.name,
            "path": str(path),
            "relative_path": str(path.relative_to(folder)) if folder.exists() else str(path),
            "folder": str(path.parent),
            "type": doc_type,
            "category": doc_type,
            "group": DOCUMENT_GROUPS.get(doc_type, DOCUMENT_GROUPS["other"]),
            "source": "folder",
        }

        if path.suffix.lower() == ".pdf":
            if inventory_enabled:
                if provenance is not None and provenance.get("status") == "verified":
                    pdf_doc = extract_pdf_document(
                        path,
                        nyscef_document_number=verified_nyscef,
                    )
                else:
                    # Inventory configured but provenance unresolved: never guess.
                    pdf_doc = extract_pdf_document(
                        path,
                        nyscef_document_number=None,
                        allow_filename_nyscef_parse=False,
                    )
            else:
                pdf_doc = extract_pdf_document(path)

            extracted_text = pdf_doc["text"]
            document["text"] = extracted_text
            document["preview"] = extracted_text[:800]
            document["pages"] = pdf_doc["pages"]
            document["page_count"] = pdf_doc["page_count"]
            document["nyscef_document_number"] = pdf_doc["nyscef_document_number"]
            if provenance is not None:
                document["nyscef_provenance_status"] = provenance["status"]
        else:
            extracted_text = clean_text(extract_text(path))
            document["text"] = extracted_text
            document["preview"] = extracted_text[:800]

        print(
            f"CLASSIFIED [{path.name}] "
            f"type={doc_type} "
            f"chars={len(document['text'])}"
        )

        documents.append(document)

    return documents


def selected_case_to_document(selected_case):
    if not selected_case:
        return None

    title = clean_text(selected_case.get("title") or selected_case.get("case_name") or "Selected Case")
    court = clean_text(selected_case.get("court"))
    date = clean_text(selected_case.get("date"))
    citation = clean_text(selected_case.get("citation"))
    outcome = clean_text(selected_case.get("outcome"))
    motion = clean_text(selected_case.get("motion"))
    cause = clean_text(selected_case.get("primary_cause"))
    holding = clean_text(selected_case.get("holding"))
    rule = clean_text(selected_case.get("rule"))

    text = clean_text(
        selected_case.get("formatted_text")
        or selected_case.get("text")
        or selected_case.get("summary")
        or selected_case.get("snippet")
        or ""
    )

    metadata_lines = []

    if title:
        metadata_lines.append(title)

    if court:
        metadata_lines.append(f"Court: {court}")

    if date:
        metadata_lines.append(f"Date: {date}")

    if citation:
        metadata_lines.append(f"Citation: {citation}")

    if motion:
        metadata_lines.append(f"Motion: {motion}")

    if outcome:
        metadata_lines.append(f"Outcome: {outcome}")

    if cause:
        metadata_lines.append(f"Cause: {cause}")

    if rule:
        metadata_lines.append(f"Rule: {rule}")

    if holding:
        metadata_lines.append(f"Holding: {holding}")

    combined = clean_text("\n".join(metadata_lines + [text]))

    return {
        "filename": f"Selected Case - {title}",
        "title": title,
        "path": "",
        "relative_path": "Selected from search results",
        "folder": "",
        "type": "selected_case",
        "category": "selected_case",
        "group": DOCUMENT_GROUPS["selected_case"],
        "text": combined,
        "preview": combined[:800],
        "source": "selected_case",
        "court": court,
        "date": date,
        "citation": citation,
        "motion": motion,
        "outcome": outcome,
        "primary_cause": cause,
        "holding": holding,
        "rule": rule,
        "case_id": clean_text(selected_case.get("case_id")),
    }


def normalize_document(document, *, include_exhibit_segments=None):
    filename = clean_text(
        document.get("filename")
        or document.get("name")
        or document.get("title")
        or "Untitled Document"
    )

    doc_type = (
        document.get("type")
        or document.get("category")
        or classify_by_filename(filename)
    )

    group = DOCUMENT_GROUPS.get(doc_type, DOCUMENT_GROUPS["other"])

    nyscef_document_number = None
    if "nyscef_document_number" in document:
        nyscef_document_number = coerce_nyscef_document_number(
            document.get("nyscef_document_number")
        )
    else:
        nyscef_document_number = parse_nyscef_document_number_from_filename(filename)

    pages = None
    page_count = None

    if "pages" in document and document.get("pages") is not None:
        pages = [
            normalize_page_record(page, nyscef_document_number)
            for page in document.get("pages") or []
        ]
        page_count = document.get("page_count")
        if page_count is None:
            page_count = len(pages)
        else:
            try:
                page_count = int(page_count)
            except (TypeError, ValueError):
                page_count = len(pages)
        text = aggregate_page_text(pages)
    else:
        text = clean_text(document.get("text", ""))
        if "page_count" in document and document.get("page_count") is not None:
            try:
                page_count = int(document.get("page_count"))
            except (TypeError, ValueError):
                page_count = None

    normalized = {
        "filename": filename,
        "title": clean_text(document.get("title") or filename),
        "path": document.get("path", ""),
        "relative_path": document.get("relative_path", document.get("path", "")),
        "folder": document.get("folder", ""),
        "type": doc_type,
        "category": doc_type,
        "group": group,
        "text": text,
        "preview": text[:800],
        "source": document.get("source", "manual"),
        "court": document.get("court", ""),
        "date": document.get("date", ""),
        "citation": document.get("citation", ""),
        "motion": document.get("motion", ""),
        "outcome": document.get("outcome", ""),
        "primary_cause": document.get("primary_cause", ""),
        "holding": document.get("holding", ""),
        "rule": document.get("rule", ""),
        "case_id": document.get("case_id", ""),
    }

    if "nyscef_document_number" in document or nyscef_document_number is not None:
        normalized["nyscef_document_number"] = nyscef_document_number

    if pages is not None:
        normalized["pages"] = pages

    if page_count is not None:
        normalized["page_count"] = page_count

    # Additive opt-in: kwarg wins; otherwise honor document flag. Default off
    # so existing consumers receive unchanged document/page structures.
    # If a prior normalize already attached exhibit_segments, keep opting in so
    # group_documents / re-normalize paths do not silently drop them.
    if include_exhibit_segments is None:
        if "include_exhibit_segments" in document:
            include_exhibit_segments = bool(document.get("include_exhibit_segments"))
        else:
            include_exhibit_segments = "exhibit_segments" in document

    if include_exhibit_segments and pages is not None:
        segmentation = segment_embedded_exhibits(pages, nyscef_document_number)
        normalized["exhibit_segments"] = segmentation["segments"]
        if segmentation["uncertain_boundaries"]:
            normalized["uncertain_exhibit_boundaries"] = segmentation[
                "uncertain_boundaries"
            ]

    return normalized


def group_documents(documents):
    grouped = {label: [] for label in DOCUMENT_GROUPS.values()}

    for document in documents:
        normalized = normalize_document(document)
        grouped[normalized["group"]].append(normalized)

    return grouped


def combined_text(documents, limit=50000):
    chunks = []

    for doc in documents:
        text = clean_text(doc.get("text", ""))

        if text:
            chunks.append(text)

    return clean_text(" ".join(chunks))[:limit]


def extract_index_number(text):
    patterns = [
        r"index\\s*(?:no\\.?|number)?\\s*[:#]?\\s*([0-9]{4,8}/[0-9]{4})",
        r"index\\s*(?:no\\.?|number)?\\s*[:#]?\\s*([0-9]{5,8})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            return clean_text(match.group(1))

    return "—"


def extract_case_name(text):
    patterns = [
        r"([A-Z][A-Za-z0-9&.,'\\-\\s]{2,80})\\s+v\\.?\\s+([A-Z][A-Za-z0-9&.,'\\-\\s]{2,80})",
        r"([A-Z][A-Za-z0-9&.,'\\-\\s]{2,80})\\s+against\\s+([A-Z][A-Za-z0-9&.,'\\-\\s]{2,80})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if match:
            left = clean_case_party(match.group(1))
            right = clean_case_party(match.group(2))

            if left and right:
                return f"{left} v. {right}"

    return "Matter Builder"


def extract_parties(case_name):
    if " v. " not in case_name:
        return {"plaintiff": "—", "defendant": "—"}

    left, right = case_name.split(" v. ", 1)

    return {
        "plaintiff": clean_case_party(left) or "—",
        "defendant": clean_case_party(right) or "—",
    }


def detect_motion_posture(documents, text):
    names = " ".join(doc.get("filename", "") for doc in documents).lower()

    haystack = f"{names} {text.lower()}"

    if "summary judgment" in haystack:
        return "Summary judgment motion"

    if "dismiss" in haystack or "3211" in haystack:
        return "Motion to dismiss"

    if "default judgment" in haystack:
        return "Default judgment motion"

    if "discovery" in haystack or "compel" in haystack:
        return "Discovery motion"

    if "opposition" in haystack:
        return "Opposition papers"

    return "—"


def detect_procedural_posture(text):
    lower = text.lower()

    if "complaint" in lower and "answer" in lower and "motion" in lower:
        return "Pleadings and motion papers are present."

    if "complaint" in lower and "motion" in lower:
        return "Complaint and motion papers are present."

    if "order" in lower or "decision" in lower:
        return "Prior order or decision appears to be present."

    return "Procedural posture not yet detected from extracted text."


def strongest_motion_documents(documents):
    ranked = []

    weights = {
        "selected_case": 120,
        "motion": 100,
        "opposition": 90,
        "affirmation": 80,
        "memo": 75,
        "reply": 70,
        "order": 60,
        "complaint": 40,
        "answer": 35,
        "exhibit": 20,
        "other": 10,
    }

    for doc in documents:
        doc_type = doc.get("type", "other")
        score = weights.get(doc_type, 0)

        ranked.append(
            {
                "filename": doc.get("filename", ""),
                "type": doc_type,
                "group": doc.get("group", ""),
                "score": score,
            }
        )

    ranked.sort(key=lambda item: item["score"], reverse=True)

    return ranked[:5]


def selected_case_summary(documents):
    for doc in documents:
        if doc.get("type") == "selected_case":
            return {
                "title": doc.get("title", ""),
                "court": doc.get("court", ""),
                "date": doc.get("date", ""),
                "citation": doc.get("citation", ""),
                "motion": doc.get("motion", ""),
                "outcome": doc.get("outcome", ""),
                "primary_cause": doc.get("primary_cause", ""),
                "holding": doc.get("holding", ""),
                "rule": doc.get("rule", ""),
                "case_id": doc.get("case_id", ""),
            }

    return None


def build_attorney_work_product(summary, documents):
    return {
        "plaintiff_core_arguments": [],
        "defense_core_arguments": [],
        "strongest_authorities": [],
        "weaknesses": [],
        "drafting_strategy": [],
        "recommended_outline": [],
        "draft_generation": {},
        "citation_exhibit_engine": {},
    }


def build_matter_summary(documents):
    selected = selected_case_summary(documents)

    text = combined_text(documents)

    if selected and selected.get("title"):
        case_name = selected["title"]
    else:
        case_name = extract_case_name(text)

    parties = extract_parties(case_name)

    summary = {
        "case_name": case_name,
        "index_number": extract_index_number(text),
        "plaintiff": parties["plaintiff"],
        "defendant": parties["defendant"],
        "motion_posture": detect_motion_posture(documents, text),
        "procedural_posture": detect_procedural_posture(text),
        "strongest_motion_documents": strongest_motion_documents(documents),
        "selected_case": selected,
    }

    summary["issue_packet"] = build_issue_analysis(
        selected,
        documents,
    )

    summary["contradiction_analysis"] = build_contradiction_analysis(documents)

    summary["attorney_work_product"] = build_attorney_work_product(summary, documents)

    return summary


def get_matter(
    selected_case=None,
    documents=None,
    matter_folder=None,
    inventory_path=None,
    *,
    include_exhibit_segments=False,
):
    resolved_folder = resolve_matter_folder(matter_folder)
    folder_documents = read_matter_folder(
        resolved_folder,
        inventory_path=inventory_path,
    )

    selected_case_document = None

    if isinstance(selected_case, dict):
        selected_case_document = selected_case_to_document(selected_case)

    if documents is None:
        documents = []

    all_documents = []

    if selected_case_document:
        all_documents.append(selected_case_document)

    all_documents.extend(folder_documents)
    all_documents.extend(documents)

    normalized_documents = [
        normalize_document(
            doc,
            include_exhibit_segments=include_exhibit_segments,
        )
        for doc in all_documents
    ]

    grouped_documents = group_documents(normalized_documents)

    summary = build_matter_summary(normalized_documents)

    return {
        "matter_name": summary["case_name"],
        "case_name": summary["case_name"],
        "index_number": summary["index_number"],
        "document_count": len(normalized_documents),
        "documents": normalized_documents,
        "groups": grouped_documents,
        "grouped_documents": grouped_documents,
        "folder": str(resolved_folder),
        "summary": summary,
        "selected_case": summary.get("selected_case"),
        "issue_packet": summary.get("issue_packet", {}),
        "contradiction_analysis": summary.get("contradiction_analysis", {}),
        "attorney_work_product": summary.get("attorney_work_product", {}),
        "draft_generation": summary.get("attorney_work_product", {}).get("draft_generation", {}),
        "citation_exhibit_engine": summary.get("attorney_work_product", {}).get("citation_exhibit_engine", {}),
    }
