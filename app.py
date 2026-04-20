from flask import Flask, request, render_template
import json
import math
import os
import csv
import re
from types import SimpleNamespace

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PREFERRED_JSON_PATHS = [
    os.path.join(BASE_DIR, "data", "output_v4.json"),
    os.path.join(BASE_DIR, "data", "output_v3.json"),
    os.path.join(BASE_DIR, "output_v1.json"),
]

PREFERRED_CSV_PATHS = [
    os.path.join(BASE_DIR, "data", "output_v3.csv"),
]

PER_PAGE = 10


# =========================
# HELPERS
# =========================

def clean_text(value):
    return " ".join(str(value or "").split()).strip()


def normalize_for_search(value):
    value = str(value or "").lower()
    value = value.replace("§", " section ")
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def build_pager(page, per_page, total_count):
    total_pages = max(1, math.ceil(total_count / per_page)) if total_count else 1

    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages

    return SimpleNamespace(
        page=page,
        per_page=per_page,
        total=total_count,
        total_pages=total_pages,
        has_prev=page > 1,
        has_next=page < total_pages,
        prev_num=page - 1 if page > 1 else None,
        next_num=page + 1 if page < total_pages else None,
    )


def flatten_citation(case):
    direct = clean_text(
        case.get("citation")
        or case.get("cite")
        or case.get("reporter_citation")
        or case.get("slip_op")
        or case.get("slip_op_citation")
    )
    if direct:
        return direct

    citations = case.get("citations")
    if isinstance(citations, dict):
        slip_ops = citations.get("slip_op") or []
        reporters = citations.get("reporters") or []

        if isinstance(slip_ops, list) and slip_ops:
            first_slip = clean_text(slip_ops[0])
            if first_slip:
                return first_slip

        if isinstance(reporters, list) and reporters:
            first_reporter = clean_text(reporters[0])
            if first_reporter:
                return first_reporter

    return ""


def looks_like_bad_title(line):
    if not line:
        return True

    low = line.lower().strip()

    junk_phrases = [
        "appellate division",
        "first judicial department",
        "motion no",
        "index no",
        "case no",
        "order,",
        "entered ",
        "entered on",
        "unanimously",
        "appealed from",
        "to the extent appealed",
        "plaintiff-appellant",
        "defendant-appellant",
        "petitioner-respondent",
        "respondent-appellant",
        "plaintiff-respondent",
        "defendant-respondent",
    ]
    if any(p in low for p in junk_phrases):
        return True

    fragment_starts = [
        "to dismiss",
        "against him",
        "against her",
        "against it",
        "motion as sought",
        "motion pursuant",
        "which granted",
        "which denied",
        "which, to the extent",
        "s motion",
        "cross motion",
    ]
    if any(low.startswith(p) for p in fragment_starts):
        return True

    if len(line) < 12:
        return True
    if len(line) > 140:
        return True

    words = line.split()
    if len(words) < 3:
        return True

    lowercase_words = sum(1 for w in words if w[:1].islower())
    if lowercase_words >= max(2, len(words) // 2):
        return True

    return False


def extract_caption_from_text(text):
    if not text:
        return ""

    raw = str(text)
    lines = [clean_text(line) for line in raw.splitlines() if clean_text(line)]
    if not lines:
        return ""

    joined = " ".join(lines[:30])

    patterns = [
        r"([A-Z][A-Za-z0-9&'.,\- ]+ v\. [A-Z][A-Za-z0-9&'.,\- ]+)",
        r"([A-Z][A-Za-z0-9&'.,\- ]+ against [A-Z][A-Za-z0-9&'.,\- ]+)",
        r"(In the Matter of [A-Z][A-Za-z0-9&'.,\- ]+)",
    ]

    for pat in patterns:
        m = re.search(pat, joined, re.IGNORECASE)
        if m:
            candidate = clean_text(m.group(1))
            if not looks_like_bad_title(candidate):
                return candidate

    for line in lines[:12]:
        if looks_like_bad_title(line):
            continue
        if re.search(r"[A-Za-z]", line):
            return line

    return ""


def build_safe_title(case):
    direct_title = clean_text(case.get("title"))
    if direct_title and direct_title.lower() not in {"untitled case", "case record"}:
        if not looks_like_bad_title(direct_title):
            return direct_title

    caption = extract_caption_from_text(case.get("text", ""))
    if caption:
        return caption

    case_number = clean_text(case.get("case_number") or case.get("docket"))
    court = clean_text(case.get("court"))
    date = clean_text(case.get("date"))

    if case_number and court and date:
        return f"Case {case_number} ({court}, {date})"
    if case_number and court:
        return f"Case {case_number} ({court})"
    if case_number:
        return f"Case {case_number}"

    return "Case Record"


def detect_record_type(case):
    file_name = clean_text(case.get("file")).lower()
    text = normalize_for_search(" ".join([
        case.get("title", ""),
        case.get("summary", ""),
        case.get("snippet", ""),
        case.get("text", "")[:1200],
    ]))

    if "__motion_order__" in file_name:
        return "motion_order"

    if "motion no" in text and "case no" in text and "index no" in text:
        return "motion_order"

    return "decision"


# =========================
# LOADERS
# =========================

def load_json_cases(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ["cases", "results", "data", "records"]:
            value = data.get(key)
            if isinstance(value, list):
                return value

    return []


def load_csv_cases(path):
    rows = []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    return rows


def load_cases():
    for path in PREFERRED_JSON_PATHS:
        if os.path.exists(path):
            rows = load_json_cases(path)
            if rows:
                print(f"✅ Loaded {len(rows)} cases from {path}")
                return [normalize_case(r) for r in rows]

    for path in PREFERRED_CSV_PATHS:
        if os.path.exists(path):
            rows = load_csv_cases(path)
            if rows:
                print(f"⚠️ Loaded CSV fallback {len(rows)} rows from {path}")
                return [normalize_case(r) for r in rows]

    print("⚠️ No data found")
    return []


# =========================
# PHRASE ALIASES / DETECTION
# =========================

PHRASE_ALIASES = {
    "labor law": [
        "labor law",
        "labor law 200",
        "labor law 240",
        "labor law 241",
        "labor law section 200",
        "labor law section 240",
        "labor law section 241",
        "scaffold law",
    ],
    "breach of contract": [
        "breach of contract",
        "material breach",
        "written agreement",
        "oral agreement",
        "contractual breach",
    ],
    "contract": [
        "breach of contract",
        "contract",
        "agreement",
        "material breach",
        "written agreement",
        "oral agreement",
    ],
    "summary judgment": [
        "summary judgment",
        "partial summary judgment",
    ],
    "motion to dismiss": [
        "motion to dismiss",
        "dismissal",
        "dismiss",
    ],
    "negligence": [
        "negligence",
        "negligent",
        "duty of care",
        "breach of duty",
        "proximate cause",
    ],
    "fraud": [
        "fraud",
        "fraudulent",
        "misrepresentation",
        "fraudulent inducement",
        "concealment",
    ],
    "conversion": [
        "conversion",
        "dominion and control",
        "wrongful possession",
        "unauthorized control",
    ],
}

STRICT_PHRASE_QUERIES = set(PHRASE_ALIASES.keys())


def detect_motion(case):
    text = normalize_for_search(" ".join([
        case.get("title", ""),
        case.get("summary", ""),
        case.get("snippet", ""),
        case.get("text", ""),
    ]))

    if "partial summary judgment" in text:
        return "partial summary judgment"
    if "summary judgment" in text:
        return "summary judgment"
    if "motion to dismiss" in text:
        return "motion to dismiss"
    if "dismiss" in text:
        return "dismissal"
    return ""


def detect_primary_cause(case):
    text = normalize_for_search(" ".join([
        case.get("title", ""),
        case.get("summary", ""),
        case.get("snippet", ""),
        case.get("text", ""),
    ]))

    if any(alias in text for alias in PHRASE_ALIASES["labor law"]):
        return "labor law"
    if any(alias in text for alias in PHRASE_ALIASES["breach of contract"]):
        return "breach of contract"
    if any(alias in text for alias in PHRASE_ALIASES["fraud"]):
        return "fraud"
    if any(alias in text for alias in PHRASE_ALIASES["conversion"]):
        return "conversion"
    if any(alias in text for alias in PHRASE_ALIASES["negligence"]):
        return "negligence"

    return ""


# =========================
# NORMALIZE
# =========================

def normalize_case(case):
    case = dict(case)

    case["court"] = clean_text(case.get("court"))
    case["summary"] = clean_text(case.get("summary"))
    case["snippet"] = clean_text(case.get("snippet"))
    case["outcome"] = clean_text(case.get("outcome")).lower()
    case["citation"] = flatten_citation(case)
    case["docket"] = clean_text(case.get("case_number") or case.get("docket"))
    case["case_number"] = clean_text(case.get("case_number"))
    case["date"] = clean_text(case.get("date"))
    case["text"] = clean_text(case.get("text"))
    case["file"] = clean_text(case.get("file"))
    case["record_type"] = detect_record_type(case)
    case["motion"] = detect_motion(case)
    case["primary_cause"] = detect_primary_cause(case)
    case["title"] = build_safe_title(case)

    return case


# =========================
# SEARCH
# =========================

def text_for_search(case):
    return normalize_for_search(" ".join([
        case.get("title", ""),
        case.get("summary", ""),
        case.get("snippet", ""),
        case.get("text", ""),
        case.get("court", ""),
        case.get("citation", ""),
        case.get("docket", ""),
        case.get("date", ""),
        case.get("outcome", ""),
        case.get("motion", ""),
        case.get("primary_cause", ""),
        case.get("record_type", ""),
    ]))


def best_snippet(case, query):
    snippet = clean_text(case.get("snippet"))
    text = clean_text(case.get("text"))

    if not query:
        if snippet:
            return snippet[:900]
        return text[:900]

    hay_query = normalize_for_search(query)
    terms = [t for t in hay_query.split() if t]

    if text:
        paragraphs = [clean_text(p) for p in re.split(r"[\n\r]+", text) if clean_text(p)]
        if not paragraphs:
            paragraphs = [text]

        best_para = ""
        best_score = -1

        for para in paragraphs:
            pl = normalize_for_search(para)
            score = 0

            if hay_query and hay_query in pl:
                score += 10

            for term in terms:
                if term in pl:
                    score += 2

            if score > best_score:
                best_score = score
                best_para = para

        if best_para and best_score > 0:
            return best_para[:900]

    if snippet:
        return snippet[:900]

    return text[:900]


def query_aliases(query):
    q = normalize_for_search(query)
    if q in PHRASE_ALIASES:
        return PHRASE_ALIASES[q]
    return [q] if q else []


def matches_query(case, query):
    if not query:
        return True

    haystack = text_for_search(case)
    q = normalize_for_search(query)

    if not q:
        return True

    aliases = query_aliases(query)

    if q in STRICT_PHRASE_QUERIES:
        return any(alias in haystack for alias in aliases)

    if q in haystack:
        return True

    terms = [t for t in q.split() if t]

    if len(terms) == 1:
        return terms[0] in haystack

    return all(term in haystack for term in terms)


def matches_filters(case, selected_court, selected_outcome):
    if selected_court != "All Courts":
        if case.get("court") != selected_court:
            return False

    if selected_outcome != "All Outcomes":
        if case.get("outcome", "").lower() != selected_outcome.lower():
            return False

    return True


# =========================
# RANKING
# =========================

def score_case(case, query):
    score = 0
    haystack = text_for_search(case)
    q = normalize_for_search(query)

    aliases = query_aliases(query)

    if q in STRICT_PHRASE_QUERIES:
        alias_hits = sum(1 for alias in aliases if alias in haystack)
        if alias_hits:
            score += 18 + (alias_hits * 2)
    else:
        if q and q in haystack:
            score += 10

        terms = [t for t in q.split() if t]
        matched_terms = 0
        for term in terms:
            if term in haystack:
                matched_terms += 1
                score += 2

        if len(terms) > 1 and matched_terms == len(terms):
            score += 4

    if case.get("court") == "Appellate Division, First Department":
        score += 2

    if len(case.get("text", "")) > 3000:
        score += 2

    if case.get("outcome") in {"affirmed", "reversed", "granted", "denied"}:
        score += 1

    if case.get("record_type") == "motion_order":
        score -= 10

    useful_len = len(case.get("snippet", "")) + len(case.get("text", ""))
    if useful_len < 120:
        score -= 8
    elif useful_len < 300:
        score -= 4

    if looks_like_bad_title(case.get("title", "")):
        score -= 6

    case["score"] = score
    return score


# =========================
# SIMILAR CASES
# =========================

SIMILAR_STOPWORDS = {
    "the", "and", "for", "that", "with", "from", "this", "into", "their", "there",
    "which", "were", "been", "have", "has", "had", "under", "over", "upon", "without",
    "costs", "order", "entered", "about", "appealed", "limited", "briefs", "branch",
    "motion", "court", "county", "state", "york", "law", "plaintiff", "defendant",
    "defendants", "respondent", "appellant", "appellants", "respondents", "issue",
    "against", "denied", "granted", "affirmed", "reversed", "summary", "judgment",
    "complaint", "claims", "claim", "action", "matter", "extent", "sought", "cross",
    "appeal", "appealed", "appeals", "without", "hearing"
}


def token_set(text):
    raw = normalize_for_search(text).split()
    return {
        tok for tok in raw
        if len(tok) > 2 and tok not in SIMILAR_STOPWORDS and not tok.isdigit()
    }


def substantive_text(case):
    return " ".join([
        case.get("summary", ""),
        case.get("snippet", ""),
        case.get("text", "")[:5000],
        case.get("motion", ""),
        case.get("primary_cause", ""),
    ])


def similar_score(a, b):
    score = 0

    if a.get("court") and a.get("court") == b.get("court"):
        score += 3

    if a.get("outcome") and a.get("outcome") == b.get("outcome"):
        score += 1

    if a.get("motion") and a.get("motion") == b.get("motion"):
        score += 4

    if a.get("primary_cause") and a.get("primary_cause") == b.get("primary_cause"):
        score += 8

    a_tokens = token_set(substantive_text(a))
    b_tokens = token_set(substantive_text(b))
    overlap = len(a_tokens & b_tokens)

    score += min(overlap, 10)

    if overlap < 2:
        score -= 4

    if a.get("record_type") == "motion_order":
        score -= 8

    return score


def get_similar_cases(target_case, all_cases, limit=5):
    scored = []

    target_cause = target_case.get("primary_cause", "")
    target_motion = target_case.get("motion", "")
    target_tokens = token_set(substantive_text(target_case))

    for case in all_cases:
        if case is target_case:
            continue

        if (
            case.get("case_number")
            and target_case.get("case_number")
            and case.get("case_number") == target_case.get("case_number")
        ):
            continue

        if target_case.get("record_type") != "motion_order" and case.get("record_type") == "motion_order":
            continue

        case_tokens = token_set(substantive_text(case))
        overlap = len(target_tokens & case_tokens)

        if target_cause:
            if case.get("primary_cause") != target_cause:
                continue

        if target_motion and case.get("motion") and target_motion != case.get("motion"):
            if overlap < 8:
                continue

        sim_value = similar_score(case, target_case)
        if sim_value <= 0:
            continue

        sim_case = dict(case)
        sim_case["similarity"] = sim_value
        scored.append(sim_case)

    scored.sort(
        key=lambda x: (
            x.get("similarity", 0),
            x.get("date", ""),
            x.get("title", ""),
        ),
        reverse=True,
    )
    return scored[:limit]


# =========================
# DROPDOWNS
# =========================

def build_courts(cases):
    courts = sorted({c.get("court") for c in cases if c.get("court")})
    return ["All Courts"] + courts


def build_outcomes(cases):
    outcomes = sorted({c.get("outcome") for c in cases if c.get("outcome")})
    return ["All Outcomes"] + outcomes


# =========================
# ROUTE
# =========================

@app.route("/", methods=["GET", "POST"])
def index():
    try:
        page = int(request.args.get("page", 1))
    except ValueError:
        page = 1

    if request.method == "POST":
        query = clean_text(request.form.get("query", ""))
        court = clean_text(request.form.get("court", "All Courts")) or "All Courts"
        outcome = clean_text(request.form.get("outcome", "All Outcomes")) or "All Outcomes"
        page = 1
    else:
        query = clean_text(request.args.get("query", ""))
        court = clean_text(request.args.get("court", "All Courts")) or "All Courts"
        outcome = clean_text(request.args.get("outcome", "All Outcomes")) or "All Outcomes"

    cases = load_cases()

    for case in cases:
        score_case(case, query)
        case["display_snippet"] = best_snippet(case, query)

    if not query:
        filtered = []
    else:
        filtered = [
            c for c in cases
            if matches_query(c, query) and matches_filters(c, court, outcome)
        ]

        filtered.sort(
            key=lambda x: (
                x.get("score", 0),
                x.get("date", ""),
                x.get("title", ""),
            ),
            reverse=True,
        )

    pager = build_pager(page, PER_PAGE, len(filtered))

    start = (pager.page - 1) * PER_PAGE
    end = start + PER_PAGE
    results = filtered[start:end]

    for case in results:
        case["similar_cases"] = get_similar_cases(case, filtered, limit=5)

    return render_template(
        "index.html",
        results=results,
        pager=pager,
        query=query,
        courts=build_courts(cases),
        outcomes=build_outcomes(cases),
        selected_court=court,
        selected_outcome=outcome,
    )


# =========================
# RUN
# =========================

if __name__ == "__main__":
    app.run(debug=True, port=5001)