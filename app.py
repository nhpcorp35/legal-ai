from flask import Flask, request, render_template
import json
import math
import os
import csv
from types import SimpleNamespace

app = Flask(__name__)

# =========================
# PATHS
# =========================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PREFERRED_JSON_PATHS = [
    os.path.join(BASE_DIR, "data", "output_v3.json"),
    os.path.join(BASE_DIR, "output_v1.json"),
]

PREFERRED_CSV_PATHS = [
    os.path.join(BASE_DIR, "data", "output_v3.csv"),
    os.path.join(BASE_DIR, "output_enriched.csv"),
    os.path.join(BASE_DIR, "output_clean.csv"),
]

TXT_FALLBACK_PATHS = [
    os.path.join(BASE_DIR, "cases.txt"),
    os.path.join(BASE_DIR, "pdf_cases.txt"),
]

# =========================
# CONFIG
# =========================

COURT_PRIORITY = {
    "Appellate Division, First Department": 5,
    "Appellate Division, Second Department": 5,
    "Appellate Division": 4,
    "Supreme Court": 3,
    "Civil Court": 2,
}

CAUSE_MAP = {
    "negligence": [
        "negligence", "negligent", "duty", "breach", "reasonable care"
    ],
    "contract": [
        "breach of contract", "contract", "agreement", "breach"
    ],
    "fraud": [
        "fraud", "fraudulent", "misrepresentation", "intentional misrepresentation"
    ],
    "labor law": [
        "labor law", "labor law 240", "labor law 241", "construction accident"
    ],
    "conversion": [
        "conversion", "wrongful possession", "unauthorized control"
    ],
    "premises liability": [
        "premises liability", "dangerous condition", "slip and fall"
    ],
}

PER_PAGE = 10

FALLBACK_CASES = [
    {
        "title": "Negligence Summary Judgment Example",
        "court": "Appellate Division, First Department",
        "summary": "The court granted plaintiff partial summary judgment in a negligence action.",
        "snippet": "Plaintiff established duty and breach, and defendants failed to raise a triable issue of fact.",
        "outcome": "granted",
        "citation": "",
        "docket": "",
        "date": "",
        "text": "",
    },
    {
        "title": "Contract Dismissal Example",
        "court": "Supreme Court",
        "summary": "The court denied defendant's motion to dismiss a breach of contract claim.",
        "snippet": "The complaint sufficiently alleged the agreement, plaintiff's performance, breach, and damages.",
        "outcome": "denied",
        "citation": "",
        "docket": "",
        "date": "",
        "text": "",
    },
]

# =========================
# BASIC HELPERS
# =========================

def safe_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def first_nonempty(case, keys, default=""):
    for key in keys:
        value = case.get(key)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return default


def looks_like_docket(value):
    if not value:
        return False
    value = str(value).strip()
    if len(value) > 30:
        return False
    allowed = set("0123456789-/.")
    return all(ch in allowed for ch in value) and any(ch.isdigit() for ch in value)


def clean_text(value):
    return " ".join(str(value or "").split()).strip()


def shorten_court_name(court):
    court = clean_text(court)

    if court == "Appellate Division, First Department":
        return "App Div 1st Dept"
    if court == "Appellate Division, Second Department":
        return "App Div 2nd Dept"
    if court == "Appellate Division":
        return "App Div"
    if court == "Supreme Court":
        return "Sup Ct"
    if court == "Civil Court":
        return "Civ Ct"

    return court


def flatten_citation(case):
    direct = first_nonempty(case, [
        "citation", "cite", "reporter_citation", "slip_op", "slip_op_citation"
    ], "")
    if direct:
        return clean_text(direct)

    citations = case.get("citations")
    if isinstance(citations, dict):
        slip_ops = citations.get("slip_op") or []
        reporters = citations.get("reporters") or []

        if slip_ops and isinstance(slip_ops, list):
            return clean_text(slip_ops[0])

        if reporters and isinstance(reporters, list):
            return clean_text(reporters[0])

    return ""


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

# =========================
# NORMALIZATION
# =========================

def derive_title(case, summary, docket):
    direct_title = first_nonempty(case, [
        "title",
        "case_title",
        "decision_title",
        "caption",
        "case_name",
        "matter_name",
        "matter",
        "name",
        "full_title",
        "short_title",
    ], "")

    if direct_title and not looks_like_docket(direct_title):
        return clean_text(direct_title)

    parties = case.get("parties")
    if isinstance(parties, list) and len(parties) >= 2:
        p1 = clean_text(parties[0])
        p2 = clean_text(parties[1])
        if p1 and p2:
            return f"{p1} v. {p2}"
    elif isinstance(parties, list) and len(parties) == 1:
        p1 = clean_text(parties[0])
        if p1 and not looks_like_docket(p1):
            return p1

    if summary:
        first_sentence = summary.split(". ")[0].strip()
        if first_sentence and len(first_sentence) <= 180 and not looks_like_docket(first_sentence):
            return clean_text(first_sentence)

    case_number = clean_text(first_nonempty(case, [
        "case_number", "docket", "docket_number", "index_number", "case_number", "id", "case_id"
    ], docket))

    court = shorten_court_name(first_nonempty(case, [
        "court", "court_name", "jurisdiction", "tribunal"
    ], ""))

    date = clean_text(first_nonempty(case, [
        "date", "decision_date", "filed_date", "published_date"
    ], ""))

    if case_number and court and date:
        return f"Case {case_number} ({court}, {date})"
    if case_number and court:
        return f"Case {case_number} ({court})"
    if case_number:
        return f"Case {case_number}"

    if direct_title:
        return clean_text(direct_title)

    return "Untitled Case"


def normalize_case(raw):
    case = dict(raw)

    court = first_nonempty(case, [
        "court", "court_name", "jurisdiction", "tribunal"
    ], "Unknown Court")

    summary = clean_text(first_nonempty(case, [
        "summary", "decision_text", "body", "text", "opinion", "headnote", "abstract"
    ], ""))

    snippet = clean_text(first_nonempty(case, [
        "snippet", "excerpt", "preview", "summary", "headnote"
    ], summary[:300]))

    outcome = clean_text(first_nonempty(case, [
        "outcome", "result", "disposition"
    ], ""))

    citation = flatten_citation(case)

    docket = clean_text(first_nonempty(case, [
        "docket", "docket_number", "index_number", "case_number", "id", "case_id"
    ], ""))

    date = clean_text(first_nonempty(case, [
        "date", "decision_date", "filed_date", "published_date"
    ], ""))

    text = clean_text(first_nonempty(case, [
        "text", "body", "decision_text", "opinion", "summary"
    ], ""))

    title = derive_title(case, summary, docket)

    normalized = dict(case)
    normalized["title"] = title
    normalized["court"] = court
    normalized["summary"] = summary
    normalized["snippet"] = snippet
    normalized["outcome"] = outcome
    normalized["citation"] = citation
    normalized["docket"] = docket
    normalized["date"] = date
    normalized["text"] = text

    return normalized

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

    raise ValueError(f"Unsupported JSON structure in {path}")


def load_csv_cases(path):
    rows = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    return rows


def parse_txt_blocks(path):
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read().strip()

    if not raw:
        return []

    blocks = [b.strip() for b in raw.split("\n\n") if b.strip()]
    rows = []

    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue

        rows.append({
            "title": lines[0][:120],
            "court": "Unknown Court",
            "summary": " ".join(lines)[:1200],
            "snippet": " ".join(lines)[:300],
            "outcome": "",
            "citation": "",
            "docket": lines[0] if len(lines[0]) <= 60 else "",
            "date": "",
            "text": block,
        })

    return rows


def load_cases():
    for path in PREFERRED_JSON_PATHS:
        if os.path.exists(path):
            try:
                rows = load_json_cases(path)
                if rows:
                    print(f"✅ Loaded {len(rows)} structured JSON cases from {path}")
                    return [normalize_case(r) for r in rows]
            except Exception as e:
                print(f"❌ Failed loading JSON {path}: {e}")

    for path in PREFERRED_CSV_PATHS:
        if os.path.exists(path):
            try:
                rows = load_csv_cases(path)
                if rows:
                    print(f"✅ Loaded {len(rows)} structured CSV rows from {path}")
                    return [normalize_case(r) for r in rows]
            except Exception as e:
                print(f"❌ Failed loading CSV {path}: {e}")

    for path in TXT_FALLBACK_PATHS:
        if os.path.exists(path):
            try:
                rows = parse_txt_blocks(path)
                if rows:
                    print(f"⚠️ Loaded {len(rows)} text fallback cases from {path}")
                    return [normalize_case(r) for r in rows]
            except Exception as e:
                print(f"❌ Failed loading TXT {path}: {e}")

    print("⚠️ No usable data files found. Using fallback cases.")
    return [normalize_case(r) for r in FALLBACK_CASES]

# =========================
# DETECTION
# =========================

def detect_cause(text):
    text = (text or "").lower()
    for cause, keywords in CAUSE_MAP.items():
        for kw in keywords:
            if kw in text:
                return cause
    return None


def detect_case_cause(case):
    text = " ".join([
        case.get("title", ""),
        case.get("summary", ""),
        case.get("snippet", ""),
        case.get("text", ""),
    ]).lower()

    for cause, keywords in CAUSE_MAP.items():
        for kw in keywords:
            if kw in text:
                return cause
    return None


def detect_motion(text):
    text = (text or "").lower()

    if "summary judgment" in text:
        return "summary judgment"
    if "motion to dismiss" in text or "dismiss" in text:
        return "dismissal"
    if "preliminary injunction" in text:
        return "preliminary injunction"
    if "default judgment" in text:
        return "default judgment"

    return None


def detect_outcome(case):
    explicit = (case.get("outcome") or "").lower().strip()
    if explicit:
        if "affirm" in explicit:
            return "affirmed"
        if "revers" in explicit:
            return "reversed"
        if "grant" in explicit:
            return "granted"
        if "deni" in explicit:
            return "denied"

    text = " ".join([
        case.get("summary", ""),
        case.get("snippet", ""),
        case.get("text", ""),
    ]).lower()

    if "reversed" in text:
        return "reversed"
    if "unanimously affirmed" in text or " affirmed" in text or text.startswith("affirmed"):
        return "affirmed"
    if "granted" in text:
        return "granted"
    if "denied" in text:
        return "denied"

    return None


def get_court_score(court):
    return COURT_PRIORITY.get(court, 1)

# =========================
# SEARCH / FILTERS
# =========================

def text_for_search(case):
    return " ".join([
        case.get("title", ""),
        case.get("court", ""),
        case.get("summary", ""),
        case.get("snippet", ""),
        case.get("citation", ""),
        case.get("docket", ""),
        case.get("date", ""),
        case.get("text", ""),
    ]).lower()


def matches_query(case, query):
    query = (query or "").strip().lower()
    if not query:
        return True

    haystack = text_for_search(case)
    terms = [term for term in query.split() if term.strip()]
    return all(term in haystack for term in terms)


def matches_filters(case, selected_court, selected_outcome):
    if selected_court and selected_court != "All Courts":
        if case.get("court") != selected_court:
            return False

    case_outcome = case.get("outcome") or detect_outcome(case) or ""
    if selected_outcome and selected_outcome != "All Outcomes":
        if case_outcome.lower() != selected_outcome.lower():
            return False

    return True

# =========================
# RANKING
# =========================

def score_case(case, user_query):
    score = 0

    query_cause = detect_cause(user_query)
    case_cause = detect_case_cause(case)

    query_motion = detect_motion(user_query)
    case_motion = detect_motion(" ".join([
        case.get("title", ""),
        case.get("summary", ""),
        case.get("snippet", ""),
        case.get("text", ""),
    ]))

    case_outcome = detect_outcome(case)

    score += get_court_score(case.get("court"))

    if user_query:
        haystack = text_for_search(case)
        for term in user_query.lower().split():
            if term in haystack:
                score += 2

    if query_motion:
        if case_motion == query_motion:
            score += 15
        elif case_motion:
            score -= 5

    if query_cause:
        if case_cause == query_cause:
            score += 25
            case["cause_match"] = "green"
        elif case_cause:
            score -= 15
            case["cause_match"] = "red"
        else:
            score -= 5
            case["cause_match"] = "yellow"
    else:
        case["cause_match"] = "yellow"

    if case_outcome == "granted":
        score += 3
    elif case_outcome == "affirmed":
        score += 2
    elif case_outcome == "reversed":
        score += 2

    case["score"] = score
    case["cause"] = case_cause
    case["motion"] = case_motion
    case["outcome"] = case_outcome

    return score

# =========================
# SIMILAR CASES
# =========================

def compute_similarity(case, target):
    score = 0

    if case.get("court") == target.get("court"):
        score += 3
    if case.get("motion") == target.get("motion"):
        score += 2
    if case.get("cause") == target.get("cause"):
        score += 4
    if case.get("outcome") == target.get("outcome"):
        score += 1

    return score


def attach_match_labels(case, target_case):
    same_court = case.get("court") == target_case.get("court")
    same_motion = case.get("motion") == target_case.get("motion")
    same_cause = case.get("cause") == target_case.get("cause")
    same_outcome = case.get("outcome") == target_case.get("outcome")

    case["match_labels"] = {
        "court": "green" if same_court else "yellow",
        "motion": "green" if same_motion else "yellow",
        "cause": "green" if same_cause else ("red" if case.get("cause") and target_case.get("cause") else "yellow"),
        "outcome": "green" if same_outcome else "yellow",
    }

    badges = []
    if same_court:
        badges.append("Same Court")
    if same_motion:
        badges.append("Same Motion")
    if same_cause:
        badges.append("Same Cause")
    if same_outcome:
        badges.append("Same Outcome")

    case["match_badges"] = badges


def get_similar_cases(target_case, all_cases, limit=5):
    scored = []

    for case in all_cases:
        if case is target_case:
            continue

        sim_case = dict(case)
        sim_case["similarity"] = compute_similarity(sim_case, target_case)
        attach_match_labels(sim_case, target_case)
        scored.append(sim_case)

    scored.sort(key=lambda x: x["similarity"], reverse=True)
    return scored[:limit]

# =========================
# DROPDOWNS
# =========================

def build_court_options(cases):
    courts = sorted({case.get("court", "").strip() for case in cases if case.get("court")})
    return ["All Courts"] + courts


def build_outcome_options(cases):
    outcomes = []
    seen = set()

    for case in cases:
        outcome = detect_outcome(case)
        if outcome and outcome not in seen:
            outcomes.append(outcome)
            seen.add(outcome)

    outcomes = sorted(outcomes)
    return ["All Outcomes"] + outcomes

# =========================
# ROUTE
# =========================

@app.route("/", methods=["GET", "POST"])
def index():
    page = safe_int(request.args.get("page"), 1)

    if request.method == "POST":
        query = (request.form.get("query") or "").strip()
        selected_court = (request.form.get("court") or "All Courts").strip()
        selected_outcome = (request.form.get("outcome") or "All Outcomes").strip()
        page = 1
    else:
        query = (request.args.get("query") or "").strip()
        selected_court = (request.args.get("court") or "All Courts").strip()
        selected_outcome = (request.args.get("outcome") or "All Outcomes").strip()

    all_cases = load_cases()

    courts = build_court_options(all_cases)
    outcomes = build_outcome_options(all_cases)

    filtered_cases = []
    for case in all_cases:
        if matches_query(case, query) and matches_filters(case, selected_court, selected_outcome):
            score_case(case, query)
            filtered_cases.append(case)

    if query:
        filtered_cases.sort(key=lambda x: x.get("score", 0), reverse=True)
    else:
        filtered_cases.sort(key=lambda x: (-get_court_score(x.get("court")), x.get("title", "")))

    pager = build_pager(page, PER_PAGE, len(filtered_cases))

    start = (pager.page - 1) * pager.per_page
    end = start + pager.per_page
    results = filtered_cases[start:end]

    for case in results:
        case["similar_cases"] = get_similar_cases(case, filtered_cases, limit=5)

    return render_template(
        "index.html",
        results=results,
        query=query,
        pager=pager,
        courts=courts,
        outcomes=outcomes,
        selected_court=selected_court,
        selected_outcome=selected_outcome,
    )

# =========================
# RUN
# =========================

if __name__ == "__main__":
    app.run(debug=True, port=5001)