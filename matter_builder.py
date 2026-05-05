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
        print("TEXT SAMPLE:", text[:150])

        documents.append({
            "filename": path.name,
            "title": path.name,
            "text": text,
        })

    return documents


def clean_text(value):
    return " ".join(str(value or "").split()).strip()


def parse_case_citations(text):
    results = []

    patterns = [
        {
            "reporter": "AD3d",
            "regex": r"([A-Z][A-Za-z0-9&.'\- ]+ v\. [A-Z][A-Za-z0-9&.'\- ]+),?\s+(\d+)\s+AD3d\s+(\d+)(?:\s+\(([^)]*)\))?",
        },
        {
            "reporter": "AD2d",
            "regex": r"([A-Z][A-Za-z0-9&.'\- ]+ v\. [A-Z][A-Za-z0-9&.'\- ]+),?\s+(\d+)\s+AD2d\s+(\d+)(?:\s+\(([^)]*)\))?",
        },
        {
            "reporter": "NY3d",
            "regex": r"([A-Z][A-Za-z0-9&.'\- ]+ v\. [A-Z][A-Za-z0-9&.'\- ]+),?\s+(\d+)\s+NY3d\s+(\d+)(?:\s+\(([^)]*)\))?",
        },
        {
            "reporter": "NY2d",
            "regex": r"([A-Z][A-Za-z0-9&.'\- ]+ v\. [A-Z][A-Za-z0-9&.'\- ]+),?\s+(\d+)\s+NY2d\s+(\d+)(?:\s+\(([^)]*)\))?",
        },
        {
            "reporter": "NY Slip Op",
            "regex": r"([A-Z][A-Za-z0-9&.'\- ]+ v\. [A-Z][A-Za-z0-9&.'\- ]+),?\s+(\d{4})\s+NY\s+Slip\s+Op\s+(\d+)(?:\s+\(([^)]*)\))?",
        },
    ]

    for item in patterns:
        reporter = item["reporter"]
        pattern = item["regex"]

        for match in re.finditer(pattern, text):
            case_name = clean_text(match.group(1))
            volume = clean_text(match.group(2))
            page = clean_text(match.group(3))
            parenthetical = clean_text(match.group(4) if len(match.groups()) >= 4 else "")

            court = ""
            year = ""

            if parenthetical:
                year_match = re.search(r"\b(19|20)\d{2}\b", parenthetical)
                if year_match:
                    year = year_match.group(0)

                court = parenthetical.replace(year, "").strip(" ,")

            if reporter == "NY Slip Op":
                citation = f"{volume} NY Slip Op {page}"
            else:
                citation = f"{volume} {reporter} {page}"

            full_citation = f"{case_name}, {citation}"
            if parenthetical:
                full_citation += f" ({parenthetical})"

            results.append({
                "case_name": case_name,
                "citation": citation,
                "full_citation": full_citation,
                "reporter": reporter,
                "volume": volume,
                "page": page,
                "court": court or "Unknown",
                "year": year or "Unknown",
                "authority_rank": rank_authority(reporter, court),
                "quote": full_citation,
                "verification_status": "unverified",
                "verification_notes": "Attorney must verify existence, quote accuracy, and current validity.",
                "relevance_score": score_authority(reporter, court),
            })

    return dedupe_cases(results)


def rank_authority(reporter, court):
    court_lower = clean_text(court).lower()

    if reporter in {"NY3d", "NY2d"}:
        return "controlling"

    if "1st dept" in court_lower or "first dept" in court_lower:
        return "appellate authority"

    if "2d dept" in court_lower or "second dept" in court_lower:
        return "appellate authority"

    if "3d dept" in court_lower or "third dept" in court_lower:
        return "appellate authority"

    if "4th dept" in court_lower or "fourth dept" in court_lower:
        return "appellate authority"

    if reporter in {"AD3d", "AD2d"}:
        return "appellate authority"

    return "cited authority"


def score_authority(reporter, court):
    score = 50

    if reporter in {"NY3d", "NY2d"}:
        score += 35

    if reporter in {"AD3d", "AD2d"}:
        score += 25

    if court and court != "Unknown":
        score += 10

    return min(score, 100)


def dedupe_cases(cases):
    seen = set()
    deduped = []

    for case in cases:
        key = clean_text(f"{case.get('case_name')} {case.get('citation')}").lower()

        if key in seen:
            continue

        seen.add(key)
        deduped.append(case)

    deduped.sort(
        key=lambda item: item.get("relevance_score", 0),
        reverse=True,
    )

    return deduped


def detect_issues(text):
    lower = text.lower()
    issues = []

    if "summary judgment" in lower:
        issues.append({"issue": "summary judgment", "hits": lower.count("summary judgment")})

    if "motion to dismiss" in lower or "cplr 3211" in lower:
        issues.append({"issue": "motion to dismiss", "hits": lower.count("motion to dismiss") + lower.count("cplr 3211")})

    if "mechanics lien" in lower or "mechanic's lien" in lower:
        issues.append({"issue": "mechanics lien", "hits": lower.count("mechanics lien") + lower.count("mechanic's lien")})

    if "lis pendens" in lower or "notice of pendency" in lower:
        issues.append({"issue": "lis pendens / notice of pendency", "hits": lower.count("lis pendens") + lower.count("notice of pendency")})

    if not issues:
        issues.append({"issue": "general legal authority", "hits": 1})

    return issues


def get_matter(selected_case=None, documents=None, matter_folder=DEFAULT_MATTER_FOLDER):
    if documents is None:
        documents = read_matter_folder(matter_folder)

    all_text = " ".join([d.get("text", "") for d in documents])
    authorities = parse_case_citations(all_text)
    issues = detect_issues(all_text)

    print("TOTAL TEXT LENGTH:", len(all_text))
    print("AUTHORITIES FOUND:", authorities)

    return {
        "matter_name": "Test Matter",
        "document_count": len(documents),
        "real_authority_layer": {
            "version": "v3.2 Structured Parser",
            "jurisdiction": {
                "state": "New York",
                "court": "Supreme Court",
            },
            "issues_detected": issues,
            "authorities": authorities,
            "verification_warning": "Structured parser extracted cited authorities. Attorney must verify existence, quotation accuracy, and current validity before filing.",
        }
    }
