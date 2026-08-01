# matter_builder.py
from pathlib import Path
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

# Used only for deterministic page_id formatting when no verified NYSCEF
# document number is available. Never invents a provenance document number.
UNKNOWN_NYSCEF_DOCUMENT_NUMBER = 0

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


def extract_pdf_document(path, nyscef_document_number=None):
    """
    Extract every physical PDF page with per-page OCR fallback.

    Returns text, pages, page_count, and nyscef_document_number.
    """
    path = Path(path)

    if nyscef_document_number is None:
        nyscef_document_number = parse_nyscef_document_number_from_filename(path.name)
    else:
        nyscef_document_number = coerce_nyscef_document_number(nyscef_document_number)

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


def read_matter_folder(folder_path=DEFAULT_MATTER_FOLDER):
    folder = Path(folder_path)
    files = find_matter_files(folder)

    documents = []

    for path in files:
        print(f"\nPROCESSING FILE: {path.name}")

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
            pdf_doc = extract_pdf_document(path)
            extracted_text = pdf_doc["text"]
            document["text"] = extracted_text
            document["preview"] = extracted_text[:800]
            document["pages"] = pdf_doc["pages"]
            document["page_count"] = pdf_doc["page_count"]
            document["nyscef_document_number"] = pdf_doc["nyscef_document_number"]
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


def normalize_document(document):
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


def get_matter(selected_case=None, documents=None, matter_folder=DEFAULT_MATTER_FOLDER):
    folder_documents = read_matter_folder(matter_folder)

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

    normalized_documents = [normalize_document(doc) for doc in all_documents]

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
        "folder": str(matter_folder),
        "summary": summary,
        "selected_case": summary.get("selected_case"),
        "issue_packet": summary.get("issue_packet", {}),
        "contradiction_analysis": summary.get("contradiction_analysis", {}),
        "attorney_work_product": summary.get("attorney_work_product", {}),
        "draft_generation": summary.get("attorney_work_product", {}).get("draft_generation", {}),
        "citation_exhibit_engine": summary.get("attorney_work_product", {}).get("citation_exhibit_engine", {}),
    }
