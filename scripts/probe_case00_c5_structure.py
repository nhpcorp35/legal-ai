#!/usr/bin/env python3
"""Report privacy-safe C5 token topology from the Case-00 derived page cache."""

from __future__ import annotations

import hashlib
import itertools
import json
import re
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import rebuild_case00_derived as rebuild  # noqa: E402

CACHE_INPUTS = (
    Path("data/case-00-triborough/nyscef_filing_inventory.json"),
    Path("matter_builder.py"),
    Path("complaint_structure.py"),
    Path("scripts/rebuild_case00_derived.py"),
)
PAGE_RECORDS_PATH = Path(
    "derived/page-extraction/canonical_page_records.json"
)
TOKEN_PATTERNS = {
    "action_1": re.compile(r"\baction\s+(?:no\.?|number)\s*:?[\s]*1\b", re.I),
    "action_2": re.compile(r"\baction\s+(?:no\.?|number)\s*:?[\s]*2\b", re.I),
    "plaintiff": re.compile(r"\bplaintiffs?\b", re.I),
    "defendant": re.compile(r"\bdefendants?\b", re.I),
}


def derived_cache_prefix(repo_root: Path = REPO_ROOT) -> str:
    digest = hashlib.sha256()
    for relative_path in CACHE_INPUTS:
        path = repo_root / relative_path
        digest.update(relative_path.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return (
        "Benchmarks/Case-00-Triborough/derived/runtime-cache/"
        f"{digest.hexdigest()}/"
    )


def page_topology(page: dict) -> dict | None:
    text = str(page.get("text") or page.get("page_text") or "")
    matches = {
        label: list(pattern.finditer(text))
        for label, pattern in TOKEN_PATTERNS.items()
    }
    if any(not rows for rows in matches.values()):
        return None

    best = None
    for combination in itertools.product(*(matches[label] for label in TOKEN_PATTERNS)):
        start = min(match.start() for match in combination)
        end = max(match.end() for match in combination)
        candidate = (end - start, start, end, combination)
        if best is None or candidate[:3] < best[:3]:
            best = candidate
    assert best is not None
    span_length, start, end, combination = best
    ordered = sorted(
        zip(TOKEN_PATTERNS, combination), key=lambda item: item[1].start()
    )
    span = text[start:end]
    return {
        "page_id": str(page.get("page_id") or ""),
        "minimum_covering_span_characters": span_length,
        "token_order": [label for label, _match in ordered],
        "period_count": span.count("."),
        "newline_count": span.count("\n"),
        "within_200_chars": span_length <= 200,
        "within_400_chars": span_length <= 400,
        "within_800_chars": span_length <= 800,
    }


def build_report(page_records: dict) -> dict:
    rows = [
        row
        for page in page_records.get("pages") or []
        if isinstance(page, dict) and (row := page_topology(page)) is not None
    ]
    rows.sort(key=lambda row: row["page_id"])
    return {
        "schema_version": "case00_c5_structure_probe.v1",
        "matched_page_count": len(rows),
        "pages": rows,
    }


def main(*, cache_digest: str | None = None) -> int:
    if cache_digest is not None and not re.fullmatch(r"[0-9a-f]{64}", cache_digest):
        raise ValueError("cache_digest must be exactly 64 lowercase hex characters")
    import boto3
    config = rebuild.B2Config.from_env()
    client = boto3.client(
        "s3",
        endpoint_url=config.endpoint.rstrip("/"),
        region_name=config.region,
        aws_access_key_id=config.key_id,
        aws_secret_access_key=config.application_key,
    )
    with tempfile.TemporaryDirectory(prefix="case00-c5-probe-") as temp_dir:
        destination = Path(temp_dir) / PAGE_RECORDS_PATH.name
        rebuild.download_b2_file(
            client,
            config.bucket,
            (
                "Benchmarks/Case-00-Triborough/derived/runtime-cache/"
                f"{cache_digest}/"
                if cache_digest is not None
                else derived_cache_prefix()
            )
            + PAGE_RECORDS_PATH.as_posix(),
            destination,
        )
        page_records = json.loads(destination.read_text(encoding="utf-8"))
    print(json.dumps(build_report(page_records), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
