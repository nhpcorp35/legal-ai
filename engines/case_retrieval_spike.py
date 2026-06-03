import json
import os
import re

DEFAULT_CASE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data",
    "output_v4.json",
)

SKIP_LINE_MARKERS = (
    "index no",
    "case no",
    "llp",
    "counsel",
    "order,",
    "unanimously",
    "entered on",
    "appellate division",
)


def _clean_text(value):
    if not value:
        return ""

    return re.sub(r"\s+", " ", str(value)).strip()


def _looks_like_bad_case_name(name):
    if not name:
        return True

    lowered = name.lower()

    if lowered.startswith("supreme court of the state"):
        return True

    if lowered.startswith("appellate division"):
        return True

    if " v. " not in lowered and len(lowered) > 80:
        return True

    return False


def _extract_case_name(row):
    title = _clean_text(row.get("title") or row.get("name", ""))

    if title and not _looks_like_bad_case_name(title):
        return title

    text = row.get("text", "")
    lines = [_clean_text(line) for line in text.splitlines() if _clean_text(line)]

    plaintiff = ""
    defendant = ""
    saw_against = False

    for i, line in enumerate(lines[:35]):
        lowered = line.lower()

        if lowered in {"-against-", "against"}:
            saw_against = True
            continue

        if "plaintiff" in lowered and not plaintiff and i > 0:
            name = re.sub(r"^\d+\s+", "", lines[i - 1])
            name = name.split(",")[0].strip()

            if name and len(name) > 2:
                plaintiff = name
            continue

        if saw_against and not defendant and "defendant" not in lowered:
            if any(marker in lowered for marker in SKIP_LINE_MARKERS):
                continue

            name = re.sub(r"^\d+\s+", "", line).split(",")[0].strip()

            if name and len(name) > 2:
                defendant = name
            continue

        if "defendant" in lowered and defendant:
            break

    if plaintiff and defendant:
        return f"{plaintiff} v. {defendant}"

    case_number = row.get("case_number")
    if case_number:
        return f"Case {case_number}"

    return ""


def retrieve_matching_cases(terms, limit=5):
    terms = [str(term).lower() for term in (terms or []) if term]

    if not terms:
        return []

    if not os.path.exists(DEFAULT_CASE_PATH):
        return []

    with open(DEFAULT_CASE_PATH, encoding="utf-8") as handle:
        rows = json.load(handle)

    matches = []

    for row in rows:
        haystack = " ".join(
            [
                str(row.get("title", "")),
                str(row.get("name", "")),
                str(row.get("text", "")),
                str(row.get("snippet", "")),
            ]
        ).lower()

        matched_term = next(
            (term for term in terms if term in haystack),
            "",
        )

        if not matched_term:
            continue

        case_name = _extract_case_name(row)

        if _looks_like_bad_case_name(case_name):
            continue

        matches.append(
            {
                "case_name": case_name,
                "reason": matched_term,
            }
        )

        if len(matches) >= limit:
            break

    return matches
