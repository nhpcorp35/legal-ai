#!/usr/bin/env python3
"""Generate a cited case-map candidate from immutable verified page records.

The script is deliberately narrow: it selects a fixed small evidence packet,
requires filename/page citations with literal quotes, and refuses to render a
packet until ``verified_case_review`` proves every quote exists in the record.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from verified_case_review import render_packet, validate_candidate, load_page_index  # noqa: E402

QUESTION = "What are the parties, claims, defenses, and requested relief shown in the verified record?"
TERMS = ("complaint", "plaintiff", "defendant", "cause of action", "wherefore", "answer", "affirmative defense")


def select_pages(records_path: Path, limit: int = 24) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    scored = []
    for row in rows:
        text, filename = str(row.get("text", "")), str(row.get("filename", ""))
        if not text or not filename or not isinstance(row.get("page_number"), int):
            continue
        lowered = text.casefold()
        score = sum(lowered.count(term) for term in TERMS)
        score += 3 if any(term in filename.casefold() for term in ("complaint", "answer", "order")) else 0
        if score:
            scored.append((score, filename, row["page_number"], {"filename": filename, "page_number": row["page_number"], "text": re.sub(r"\s+", " ", text)[:1800]}))
    return [row for _, _, _, row in sorted(scored, key=lambda item: (-item[0], item[1], item[2]))[:limit]]


def build_request(case_id: str, pages: list[dict[str, Any]]) -> dict[str, Any]:
    schema = {"type":"object","additionalProperties":False,"required":["case_id","question","proposed_answer","findings","unresolved_questions","limitations"],"properties":{"case_id":{"type":"string"},"question":{"type":"string"},"proposed_answer":{"type":"string"},"findings":{"type":"array","minItems":1,"items":{"type":"object","additionalProperties":False,"required":["statement","evidence"],"properties":{"statement":{"type":"string"},"evidence":{"type":"array","minItems":1,"items":{"type":"object","additionalProperties":False,"required":["filename","page_number","quote"],"properties":{"filename":{"type":"string"},"page_number":{"type":"integer","minimum":1},"quote":{"type":"string","minLength":12}}}}}}},"unresolved_questions":{"type":"array","items":{"type":"string"}},"limitations":{"type":"string"}}}
    prompt = {"question": QUESTION, "case_id": case_id, "instructions": "Use only these verified pages. Do not infer missing facts. Every finding needs one or more literal, at-least-12-character quotes. If a category is unsupported, put it in unresolved_questions.", "pages": pages}
    return {"model": os.environ.get("LEGALAI_OPENAI_MODEL", "gpt-5.6-sol"), "instructions": "You are a careful legal-record analyst. Return only strict JSON matching the schema.", "input": json.dumps(prompt), "text": {"format": {"type":"json_schema", "name":"verified_case_map", "strict":True, "schema":schema}}}


def call_model(payload: dict[str, Any]) -> dict[str, Any]:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is required for the paid generation step")
    request = urllib.request.Request("https://api.openai.com/v1/responses", data=json.dumps(payload).encode(), headers={"Authorization": f"Bearer {key}", "Content-Type":"application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=180) as response:
        body = json.loads(response.read().decode())
    text = body.get("output_text")
    if not isinstance(text, str):
        raise RuntimeError("model response did not contain structured output")
    return json.loads(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--page-records", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    pages = select_pages(args.page_records)
    if not pages:
        raise SystemExit("no suitable verified pages found")
    if args.dry_run:
        print(json.dumps({"ok": True, "selected_pages": [{"filename": p["filename"], "page_number": p["page_number"]} for p in pages]}, sort_keys=True))
        return 0
    candidate = call_model(build_request(args.case_id, pages))
    checked = validate_candidate(candidate, load_page_index(args.page_records))
    args.output.write_text(render_packet(checked), encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(args.output), "findings": len(checked["findings"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
