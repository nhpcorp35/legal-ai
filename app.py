import csv
import html
import math
import os
import re
from pathlib import Path

from flask import Flask, render_template, request, url_for

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent

CSV_PATH = BASE_DIR / "output_enriched.csv"
PDF_DIR = BASE_DIR / "static" / "pdfs"

PER_PAGE = 10
MAX_SNIPPETS = 3
SEARCH_CACHE_LIMIT = 100

APP_STATE = {
    "rows": None,
    "load_error": None,
    "search_cache": {},
}


# =========================
# Utilities
# =========================

def normalize_space(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_text(value):
    return normalize_space(value).lower()


def tokenize_query(query):
    return re.findall(r"[A-Za-z0-9\-]+", normalize_text(query))


def html_highlight(text, terms):
    escaped = html.escape(str(text or ""))
    if not terms:
        return escaped

    clean_terms = [t for t in terms if t]
    if not clean_terms:
        return escaped

    pattern = re.compile(
        r"(" + "|".join(re.escape(t) for t in clean_terms) + r")",
        re.IGNORECASE,
    )
    return pattern.sub(r"<mark>\1</mark>", escaped)


def safe_int(value, default=1):
    try:
        return int(value)
    except Exception:
        return default


def clear_search_cache():
    APP_STATE["search_cache"] = {}


def cache_search_result(query_norm, results):
    cache = APP_STATE["search_cache"]
    if len(cache) >= SEARCH_CACHE_LIMIT:
        oldest_key = next(iter(cache))
        del cache[oldest_key]
    cache[query_norm] = results


# =========================
# Snippets
# =========================

def split_sentences(text):
    text = normalize_space(text)
    if not text:
        return []
    parts = re.split(r"(?<=[\.\?!;:])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def trim_snippet(text, max_len=260):
    text = normalize_space(text)
    if len(text) <= max_len:
        return text
    cut = text[:max_len].rstrip()
    last_space = cut.rfind(" ")
    if last_space > int(max_len * 0.7):
        cut = cut[:last_space]
    return cut.rstrip(" ,;:-") + " …"


def build_snippets(full_text, query, terms):
    if not full_text:
        return []

    text = normalize_space(full_text)
    sentences = split_sentences(text)
    if not sentences:
        return []

    scored = []
    q_norm = normalize_text(query)

    for s in sentences:
        s_norm = normalize_text(s)
        score = 0

        if q_norm and q_norm in s_norm:
            score += 100

        score += sum(1 for t in terms if t and t in s_norm) * 10
        score += max(0, 50 - len(s) // 5)

        if score > 0:
            scored.append((score, s))

    scored.sort(key=lambda x: -x[0])

    snippets = []
    seen = set()

    for _, s in scored:
        key = s[:120].lower()
        if key in seen:
            continue
        seen.add(key)
        snippets.append(trim_snippet(s))
        if len(snippets) >= MAX_SNIPPETS:
            break

    if not snippets:
        for s in sentences[:2]:
            snippets.append(trim_snippet(s))

    return snippets


# =========================
# Data loading
# =========================

def build_pdf_index():
    pdf_index = {}

    for p in PDF_DIR.glob("*.pdf"):
        name = p.name
        case_number = name.split("__", 1)[0].strip()
        if case_number and case_number not in pdf_index:
            pdf_index[case_number] = name

    return pdf_index


def load_rows():
    rows = []

    print("=== STARTUP PATH CHECK ===")
    print("BASE_DIR:", BASE_DIR)
    print("CSV_PATH:", CSV_PATH, "exists:", CSV_PATH.exists())
    print("PDF_DIR:", PDF_DIR, "exists:", PDF_DIR.exists())
    print("==========================")

    if not CSV_PATH.exists():
        raise FileNotFoundError(f"Missing CSV: {CSV_PATH}")

    if not PDF_DIR.exists():
        raise FileNotFoundError(f"Missing PDF directory: {PDF_DIR}")

    pdf_index = build_pdf_index()
    print("PDF_INDEX_COUNT:", len(pdf_index))

    with open(CSV_PATH, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        for i, r in enumerate(reader):
            case_number = normalize_space(r.get("case_number", ""))
            if not case_number:
                continue

            pdf_file = pdf_index.get(case_number)
            if not pdf_file:
                continue

            title = normalize_space(r.get("case_name", ""))
            if not title:
                title = normalize_space(r.get("summary", ""))[:120]
            if not title:
                title = case_number or "Untitled case"

            full_text = r.get("full_text", "")
            facts_text = r.get("facts_excerpt", "")
            procedure_text = r.get("procedure_text", "")
            claims_text = r.get("claims_text", "")
            relief_text = r.get("relief_text", "")
            summary_text = r.get("summary", "")
            court_text = normalize_space(r.get("court", ""))
            outcome_text = normalize_space(r.get("outcome", ""))
            judges_text = r.get("judges", "")

            title_norm = normalize_text(title)
            full_text_norm = normalize_text(full_text)
            facts_text_norm = normalize_text(facts_text)
            procedure_text_norm = normalize_text(procedure_text)
            claims_text_norm = normalize_text(claims_text)
            relief_text_norm = normalize_text(relief_text)

            metadata_blob = normalize_text(
                " ".join([
                    title,
                    court_text,
                    outcome_text,
                    judges_text,
                    summary_text,
                    case_number,
                ])
            )

            rows.append({
                "id": i,
                "case_number": case_number,
                "title": title,
                "title_norm": title_norm,
                "court": court_text,
                "court_norm": normalize_text(court_text),
                "outcome": outcome_text,
                "outcome_norm": normalize_text(outcome_text),
                "judges_text": judges_text,
                "summary": summary_text,
                "pdf_filename": pdf_file,
                "full_text": full_text,
                "full_text_norm": full_text_norm,
                "facts_text": facts_text,
                "facts_text_norm": facts_text_norm,
                "procedure_text": procedure_text,
                "procedure_text_norm": procedure_text_norm,
                "claims_text": claims_text,
                "claims_text_norm": claims_text_norm,
                "relief_text": relief_text,
                "relief_text_norm": relief_text_norm,
                "metadata_blob": metadata_blob,
            })

    print("ROWS_LOADED:", len(rows))
    clear_search_cache()
    return rows


def get_rows():
    if APP_STATE["rows"] is not None:
        return APP_STATE["rows"]

    if APP_STATE["load_error"] is not None:
        return []

    try:
        APP_STATE["rows"] = load_rows()
    except Exception as e:
        APP_STATE["load_error"] = str(e)
        print("LOAD ERROR:", repr(e))
        APP_STATE["rows"] = []

    return APP_STATE["rows"]


# =========================
# Ranking v2
# =========================

def token_positions(text, terms):
    if not text or not terms:
        return {}

    words = re.findall(r"[A-Za-z0-9\-]+", text)
    positions = {t: [] for t in terms}

    for idx, word in enumerate(words):
        for term in terms:
            if word == term:
                positions[term].append(idx)

    return positions


def proximity_score(text, terms):
    unique_terms = [t for t in dict.fromkeys(terms) if t]
    if len(unique_terms) < 2 or not text:
        return 0

    positions = token_positions(text, unique_terms)
    present_terms = [t for t in unique_terms if positions.get(t)]

    if len(present_terms) < 2:
        return 0

    all_positions = []
    for term in present_terms:
        for pos in positions[term]:
            all_positions.append((pos, term))

    all_positions.sort()
    best_window = None
    left = 0
    counts = {}

    for right in range(len(all_positions)):
        right_pos, right_term = all_positions[right]
        counts[right_term] = counts.get(right_term, 0) + 1

        while len(counts) == len(present_terms):
            left_pos, left_term = all_positions[left]
            window = right_pos - left_pos + 1
            if best_window is None or window < best_window:
                best_window = window

            counts[left_term] -= 1
            if counts[left_term] == 0:
                del counts[left_term]
            left += 1

    if best_window is None:
        return 0

    if best_window <= 5:
        return 220
    if best_window <= 10:
        return 140
    if best_window <= 20:
        return 80
    if best_window <= 40:
        return 35
    return 10


def field_coverage_bonus(text, terms):
    unique_terms = {t for t in terms if t}
    if not unique_terms or not text:
        return 0, 0

    matched = sum(1 for t in unique_terms if t in text)
    coverage_ratio = matched / len(unique_terms)

    if coverage_ratio == 1:
        return matched, 180
    if coverage_ratio >= 0.8:
        return matched, 110
    if coverage_ratio >= 0.6:
        return matched, 55
    if coverage_ratio >= 0.4:
        return matched, 20
    return matched, 0


def score_row(row, query_norm, terms):
    if not query_norm:
        return 0

    full_text = row["full_text_norm"]
    facts_text = row["facts_text_norm"]
    procedure_text = row["procedure_text_norm"]
    claims_text = row["claims_text_norm"]
    relief_text = row["relief_text_norm"]
    metadata = row["metadata_blob"]

    score = 0

    # 1. Exact phrase boost
    if query_norm in full_text:
        score += 1000
    if query_norm in facts_text:
        score += 500
    if query_norm in procedure_text:
        score += 380
    if query_norm in claims_text:
        score += 380
    if query_norm in relief_text:
        score += 380
    if query_norm in metadata:
        score += 80

    # 2. Exact phrase frequency by field
    score += full_text.count(query_norm) * 120
    score += facts_text.count(query_norm) * 85
    score += procedure_text.count(query_norm) * 65
    score += claims_text.count(query_norm) * 65
    score += relief_text.count(query_norm) * 65
    score += metadata.count(query_norm) * 10

    # 3. Term hits by field
    full_hits = sum(1 for t in terms if t and t in full_text)
    facts_hits = sum(1 for t in terms if t and t in facts_text)
    procedure_hits = sum(1 for t in terms if t and t in procedure_text)
    claims_hits = sum(1 for t in terms if t and t in claims_text)
    relief_hits = sum(1 for t in terms if t and t in relief_text)
    metadata_hits = sum(1 for t in terms if t and t in metadata)

    score += full_hits * 35
    score += facts_hits * 24
    score += procedure_hits * 18
    score += claims_hits * 18
    score += relief_hits * 18
    score += metadata_hits * 4

    # 4. Coverage bonuses
    _, full_coverage_bonus = field_coverage_bonus(full_text, terms)
    _, facts_coverage_bonus = field_coverage_bonus(facts_text, terms)
    _, procedure_coverage_bonus = field_coverage_bonus(procedure_text, terms)
    _, claims_coverage_bonus = field_coverage_bonus(claims_text, terms)
    _, relief_coverage_bonus = field_coverage_bonus(relief_text, terms)

    score += full_coverage_bonus
    score += int(facts_coverage_bonus * 0.65)
    score += int(procedure_coverage_bonus * 0.45)
    score += int(claims_coverage_bonus * 0.45)
    score += int(relief_coverage_bonus * 0.45)

    # 5. Proximity scoring
    score += proximity_score(full_text, terms)
    score += int(proximity_score(facts_text, terms) * 0.6)
    score += int(proximity_score(procedure_text, terms) * 0.4)
    score += int(proximity_score(claims_text, terms) * 0.4)
    score += int(proximity_score(relief_text, terms) * 0.4)

    # 6. Legal phrase boost
    legal_phrases = [
        "motion to dismiss",
        "summary judgment",
        "breach of contract",
        "breach of fiduciary duty",
        "tortious interference",
        "unjust enrichment",
        "deceptive trade practices",
        "fraud",
        "negligence",
        "damages",
        "liability",
        "injunction",
        "foreclosure",
        "mandamus",
    ]

    for phrase in legal_phrases:
        if phrase in query_norm:
            if phrase in full_text:
                score += 180
            if phrase in facts_text:
                score += 100
            if phrase in procedure_text or phrase in claims_text or phrase in relief_text:
                score += 75
            if phrase in metadata:
                score += 20

    return score


def search_rows(rows, query):
    if not query:
        return rows

    query_norm = normalize_text(query)
    if not query_norm:
        return rows

    cached = APP_STATE["search_cache"].get(query_norm)
    if cached is not None:
        return cached

    terms = tokenize_query(query_norm)
    results = []

    for row in rows:
        s = score_row(row, query_norm, terms)
        if s > 0:
            r = dict(row)
            r["_score"] = s
            results.append(r)

    results.sort(key=lambda r: (-r["_score"], r["title_norm"]))
    cache_search_result(query_norm, results)
    return results


# =========================
# Filters
# =========================

def get_filter_options(rows):
    courts = sorted({r["court"] for r in rows if normalize_space(r.get("court", ""))})
    outcomes = sorted({r["outcome"] for r in rows if normalize_space(r.get("outcome", ""))})
    return courts, outcomes


def apply_filters(rows, court_filter, outcome_filter):
    court_norm = normalize_text(court_filter)
    outcome_norm = normalize_text(outcome_filter)

    filtered = rows

    if court_norm:
        filtered = [r for r in filtered if r.get("court_norm", "") == court_norm]

    if outcome_norm:
        filtered = [r for r in filtered if r.get("outcome_norm", "") == outcome_norm]

    return filtered


# =========================
# Pagination
# =========================

def paginate(items, page):
    total = len(items)
    total_pages = max(1, math.ceil(total / PER_PAGE))

    page = max(1, min(page, total_pages))
    start = (page - 1) * PER_PAGE
    end = start + PER_PAGE

    return {
        "items": items[start:end],
        "page": page,
        "total": total,
        "total_pages": total_pages,
        "start_index": start + 1 if total else 0,
        "end_index": min(end, total),
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "prev_page": page - 1,
        "next_page": page + 1,
    }


# =========================
# Routes
# =========================

@app.route("/healthz")
def healthz():
    rows = get_rows()
    return {
        "ok": True,
        "rows_loaded": len(rows),
        "load_error": APP_STATE["load_error"],
        "csv_exists": CSV_PATH.exists(),
        "pdf_dir_exists": PDF_DIR.exists(),
        "search_cache_size": len(APP_STATE["search_cache"]),
    }


@app.route("/")
def index():
    query = normalize_space(request.args.get("q", ""))
    court_filter = normalize_space(request.args.get("court", ""))
    outcome_filter = normalize_space(request.args.get("outcome", ""))
    page = safe_int(request.args.get("page", "1"))

    rows = get_rows()
    court_options, outcome_options = get_filter_options(rows)

    searched = search_rows(rows, query)
    filtered = apply_filters(searched, court_filter, outcome_filter)
    pager = paginate(filtered, page)
    terms = tokenize_query(query)

    display = []

    for r in pager["items"]:
        snippets = build_snippets(r["full_text"], query, terms) if query else []

        if query and not snippets:
            fallback = normalize_space(r.get("summary", ""))[:260]
            if fallback:
                snippets = [fallback]

        display.append({
            **r,
            "pdf_url": url_for("static", filename=f"pdfs/{r['pdf_filename']}"),
            "title_html": html_highlight(r["title"], terms),
            "case_number_html": html_highlight(r["case_number"], terms),
            "court_html": html_highlight(r["court"], terms),
            "outcome_html": html_highlight(r["outcome"], terms),
            "judges_html": html_highlight(r["judges_text"], terms),
            "snippets": [html_highlight(s, terms) for s in snippets],
        })

    return render_template(
        "index.html",
        results=display,
        query=query,
        court_filter=court_filter,
        outcome_filter=outcome_filter,
        court_options=court_options,
        outcome_options=outcome_options,
        pager=pager,
        total_loaded=len(rows),
        load_error=APP_STATE["load_error"],
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)