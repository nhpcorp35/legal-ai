"""Opt-in, read-only production check of an authenticated cited PDF."""

import base64
import hashlib
import json
import os
import re
import sys
import urllib.parse

import boto3


CASE_RE = re.compile(r"^NY-[A-Za-z]+-[0-9]{6}-[0-9]{4}-[A-Za-z0-9-]{2,80}$")
PDF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,180}\.pdf$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_PDF_BYTES = 80 * 1048576
PROBE_NAME = "AUTHENTICATED_CITED_PDF_B2_SHA256"


def run_probe(config, app, environ=None):
    """Exercise the authenticated production route and compare to B2."""
    env = os.environ if environ is None else environ
    case_id = config.get("case_id", "")
    filename = config.get("filename", "")
    source_sha256 = config.get("source_sha256", "")
    if not (
        isinstance(case_id, str) and CASE_RE.fullmatch(case_id)
        and isinstance(filename, str) and PDF_RE.fullmatch(filename)
        and isinstance(source_sha256, str) and SHA_RE.fullmatch(source_sha256)
    ):
        raise ValueError("invalid probe identity")

    username = env["LEGALAI_REVIEW_ALLEN_USERNAME"]
    password = env["LEGALAI_REVIEW_ALLEN_PASSWORD"]
    if not username or not password:
        raise ValueError("review credentials are missing")
    path = (
        "/workspace/matters/"
        + urllib.parse.quote(case_id, safe="")
        + "/pdf/" + urllib.parse.quote(filename, safe="")
        + "?source_sha256=" + source_sha256
    )
    credentials = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    response = app.test_client().get(path, headers={"Authorization": "Basic " + credentials})
    status = response.status_code
    content_type = response.mimetype
    pdf = response.get_data()

    s3 = boto3.client(
        "s3",
        endpoint_url=env["B2_ENDPOINT"].rstrip("/"),
        region_name=env["B2_REGION"],
        aws_access_key_id=env["B2_KEY_ID"],
        aws_secret_access_key=env["B2_APPLICATION_KEY"],
    )
    key = f"cases/{case_id}/intake/source/{source_sha256}/contents_manifest.json"
    object_body = s3.get_object(Bucket=env["B2_BUCKET"], Key=key)["Body"]
    try:
        manifest = json.loads(object_body.read())
    finally:
        object_body.close()
    matches = [
        entry for entry in manifest["files"]
        if isinstance(entry, dict) and entry.get("filename", "").rsplit("/", 1)[-1] == filename
    ]
    if len(matches) != 1 or not SHA_RE.fullmatch(str(matches[0].get("sha256", ""))):
        raise ValueError("manifest member is missing or ambiguous")
    actual = hashlib.sha256(pdf).hexdigest()
    if not (
        status == 200 and content_type == "application/pdf"
        and pdf.startswith(b"%PDF-") and len(pdf) <= MAX_PDF_BYTES
        and actual == matches[0]["sha256"]
    ):
        raise ValueError("authenticated PDF did not match canonical B2 manifest")
    return {
        "probe": PROBE_NAME,
        "ok": True,
        "http_status": status,
        "pdf_bytes": len(pdf),
        "pdf_sha256": actual,
        "source_sha256": source_sha256,
        "manifest_match": True,
    }


def emit_configured_probe(app):
    """Log one bounded result at startup; never log credentials or PDF text."""
    raw_config = os.environ.get("LEGALAI_READONLY_PDF_PROBE_JSON", "")
    if not raw_config:
        return
    try:
        result = run_probe(json.loads(raw_config), app)
    except Exception as exc:
        result = {"probe": PROBE_NAME, "ok": False, "error_type": type(exc).__name__}
    sys.stderr.write("LEGALAI_PDF_PROBE " + json.dumps(result, sort_keys=True) + "\n")
    sys.stderr.flush()
