import csv
import html
import math
import os
import re
from collections import Counter
from pathlib import Path

from flask import Flask, render_template, request, url_for

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent

CSV_PATH = BASE_DIR / "output_enriched.csv"
PDF_DIR = BASE_DIR / "static" / "pdfs"

PER_PAGE = 10
MAX_SNIPPETS = 3
SIMILAR_CASES_LIMIT = 5

APP_STATE = {
    "rows": None,
    "load_error": None,
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

    snippets = []
    seen = set()
    query_norm = normalize_text(query)

    def add(sentence):
        sentence = normalize_space(sentence)
        if not sentence:
            return
        key = sentence[:180].lower()
        if key in seen:
            return
        seen.add(key)
        snippets.append(trim_snippet(sentence))

    for s in sentences:
        if query_norm and query_norm in normalize_text(s):
            add(s)
            if len(snippets) >= MAX_SNIPPETS:
                return snippets

    if not snippets:
        scored = []
        for s in sentences:
            count = sum(1 for t in terms if t and t in normalize_text(s))
            if count > 0:
                scored.append((count, s))
        scored.sort(key=lambda x: -x[0])

        for _, s in scored:
            add(s)
            if len(snippets) >= MAX_SNIPPETS:
                return snippets

    if not snippets:
        for s in sentences[:2]:
            add(s)

    return snippets


# =========================
# Similar Cases v2.1
# =========================

STOPWORDS = set([
    "the", "and", "of", "to", "in", "for", "on", "with", "at", "by", "an", "be",
    "this", "that", "is", "are", "was", "were", "as", "from", "it", "or", "not",
    "have", "has", "had", "but", "into", "than", "then", "their", "there",
    "court", "case", "plaintiff", "defendant", "judge", "justice", "law", "legal",
    "matter", "action", "claim", "claims", "filed", "held", "decision", "opinion",
    "order", "judgment", "appeal", "appellant", "respondent", "petitioner",
    "against", "under", "upon", "whether", "because", "which", "also"
])

LEGAL_PHRASES = [
    "motion to dismiss",
    "summary judgment",
    "breach of contract",
    "failure to state a claim",
    "preliminary injunction",
    "statute of limitations",
    "subject matter jurisdiction",
    "personal jurisdiction",
    "standard of review",
    "burden of proof",
    "breach of fiduciary duty",
    "tortious interference",
    "unjust enrichment",
    "labor law",
    "constructive trust",
    "fraudulent inducement",
    "specific performance",
    "wrongful termination",
    "motion for summary judgment",
    "motion for leave to amend",
    "motion to compel",
    "motion for a preliminary injunction",
]


def tokenize_similarity(text):
    text = normalize_text(text)
    tokens = re.findall(r"\b[a-z]+\b", text)
    return [t for t in tokens if t not in STOPWORDS and len(t) > 2]


def extract_phrases(text):
    text = normalize_text(text)
    found = []
    for phrase in LEGAL_PHRASES:
        if phrase in text:
            found.append(phrase)
    return found


def classify_reason(shared_phrases, same_outcome, same_court, token_score):
    reasons = []
    if shared_phrases:
        reasons.append("shared legal phrases")
    if same_outcome:
        reasons.append("same outcome")
    if same_court:
        reasons.append("same court")
    if token_score >= 6 and not shared_phrases:
        reasons.append("related legal language")
    return " · ".join(reasons[:2])


def similarity_score(base_text, other_text, base_row=None, other_row=None):
    base_text = str(base_text or "")
    other_text = str(other_text or "")

    base_tokens = tokenize_similarity(base_text)
    other_tokens = tokenize_similarity(other_text)

    if not base_tokens or not other_tokens:
        return 0, "", []

    base_counts = Counter(base_tokens)
    other_counts = Counter(other_tokens)

    overlap = set(base_counts) & set(other_counts)
    token_score = sum(min(base_counts[t], other_counts[t]) for t in overlap)

    score = token_score * 1.0

    base_phrases = set(extract_phrases(base_text))
    other_phrases = set(extract_phrases(other_text))
    shared_phrases = sorted(base_phrases & other_phrases)

    score += len(shared_phrases) * 25

    same_outcome = False
    same_court = False

    if base_row is not None and other_row is not None:
        base_outcome = normalize_text(base_row.get("outcome", ""))
        other_outcome = normalize_text(other_row.get("outcome", ""))
        base_court = normalize_text(base_row.get("court", ""))
        other_court = normalize_text(other_row.get("court", ""))

        if base_outcome and other_outcome and base_outcome == other_outcome:
            score += 10
            same_outcome = True

        if base_court and other_court and base_court == other_court:
            score += 5
            same_court = True

    if token_score > 0 and not shared_phrases:
        score *= 0.6

    if token_score < 2 and not shared_phrases:
        score = 0

    reason = classify_reason(shared_phrases, same_outcome, same_court, token_score)
    return score, reason, shared_phrases


def get_similar_cases(target_row, all_rows, top_n=SIMILAR_CASES_LIMIT):
    base_text = str(target_row.get("search_blob", "") or target_row.get("full_text", "") or "")
    target_case_number = str(target_row.get("case_number", "") or "")

    scored = []

    for row in all_rows:
        row_case_number = str(row.get("case_number", "") or "")

        if target_case_number and row_case_number and row_case_number == target_case_number:
            continue

        other_text = str(row.get("search_blob", "") or row.get("full_text", "") or "")
        score, reason, shared_phrases = similarity_score(
            base_text,
            other_text,
            base_row=target_row,
            other_row=row,
        )

        if score > 0:
            r = dict(row)
            r["_similarity_score"] = score
            r["reason"] = reason
            r["shared_phrases"] = shared_phrases
            scored.append(r)

    scored.sort(key=lambda r: (-r["_similarity_score"], r.get("title", "")))
    return scored[:top_n]


# =========================
# Data loading
# =========================

def load_rows():
    rows = []

    print("=== STARTUP PATH CHECK ===")
    print("BASE_DIR:", BASE_DIR)
    print("CSV_PATH:", CSV_PATH, "exists:", CSV_PATH.exists())
    print("PDF_DIR:", PDF_DIR, "exists:", PDF_DIR.exists())
    if PDF_DIR.exists():
        try:
            pdf_count = len(list(PDF_DIR.glob("*.pdf")))
        except Exception:
            pdf_count = "unknown"
        print("PDF_COUNT:", pdf_count)
    print("==========================")

    if not CSV_PATH.exists():
        raise FileNotFoundError(f"Missing CSV: {CSV_PATH}")

    if not PDF_DIR.exists():
        raise FileNotFoundError(f"Missing PDF directory: {PDF_DIR}")

    pdf_lookup = {}
    for p in PDF_DIR.glob("*.pdf"):
        prefix = p.name.split("__", 1)[0]
        pdf_lookup[prefix] = p.name

    with open(CSV_PATH, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        for i, r in enumerate(reader):
            case_number = normalize_space(r.get("case_number", ""))
            pdf_file = pdf_lookup.get(case_number)

            if not pdf_file:
                continue

            title = normalize_space(r.get("case_name", ""))
            if not title:
                title = normalize_space(r.get("summary", ""))[:120]
            if not title:
                title = case_number or "Untitled case"

            full_text = r.get("full_text", "") or ""
            summary = r.get("summary", "") or ""
            court = normalize_space(r.get("court", ""))
            outcome = normalize_space(r.get("outcome", ""))
            judges = normalize_space(r.get("judges", ""))

            search_blob = normalize_text(
                " ".join([
                    title,
                    court,
                    outcome,
                    judges,
                    summary,
                    full_text,
                    case_number,
                ])
            )

            metadata_blob = normalize_text(
                " ".join([
                    title,
                    court,
                    outcome,
                    judges,
                    summary,
                    case_number,
                ])
            )

            rows.append({
                "id": i,
                "case_number": case_number,
                "title": title,
                "court": court,
                "outcome": outcome,
                "judges_text": judges,
                "summary": summary,
                "pdf_filename": pdf_file,
                "full_text": full_text,
                "full_text_norm": normalize_text(full_text),
                "search_blob": search_blob,
                "metadata_blob": metadata_blob,
            })

    print("ROWS_LOADED:", len(rows))
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
# Ranking / Filtering
# =========================

def score_row(row, query, terms):
    if not query:
        return 0

    q = normalize_text(query)
    full_text = row["full_text_norm"]
    metadata = row["metadata_blob"]

    score = 0

    if q in full_text:
        score += 1000

    hits = sum(1 for t in terms if t in full_text)
    score += hits * 100

    if score == 0:
        meta_hits = sum(1 for t in terms if t in metadata)
        score += meta_hits * 20

    return score


def filter_rows(rows, court_filter="", outcome_filter=""):
    court_filter = normalize_text(court_filter)
    outcome_filter = normalize_text(outcome_filter)

    filtered = []
    for row in rows:
        if court_filter and normalize_text(row.get("court", "")) != court_filter:
            continue
        if outcome_filter and normalize_text(row.get("outcome", "")) != outcome_filter:
            continue
        filtered.append(row)
    return filtered


def search_rows(rows, query):
    if not query:
        return [dict(r) for r in rows]

    terms = tokenize_query(query)
    results = []

    for row in rows:
        s = score_row(row, query, terms)
        if s > 0:
            r = dict(row)
            r["_score"] = s
            results.append(r)

    results.sort(key=lambda r: (-r["_score"], r["title"]))
    return results


def unique_values(rows, key):
    values = sorted({normalize_space(r.get(key, "")) for r in rows if normalize_space(r.get(key, ""))})
    return values


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
    }


@app.route("/")
def index():
    query = normalize_space(request.args.get("q", ""))
    court_filter = normalize_space(request.args.get("court", ""))
    outcome_filter = normalize_space(request.args.get("outcome", ""))
    page = safe_int(request.args.get("page", "1"))

    rows = get_rows()
    filter_first = filter_rows(rows, court_filter, outcome_filter)
    filtered = search_rows(filter_first, query)
    pager = paginate(filtered, page)
    terms = tokenize_query(query)

    display = []

    for r in pager["items"]:
        snippets = build_snippets(r["full_text"], query, terms) if query else []

        if query and not snippets:
            fallback = normalize_space(r.get("summary", ""))[:260]
            if fallback:
                snippets = [fallback]

        similar_raw = get_similar_cases(r, rows, top_n=SIMILAR_CASES_LIMIT)
        similar_cases = []
        for sim in similar_raw:
            similar_cases.append({
                **sim,
                "pdf_url": url_for("static", filename=f"pdfs/{sim['pdf_filename']}") if sim.get("pdf_filename") else None,
            })

        display.append({
            **r,
            "pdf_url": url_for("static", filename=f"pdfs/{r['pdf_filename']}"),
            "title_html": html_highlight(r["title"], terms),
            "case_number_html": html_highlight(r["case_number"], terms),
            "court_html": html_highlight(r["court"], terms),
            "outcome_html": html_highlight(r["outcome"], terms),
            "judges_html": html_highlight(r["judges_text"], terms),
            "summary_html": html_highlight(r.get("summary", ""), terms),
            "snippets": [html_highlight(s, terms) for s in snippets],
            "similar_cases": similar_cases,
        })

    return render_template(
        "index.html",
        results=display,
        query=query,
        court_filter=court_filter,
        outcome_filter=outcome_filter,
        court_options=unique_values(rows, "court"),
        outcome_options=unique_values(rows, "outcome"),
        pager=pager,
        total_loaded=len(rows),
        load_error=APP_STATE["load_error"],
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=True)