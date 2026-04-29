# matter_builder.py
from pathlib import Path


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


def extract_text_placeholder(path):
    suffix = path.suffix.lower()

    if suffix == ".txt":
        try:
            return path.read_text(errors="ignore")
        except Exception:
            return ""

    return ""


def read_matter_folder(folder_path=DEFAULT_MATTER_FOLDER):
    folder = Path(folder_path)

    if not folder.exists() or not folder.is_dir():
        return []

    allowed_extensions = {".pdf", ".docx", ".doc", ".txt", ".rtf"}

    documents = []

    for path in sorted(folder.iterdir()):
        if not path.is_file():
            continue

        if path.suffix.lower() not in allowed_extensions:
            continue

        doc_type = classify_by_filename(path.name)

        documents.append(
            {
                "filename": path.name,
                "title": path.name,
                "path": str(path),
                "type": doc_type,
                "category": doc_type,
                "group": DOCUMENT_GROUPS.get(doc_type, DOCUMENT_GROUPS["other"]),
                "text": clean_text(extract_text_placeholder(path)),
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

    doc_type = document.get("type") or document.get("category") or classify_by_filename(filename)
    group = DOCUMENT_GROUPS.get(doc_type, DOCUMENT_GROUPS["other"])

    return {
        "filename": filename,
        "title": filename,
        "path": document.get("path", ""),
        "type": doc_type,
        "category": doc_type,
        "group": group,
        "text": clean_text(document.get("text", "")),
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

        # v2.2 compatibility for matter.html
        "groups": grouped_documents,
        "grouped_documents": grouped_documents,

        "folder": str(matter_folder),
    }