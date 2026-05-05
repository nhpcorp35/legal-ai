from pathlib import Path
import re

DEFAULT_MATTER_FOLDER = Path("matter_docs")
ALLOWED_EXTENSIONS = {".txt"}


def extract_text(path):
    try:
        return path.read_text(errors="ignore")
    except Exception:
        return ""


def read_matter_folder(folder_path=DEFAULT_MATTER_FOLDER):
    folder = Path(folder_path)
    documents = []

    print("LOOKING IN:", folder.resolve())

    if not folder.exists():
        print("FOLDER NOT FOUND")
        return documents

    for path in folder.glob("*"):
        if not path.is_file():
            continue

        if path.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue

        text = extract_text(path)

        print("LOADED:", path.name)
        print("TEXT SAMPLE:", text[:100])

        documents.append({
            "filename": path.name,
            "title": path.name,
            "text": text
        })

    return documents


# =========================
# SAFE CASE EXTRACTION
# =========================

def extract_cases_from_text(text):
    cases = []

    # VERY SAFE patterns (no complex escaping)
    patterns = [
        r"[A-Z][a-z]+ v\. [A-Z][a-z]+ \d+ AD3d \d+",
        r"[A-Z][a-z]+ v\. [A-Z][a-z]+ \d+ NY3d \d+",
        r"[A-Z][a-z]+ v\. [A-Z][a-z]+ \d+ AD2d \d+",
        r"[A-Z][a-z]+ v\. [A-Z][a-z]+ \d+ NY2d \d+",
    ]

    for pattern in patterns:
        try:
            matches = re.findall(pattern, text)
            for m in matches:
                cases.append({
                    "case_name": m,
                    "citation": m,
                    "authority_rank": "real cited authority",
                    "quote": m,
                    "verification_status": "unverified",
                    "relevance_score": 50,
                })
        except Exception as e:
            print("REGEX ERROR:", e)

    return cases


def get_matter(selected_case=None, documents=None, matter_folder=DEFAULT_MATTER_FOLDER):

    if documents is None:
        documents = read_matter_folder(matter_folder)

    all_text = " ".join([d.get("text", "") for d in documents])
    cases = extract_cases_from_text(all_text)

    print("TOTAL TEXT LENGTH:", len(all_text))
    print("CASES FOUND:", cases)

    return {
        "matter_name": "Test Matter",
        "document_count": len(documents),
        "real_authority_layer": {
            "version": "v3.1 SAFE EXTRACTION",
            "jurisdiction": {
                "state": "New York",
                "court": "Supreme Court",
            },
            "issues_detected": [{"issue": "summary judgment", "hits": 1}],
            "authorities": cases,
            "verification_warning": "Verify before use",
        }
    }
