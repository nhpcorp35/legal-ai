# matter_builder.py
import re
from pathlib import Path


DOCUMENT_TYPES = [
    "complaint",
    "answer",
    "motion",
    "affirmation",
    "opposition",
    "declaration",
    "exhibit",
    "memorandum_of_law",
    "prior_order",
    "decision",
    "unknown",
]


TYPE_PATTERNS = {
    "complaint": [
        r"\bcomplaint\b",
        r"\bverified complaint\b",
        r"\bsummons and complaint\b",
    ],
    "answer": [
        r"\banswer\b",
        r"\bverified answer\b",
        r"\banswer with counterclaims\b",
    ],
    "motion": [
        r"\bnotice of motion\b",
        r"\bmotion\b",
        r"\bcross[- ]motion\b",
        r"\border to show cause\b",
    ],
    "affirmation": [
        r"\baffirmation\b",
        r"\battorney affirmation\b",
        r"\baffirmation in support\b",
        r"\baffirmation in opposition\b",
    ],
    "opposition": [
        r"\bopposition\b",
        r"\bin opposition\b",
        r"\baffirmation in opposition\b",
        r"\bmemorandum of law in opposition\b",
    ],
    "declaration": [
        r"\bdeclaration\b",
        r"\bdeclaration of\b",
        r"\bdeclarant\b",
    ],
    "exhibit": [
        r"\bexhibit\b",
        r"\bex\.\s*[a-z0-9]+\b",
        r"\bexhibit [a-z0-9]+\b",
    ],
    "memorandum_of_law": [
        r"\bmemorandum of law\b",
        r"\bmem\.\s*of law\b",
        r"\bbrief\b",
        r"\bpoints and authorities\b",
    ],
    "prior_order": [
        r"\bprior order\b",
        r"\border dated\b",
        r"\bso ordered\b",
        r"\bstipulation and order\b",
    ],
    "decision": [
        r"\bdecision and order\b",
        r"\bdecision\b",
        r"\bmemorandum decision\b",
        r"\bthe court held\b",
        r"\badjudged\b",
    ],
}


FILING_LANGUAGE_PATTERNS = {
    "index_number": [
        r"index\s+no\.?\s*[:#]?\s*([0-9]{4,7}/[0-9]{4})",
        r"index\s+number\s*[:#]?\s*([0-9]{4,7}/[0-9]{4})",
    ],
    "caption": [
        r"supreme court of the state of new york",
        r"county of",
        r"plaintiff",
        r"defendant",
    ],
}


def clean_text(value):
    return " ".join(str(value or "").split()).strip()


def normalize(value):
    return clean_text(value).lower()


def score_patterns(text, patterns):
    score = 0
    hits = []

    for pattern in patterns:
        matches = re.findall(pattern, text, flags=re.I)
        if matches:
            score += len(matches)
            hits.append(pattern)

    return score, hits


def extract_index_number(text):
    text = str(text or "")

    for pattern in FILING_LANGUAGE_PATTERNS["index_number"]:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return match.group(1)

    return ""


def has_caption_language(text):
    text = normalize(text)
    return any(
        re.search(pattern, text, flags=re.I)
        for pattern in FILING_LANGUAGE_PATTERNS["caption"]
    )


def classify_document(filename="", title="", text=""):
    filename_text = normalize(Path(filename).name)
    title_text = normalize(title)
    body_text = normalize(text)

    combined = f"{filename_text} {title_text} {body_text}"

    scores = {}
    signals = {}

    for doc_type, patterns in TYPE_PATTERNS.items():
        score, hits = score_patterns(combined, patterns)

        # Title/filename hits matter more than body hits.
        title_score, title_hits = score_patterns(f"{filename_text} {title_text}", patterns)
        score += title_score * 3

        scores[doc_type] = score
        signals[doc_type] = hits + title_hits

    # Tie-break boosts.
    if "opposition" in combined and scores.get("affirmation", 0):
        scores["opposition"] += 2

    if "memorandum of law" in combined:
        scores["memorandum_of_law"] += 4

    if re.search(r"\bexhibit\s+[a-z0-9]+\b", combined, flags=re.I):
        scores["exhibit"] += 4

    if re.search(r"\bnotice of motion\b|\border to show cause\b", combined, flags=re.I):
        scores["motion"] += 4

    if re.search(r"\bdecision and order\b", combined, flags=re.I):
        scores["decision"] += 5

    best_type = max(scores, key=scores.get)
    confidence = scores[best_type]

    if confidence <= 0:
        best_type = "unknown"

    return {
        "filename": filename,
        "title": title or Path(filename).stem,
        "type": best_type,
        "confidence": confidence,
        "index_number": extract_index_number(combined),
        "has_caption": has_caption_language(combined),
        "signals": signals.get(best_type, []),
    }


def classify_documents(documents):
    classified = []

    for doc in documents:
        if isinstance(doc, str):
            result = classify_document(filename=doc)
        else:
            result = classify_document(
                filename=doc.get("filename", ""),
                title=doc.get("title", ""),
                text=doc.get("text", ""),
            )

        classified.append(result)

    return classified


def group_documents(classified_documents):
    grouped = {doc_type: [] for doc_type in DOCUMENT_TYPES}

    for doc in classified_documents:
        doc_type = doc.get("type") or "unknown"
        if doc_type not in grouped:
            doc_type = "unknown"
        grouped[doc_type].append(doc)

    return grouped


def build_matter(documents=None):
    documents = documents or []

    classified = classify_documents(documents)
    grouped = group_documents(classified)

    return {
        "matter_name": "Matter Builder",
        "version": "v2",
        "document_count": len(classified),
        "documents": classified,
        "groups": grouped,
    }


def get_matter(documents=None):
    return build_matter(documents)