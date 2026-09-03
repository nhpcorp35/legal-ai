Warning: truncated output (original token count: 19498)
Total output lines: 2468

from flask import Flask, request, render_template, abort, send_from_directory, Response, send_file, render_template_string
import base64
from io import BytesIO
import hashlib
import hmac
import json
import math
import os
import csv
import re
import urllib.error
import urllib.parse
import urllib.request
from types import SimpleNamespace

from matter_builder import get_matter

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
CASE00_REVIEW_QUESTIONS = {
    "Q4": "Coverage positions and defenses",
    "Q5": "Attorney review",
}


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
        retur…18498 tokens truncated…for_review_display(packet),
    )


@app.route("/szymczyk/feedback/latest")
def szymczyk_latest_feedback():
    if basic_review_user() is None:
        return basic_auth_required_response()
    feedback = read_latest_szymczyk_feedback()
    if feedback is None:
        abort(503)
    return render_template_string(
        """<!doctype html><title>Szymczyk Attorney Feedback</title>
        <main><h1>Szymczyk Attorney Feedback</h1>
        <p><strong>Archived feedback — read-only.</strong></p>
        <p>Submitted: {{ submitted_at }}</p>
        <pre style="white-space:pre-wrap;overflow-wrap:anywhere">{{ feedback_markdown }}</pre></main>""",
        submitted_at=feedback.get("submitted_at", ""),
        feedback_markdown=feedback.get("feedback_markdown", ""),
    )


@app.route("/case-00/review/feedback/q5.pdf")
def case00_q5_feedback_pdf():
    if basic_review_user() is None:
        return basic_auth_required_response()
    feedback = read_case00_feedback("Q5")
    if feedback is None:
        abort(503)
    try:
        pdf = feedback_pdf_bytes("Q5", feedback)
    except ImportError:
        abort(503)
    return send_file(
        BytesIO(pdf),
        mimetype="application/pdf",
        as_attachment=True,
        download_name="Case-00_Q5_John-Cuomo_Feedback.pdf",
    )


@app.route("/pdf/<path:filename>")
def serve_pdf(filename):
    return send_from_directory(os.path.join(BASE_DIR, "data", "pdfs"), filename)


@app.route("/case/<path:case_id>")
def case_detail(case_id):
    cases = load_cases()
    case = find_case_by_id(case_id, cases)
    if not case:
        abort(404)

    score_case(case, "", "All Courts", "All Outcomes")
    case["display_snippet"] = case.get("formatted_text") or case.get("text") or ""
    case["similar_cases"] = get_similar_cases(case, cases, limit=8)

    return render_template("case_detail.html", case=case)


# =========================
# RUN
# =========================

if __name__ == "__main__":
    app.run(debug=True, port=5001)
