# matter_builder.py

import os
import re

print("LOADED MATTER BUILDER FROM:", __file__)
print("LOOKING IN:", os.getcwd())


def clean_text(value):
    return " ".join(str(value or "").split()).strip()


def safe_lower(value):
    return clean_text(value).lower()


FULL_CITATION_REGEX = re.compile(
    r'([A-Z][A-Za-z0-9&.,\'"\-\s]+?\s+v\.?\s+[A-Z][A-Za-z0-9&.,\'"\-\s]+?)'
    r'\s*,?\s+'
    r'([0-9]{1,4}\s+(?:AD3d|AD2d|NY3d|NY2d|Misc\s?3d|Misc\s?2d|F3d|F2d|US)\s+[0-9]{1,5})'
    r'\s*\(([^)]*)\)',
    re.IGNORECASE | re.MULTILINE | re.DOTALL
)


AUTHORITY_TERMS = [
    "held",
    "held that",
    "found",
    "ruled",
    "stated",
    "reasoned",
    "summary judgment",
    "prima facie",
    "motion",
    "burden",
    "standard",
]


PLAINTIFF_TERMS = [
    "plaintiff",
    "petitioner",
    "movant",
    "claimant",
]


DEFENDANT_TERMS = [
    "defendant",
    "respondent",
    "opponent",
]


ISSUE_SIGNALS = {
    "summary judgment": ["summary judgment", "prima facie"],
    "motion practice": ["motion", "opposition", "oppose"],
    "burden of proof": ["burden", "prima facie"],
}


TEXT_FIELDS = [
    "title",
    "case_name",
    "caption",
    "citation",
    "court",
    "date",
    "motion",
    "outcome",
    "rule",
    "holding",
    "reasoning",
    "summary",
    "facts",
    "procedural_history",
    "text",
    "content",
    "body",
]


def normalize_text_for_parser(text):
    text = str(text or "")
    text = text.replace("\r", "\n")
    text = re.sub(r"\n+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def split_sentences(text):
    text = normalize_text_for_parser(text)
    parts = re.split(r'(?<=[.!?])\s+', text)

    sentences = []

    for part in parts:
        part = clean_text(part)

        if len(part) >= 10:
            sentences.append(part)

    return sentences


def detect_side(sentence):
    lower = safe_lower(sentence)

    for term in PLAINTIFF_TERMS:
        if term in lower:
            return "plaintiff"

    for term in DEFENDANT_TERMS:
        if term in lower:
            return "defendant"

    return "neutral"


def detect_jurisdiction(text):
    lower = safe_lower(text)

    state = "Unknown"
    court = "Unknown"

    if "new york" in lower or "ny3d" in lower or "ad3d" in lower or "ad2d" in lower:
        state = "New York"

    if "supreme court of the state of new york" in lower:
        court = "Supreme Court"
    elif "1st dept" in lower:
        court = "Appellate Division, First Department"
    elif "2d dept" in lower:
        court = "Appellate Division, Second Department"

    return {
        "state": state,
        "court": court,
    }


def detect_issues(text):
    lower = safe_lower(text)
    issues = []

    for issue_name, signals in ISSUE_SIGNALS.items():
        hits = 0

        for signal in signals:
            if signal in lower:
                hits += 1

        if hits > 0:
            issues.append(
                {
                    "issue": issue_name,
                    "hits": hits,
                }
            )

    return issues


def score_authority(sentence):
    lower = safe_lower(sentence)

    score = 0

    if " v. " in lower:
        score += 20

    if "held that" in lower:
        score += 20

    if "held" in lower:
        score += 12

    if "summary judgment" in lower:
        score += 12

    if "prima facie" in lower:
        score += 10

    for term in AUTHORITY_TERMS:
        if term in lower:
            score += 3

    if "plaintiff relies" in lower:
        score += 6

    if "defendant cites" in lower:
        score += 6

    return score


def classify_used_for(sentence):
    lower = safe_lower(sentence)

    if "summary judgment" in lower:
        return "summary judgment standard"

    if "prima facie" in lower:
        return "prima facie burden"

    if "oppose" in lower or "opposition" in lower:
        return "opposition argument"

    if "motion" in lower:
        return "motion practice"

    return "general authority"


def find_sentence_for_match(sentences, case_name, citation):
    case_key = safe_lower(case_name)
    cite_key = safe_lower(citation)

    for sentence in sentences:
        lower = safe_lower(sentence)

        if case_key in lower and cite_key in lower:
            return sentence

    for sentence in sentences:
        lower = safe_lower(sentence)

        if case_key in lower:
            return sentence

    return ""


def clean_case_name(case_name):
    case_name = clean_text(case_name)

    markers = [
        "plaintiff relies on ",
        "defendant cites ",
        "the court in ",
        "court in ",
        "relies on ",
        "cites ",
    ]

    lower = case_name.lower()

    for marker in markers:
        idx = lower.rfind(marker)

        if idx != -1:
            case_name = case_name[idx + len(marker):]
            break

    case_name = clean_text(case_name)

    match = re.search(
        r'([A-Z][A-Za-z0-9&.,\'"\-\s]+?\s+v\.?\s+[A-Z][A-Za-z0-9&.,\'"\-\s]+)$',
        case_name
    )

    if match:
        case_name = clean_text(match.group(1))

    return case_name


def build_full_citation(case_name, citation, court_year):
    parts = []

    if case_name:
        parts.append(case_name)

    if citation:
        parts.append(citation)

    full = ", ".join(parts)

    if court_year:
        full = f"{full} ({court_year})"

    return clean_text(full)


def extract_authorities(text):
    normalized = normalize_text_for_parser(text)
    sentences = split_sentences(normalized)

    authorities = []

    for match in FULL_CITATION_REGEX.finditer(normalized):
        raw_case_name = match.group(1)
        citation = match.group(2)
        court_year = match.group(3)

        case_name = clean_case_name(raw_case_name)
        citation = clean_text(citation)
        court_year = clean_text(court_year)

        sentence = find_sentence_for_match(
            sentences,
            case_name,
            citation,
        )

        if not sentence:
            sentence = clean_text(match.group(0))

        relevance_score = score_authority(sentence)

        authority = {
            "case_name": case_name,
            "citation": citation,
            "court_year": court_year,
            "full_citation": build_full_citation(case_name, citation, court_year),
            "sentence": sentence,
            "context": sentence,
            "side": detect_side(sentence),
            "used_for": classify_used_for(sentence),
            "score": relevance_score,
            "relevance_score": relevance_score,
            "verification_status": "parser extracted citation; human verification required",
            "authority_rank": "unranked",
        }

        authorities.append(authority)

    return dedupe_authorities(authorities)


def dedupe_authorities(authorities):
    seen = set()
    final = []

    for auth in authorities:
        key = (
            safe_lower(auth.get("case_name", "")),
            safe_lower(auth.get("citation", "")),
        )

        if key in seen:
            continue

        seen.add(key)
        final.append(auth)

    return final


def sort_authorities(authorities):
    return sorted(
        authorities,
        key=lambda x: (
            x.get("relevance_score", 0),
            x.get("case_name", ""),
        ),
        reverse=True,
    )


def rank_authorities(authorities):
    ranked = []

    for idx, auth in enumerate(authorities, start=1):
        item = dict(auth)
        item["authority_rank"] = f"Rank #{idx}"
        ranked.append(item)

    return ranked


def build_authority_engine(text):
    text = normalize_text_for_parser(text)

    authorities = extract_authorities(text)
    authorities = sort_authorities(authorities)
    authorities = rank_authorities(authorities)

    return {
        "version": "Authority Engine v3.3",
        "verification_warning": "Draft research aid only. Verify citations, holdings, procedural posture, and treatment before use.",
        "jurisdiction": detect_jurisdiction(text),
        "issues_detected": detect_issues(text),
        "authorities": authorities,
        "authority_count": len(authorities),
    }


def extract_text_from_dict(data):
    chunks = []

    for field in TEXT_FIELDS:
        value = data.get(field)

        if value:
            chunks.append(f"{field}: {value}")

    for key, value in data.items():
        if key in TEXT_FIELDS:
            continue

        if isinstance(value, str) and len(value.strip()) > 20:
            chunks.append(f"{key}: {value}")

    return "\n\n".join(chunks)


def build_combined_text(input_data):
    if input_data is None:
        return ""

    if isinstance(input_data, dict):
        return extract_text_from_dict(input_data)

    if isinstance(input_data, list):
        chunks = []

        for item in input_data:
            if isinstance(item, dict):
                chunks.append(extract_text_from_dict(item))
            else:
                chunks.append(str(item))

        return "\n\n".join(chunks)

    return str(input_data)


def get_matter(documents=None):
    combined_text = build_combined_text(documents)
    combined_text = normalize_text_for_parser(combined_text)

    print("TEXT SAMPLE:", combined_text[:500])

    real_authority_layer = build_authority_engine(combined_text)
    authorities = real_authority_layer.get("authorities", [])

    print("AUTHORITIES RETURNED:", len(authorities))

    return {
        "authorities": authorities,
        "real_authority_layer": real_authority_layer,
        "authority_count": len(authorities),
        "document_count": 1 if combined_text else 0,
        "preview": combined_text[:1000],
    }


if __name__ == "__main__":
    sample = """
    SUPREME COURT OF THE STATE OF NEW YORK

    JOHN SMITH v. ABC CORP

    Index No. 123456/2024

    This is a motion for summary judgment.

    Plaintiff relies on Smith v. Jones, 123 AD3d 456 (1st Dept 2020) to argue that summary judgment should be granted.

    Defendant cites Brown v. City of New York, 95 AD3d 1051 (2d Dept 2012) to oppose the motion.

    The Court in Johnson v. Smith, 12 NY3d 345 (2009) held that summary judgment requires a prima facie showing.
    """

    result = get_matter([{"content": sample}])

    print("\n========== AUTHORITY LAYER ==========\n")
    print("VERSION:", result["real_authority_layer"]["version"])
    print("STATE:", result["real_authority_layer"]["jurisdiction"]["state"])
    print("COURT:", result["real_authority_layer"]["jurisdiction"]["court"])
    print("ISSUES:", result["real_authority_layer"]["issues_detected"])

    print("\n========== AUTHORITIES ==========\n")

    for auth in result["authorities"]:
        print("RANK:", auth["authority_rank"])
        print("CASE:", auth["case_name"])
        print("CITATION:", auth["citation"])
        print("FULL:", auth["full_citation"])
        print("SIDE:", auth["side"])
        print("USED FOR:", auth["used_for"])
        print("SCORE:", auth["relevance_score"])
        print("CONTEXT:", auth["context"])
        print("VERIFY:", auth["verification_status"])
        print("-" * 60)