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

    with open(CSV_PATH, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        for i, r in enumerate(reader):
            case_number = normalize_space(r.get("case_number", ""))

            pdf_file = None
            for p in PDF_DIR.glob("*.pdf"):
                if p.name.startswith(case_number):
                    pdf_file = p.name
                    break

            if not pdf_file:
                continue

            title = normalize_space(r.get("case_name", ""))
            if not title:
                title = normalize_space(r.get("summary", ""))[:120]
            if not title:
                title = case_number or "Untitled case"

            full_text = r.get("full_text", "")

            metadata_blob = normalize_text(
                " ".join([
                    title,
                    r.get("court", ""),
                    r.get("outcome", ""),
                    r.get("judges", ""),
                    r.get("summary", ""),
                    case_number,
                ])
            )

            rows.append({
                "id": i,
                "case_number": case_number,
                "title": title,
                "court": r.get("court", ""),
                "outcome": r.get("outcome", ""),
                "judges_text": r.get("judges", ""),
                "summary": r.get("summary", ""),
                "pdf_filename": pdf_file,
                "full_text": full_text,
                "full_text_norm": normalize_text(full_text),
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
# Ranking
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


def search_rows(rows, query):
    if not query:
        return rows

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
    page = safe_int(request.args.get("page", "1"))

    rows = get_rows()
    filtered = search_rows(rows, query)
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
        pager=pager,
        total_loaded=len(rows),
        load_error=APP_STATE["load_error"],
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)