# matter_builder.py
from pathlib import Path

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
    "other": "Other Documents",
}


def clean_text(value):
    return " ".join(str(value or "").split()).strip()


def classify_by_filename(filename):
    name = filename.lower()

    if "complaint" in name:
        return "complaint"

    if "answer" in name:
        return "answer"

    if "notice of motion" in name or "motion" in name:
        return "motion"

    if "affirmation" in name or "affidavit" in name:
        return "affirmation"

    if "opposition" in name or "opp" in name:
        return "opposition"

    if "reply" in name:
        return "reply"

    if "exhibit" in name or "exh" in name:
        return "exhibit"

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


def read_matter_folder(folder_path=DEFAULT_MATTER_FOLDER):
    folder = Path(folder_path)

    if not folder.exists() or not folder.is_dir():
        return []

    allowed_extensions = {
        ".pdf",
        ".docx",
        ".doc",
        ".txt",
        ".rtf",
    }

    documents = []

    for path in sorted(folder.iterdir()):
        if not path.is_file():
            continue

        if path.suffix.lower() not in allowed_extensions:
            continue

        doc_type = classify_by_filename(path.name)
        extracted_text = clean_text(extract_text(path))

        documents.append(
            {
                "filename": path.name,
                "title": path.name,
                "path": str(path),
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


def get_matter(documents=None, matter_folder=DEFAULT_MATTER_FOLDER):
    if documents is None:
        documents = read_matter_folder(matter_folder)

    normalized_documents = [normalize_document(doc) for doc in documents]
    grouped_documents = group_documents(normalized_documents)

    return {
        "matter_name": "Matter Builder",
        "document_count": len(normalized_documents),
        "documents": normalized_documents,
        "groups": grouped_documents,
        "grouped_documents": grouped_documents,
        "folder": str(matter_folder),
    }