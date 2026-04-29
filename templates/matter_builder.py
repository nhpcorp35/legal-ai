import os
import re
from types import SimpleNamespace


DOCUMENT_GROUPS = [
    ("complaint", "Complaint"),
    ("answer", "Answer"),
    ("motions", "Motions"),
    ("affirmations", "Affirmations"),
    ("oppositions", "Oppositions"),
    ("declarations", "Declarations"),
    ("exhibits", "Exhibits"),
    ("memorandum_of_law", "Memorandum of Law"),
    ("prior_orders", "Prior Orders"),
    ("decisions", "Decisions"),
]


GROUP_KEYWORDS = {
    "complaint": [
        "complaint",
        "verified complaint",
        "amended complaint",
    ],
    "answer": [
        "answer",
        "verified answer",
        "amended answer",
    ],
    "motions": [
        "notice of motion",
        "motion",
        "cross-motion",
        "cross motion",
        "order to show cause",
    ],
    "affirmations": [
        "affirmation",
        "attorney affirmation",
        "affirmation in support",
        "affirmation in opposition",
        "reply affirmation",
    ],
    "oppositions": [
        "opposition",
        "affirmation in opposition",
        "memorandum in opposition",
        "opposing",
    ],
    "declarations": [
        "declaration",
        "affidavit",
        "affidavit in support",
        "affidavit in opposition",
    ],
    "exhibits": [
        "exhibit",
        "exh.",
        "exhibit a",
        "exhibit b",
        "exhibit c",
    ],
    "memorandum_of_law": [
        "memorandum of law",
        "memo of law",
        "memorandum in support",
        "memorandum in opposition",
        "reply memorandum",
    ],
    "prior_orders": [
        "order",
        "prior order",
        "decision and order",
        "so ordered",
    ],
    "decisions": [
        "decision",
        "decision and order",
        "opinion",
        "judgment",
    ],
}


def clean_text(value):
    return " ".join(str(value or "").split()).strip()


def normalize_text(value):
    value = str(value or "").lower()
    value = value.replace("_", " ")
    value = value.replace("-", " ")
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def normalize_index_number(value):
    raw = clean_text(value)
    if not raw:
        return ""

    match = re.search(r"\b\d{5,7}\s*/\s*\d{4}\b", raw)
    if match:
        return re.sub(r"\s+", "", match.group(0))

    match = re.search(r"\b\d{5,7}\s+\d{4}\b", raw)
    if match:
        return match.group(0).replace(" ", "/")

    return ""


def looks_like_index_number(value):
    return bool(normalize_index_number(value))


def document_title_from_filename(filename):
    name = os.path.basename(clean_text(filename))
    if not name:
        return "Untitled Document"

    name = re.sub(r"\.[A-Za-z0-9]{2,6}$", "", name)
    name = name.replace("_", " ").replace("-", " ")
    name = re.sub(r"\s+", " ", name).strip()
    return name or "Untitled Document"


def infer_document_group(document):
    haystack = normalize_text(" ".join([
        document.get("title", ""),
        document.get("filename", ""),
        document.get("description", ""),
        document.get("text", "")[:1200],
    ]))

    if not haystack:
        return "motions"

    ordered_groups = [
        "memorandum_of_law",
        "oppositions",
        "affirmations",
        "declarations",
        "complaint",
        "answer",
        "exhibits",
        "prior_orders",
        "decisions",
        "motions",
    ]

    for group in ordered_groups:
        keywords = GROUP_KEYWORDS.get(group, [])
        if any(normalize_text(keyword) in haystack for keyword in keywords):
            return group

    return "motions"


def empty_groups():
    return {key: [] for key, _label in DOCUMENT_GROUPS}


def make_document(title="", filename="", description="", source="", date=""):
    title = clean_text(title) or document_title_from_filename(filename)
    filename = clean_text(filename)

    document = {
        "title": title,
        "filename": filename,
        "description": clean_text(description),
        "source": clean_text(source),
        "date": clean_text(date),
        "group": "",
    }
    document["group"] = infer_document_group(document)
    return document


def group_documents(documents):
    groups = empty_groups()

    for document in documents or []:
        doc = dict(document)
        group = doc.get("group") or infer_document_group(doc)
        if group not in groups:
            group = "motions"
        doc["group"] = group
        groups[group].append(doc)

    return groups


def build_empty_matter(query=""):
    query = clean_text(query)
    index_number = normalize_index_number(query)

    return SimpleNamespace(
        query=query,
        searched=bool(query),
        title="Matter Builder",
        matter_name="" if looks_like_index_number(query) else query,
        index_number=index_number,
        court="",
        judge="",
        status="Draft Matter Page",
        document_groups=DOCUMENT_GROUPS,
        groups=empty_groups(),
        total_documents=0,
        message="Enter an index number or case name to start building the matter page.",
    )


def build_matter(query="", documents=None):
    """
    Matter Builder v1 foundation.

    Current scope:
    - accepts index number or case name
    - creates one stable matter object
    - groups supplied documents by legal filing type
    - keeps ingestion logic out of app.py

    Later scope:
    - scan local matter folders
    - ingest PDFs / OCR text
    - match filings by index number or caption
    - sort documents chronologically
    """

    matter = build_empty_matter(query)
    grouped = group_documents(documents or [])
    matter.groups = grouped
    matter.total_documents = sum(len(items) for items in grouped.values())

    if matter.searched:
        if matter.index_number:
            matter.title = f"Matter: {matter.index_number}"
            matter.message = "Matter shell created from index number. Document ingestion is the next step."
        else:
            matter.title = f"Matter: {matter.matter_name}"
            matter.message = "Matter shell created from case name. Document ingestion is the next step."

    return matter
