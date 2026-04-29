# matter_builder.py
from pathlib import Path
import re

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

try:
    from docx import Document
except Exception:
    Document = None


DEFAULT_MATTER_FOLDER = Path("matter_docs")


DOCUMENT_GROUPS = {
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


def clean_text(value):
    return " ".join(str(value or "").split()).strip()


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


def extract_pdf(path):
    if PdfReader is None:
        return ""

    try:
        reader = PdfReader(str(path))
        pages = []

        for page in reader.pages[:20]:
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text)

        return "\n".join(pages)

    except Exception:
        return ""


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
        doc_type = classify_by_filename(path.name)
        extracted_text = clean_text(extract_text(path))

        documents.append(
            {
                "filename": path.name,
                "title": path.name,
                "path": str(path),
                "relative_path": str(path.relative_to(folder)) if folder.exists() else str(path),
                "folder": str(path.parent),
                "type": doc_type,
                "category": doc_type,
                "group": DOCUMENT_GROUPS.get(doc_type, DOCUMENT_GROUPS["other"]),
                "text": extracted_text,
                "preview": extracted_text[:800],
                "source": "folder",
            }
        )

    return documents


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
    text = clean_text(document.get("text", ""))

    return {
        "filename": filename,
        "title": filename,
        "path": document.get("path", ""),
        "relative_path": document.get("relative_path", document.get("path", "")),
        "folder": document.get("folder", ""),
        "type": doc_type,
        "category": doc_type,
        "group": group,
        "text": text,
        "preview": text[:800],
        "source": document.get("source", "manual"),
    }


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


def get_text_lines(text):
    raw_lines = re.split(r"[\r\n]+", str(text or ""))
    lines = []

    for line in raw_lines:
        cleaned = clean_text(line)
        if cleaned:
            lines.append(cleaned)

    return lines


def is_court_header_line(line):
    lower = line.lower()
    return any(word in lower for word in COURT_HEADER_WORDS)


def extract_index_number(text):
    patterns = [
        r"index\s*(?:no\.?|number)?\s*[:#]?\s*([0-9]{4,8}/[0-9]{4})",
        r"index\s*(?:no\.?|number)?\s*[:#]?\s*([0-9]{5,8})",
        r"idx\s*(?:no\.?)?\s*[:#]?\s*([0-9]{4,8}/[0-9]{4})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return clean_text(match.group(1))

    return "—"


def extract_case_name_from_lines(text):
    lines = get_text_lines(text)

    for line in lines[:80]:
        if is_court_header_line(line):
            continue

        if re.search(r"\bv\.?\b", line, re.IGNORECASE):
            match = re.search(
                r"(.{2,120}?)\s+\bv\.?\b\s+(.{2,120})",
                line,
                re.IGNORECASE,
            )

            if match:
                left = clean_case_party(match.group(1))
                right = clean_case_party(match.group(2))

                if left and right:
                    return f"{left} v. {right}"

        if re.search(r"(?i)-against-| against ", line):
            parts = re.split(r"(?i)-against-| against ", line, maxsplit=1)
            if len(parts) == 2:
                left = clean_case_party(parts[0])
                right = clean_case_party(parts[1])

                if left and right:
                    return f"{left} v. {right}"

    return ""


def extract_case_name(text):
    line_case_name = extract_case_name_from_lines(text)
    if line_case_name:
        return line_case_name

    cleaned = re.sub(
        r"(?i)SUPREME COURT OF THE STATE OF NEW YORK|STATE OF NEW YORK|COUNTY OF [A-Z\s]+",
        " ",
        text,
    )

    patterns = [
        r"([A-Z][A-Za-z0-9&.,'\-\s]{2,80})\s+v\.?\s+([A-Z][A-Za-z0-9&.,'\-\s]{2,80})",
        r"([A-Z][A-Za-z0-9&.,'\-\s]{2,80})\s+against\s+([A-Z][A-Za-z0-9&.,'\-\s]{2,80})",
    ]

    for pattern in patterns:
        match = re.search(pattern, cleaned)
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

    if "answer" in lower and "counterclaim" in lower:
        return "Answer with counterclaims appears to be present."

    if "order" in lower or "decision" in lower:
        return "Prior order or decision appears to be present."

    return "Procedural posture not yet detected from extracted text."


def strongest_motion_documents(documents):
    ranked = []

    weights = {
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

        filename = doc.get("filename", "").lower()

        if "summary judgment" in filename:
            score += 25
        if "motion" in filename:
            score += 15
        if "opposition" in filename:
            score += 15
        if "memo" in filename or "memorandum" in filename:
            score += 10

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


def build_matter_summary(documents):
    text = combined_text(documents)

    case_name = extract_case_name(text)
    parties = extract_parties(case_name)

    return {
        "case_name": case_name,
        "index_number": extract_index_number(text),
        "plaintiff": parties["plaintiff"],
        "defendant": parties["defendant"],
        "motion_posture": detect_motion_posture(documents, text),
        "procedural_posture": detect_procedural_posture(text),
        "strongest_motion_documents": strongest_motion_documents(documents),
    }


def get_matter(documents=None, matter_folder=DEFAULT_MATTER_FOLDER):
    if documents is None:
        documents = read_matter_folder(matter_folder)

    normalized_documents = [normalize_document(doc) for doc in documents]
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
    }