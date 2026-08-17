#!/usr/bin/env python3
"""Privately derive and publish the canonical Case-00 Q1 acceptance contract."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from openai import OpenAI

import acceptance_contract as ac
from scripts import rebuild_case00_derived as rebuild
from scripts.run_case00_b2_q1 import (
    CANONICAL_ATTORNEY_REVIEW_PACKET_OBJECT_KEY,
    CANONICAL_ATTORNEY_REVIEW_PACKET_SHA256,
    CANONICAL_ATTORNEY_REVIEW_PACKET_SIZE,
    verify_canonical_packet_bytes,
)

BENCHMARK_ID = "Case-00-Triborough"
QUESTION_ID = "Q1"
CONTRACT_ID = "case00-triborough-q1"
VERSION = "1.0.0"
VERSION_TOKEN = "v1.0.0"
OBJECT_KEY = (
    "Benchmarks/acceptance-contracts/case-00-triborough/Q1/"
    "case00-triborough-q1/v1.0.0/acceptance_contract.json"
)


def extract_q1_section(markdown: str) -> str:
    match = re.search(r"(?ms)^## Q1\.\s+.*?(?=^## Q[2-9][0-9]*\.|\Z)", markdown)
    if match is None:
        raise ValueError("canonical packet does not contain a bounded Q1 section")
    section = match.group(0).strip()
    if not section:
        raise ValueError("canonical packet Q1 section is empty")
    return section


def _json_object(text: str) -> dict[str, Any]:
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("contract derivation response must be a JSON object")
    return value


def semantic_payload_json_schema() -> dict[str, Any]:
    full = ac.acceptance_contract_json_schema()
    names = ("required_criterion_ids", "evidence_constraints", "semantic_preservation", "duplication_rules", "criteria", "structure_requirements")
    schema = {"type": "object", "additionalProperties": False, "required": list(names), "properties": {name: full["properties"][name] for name in names}}

    def strictify(node: Any) -> Any:
        if isinstance(node, list):
            return [strictify(item) for item in node]
        if not isinstance(node, dict):
            return node
        out = {key: strictify(value) for key, value in node.items()}
        properties = out.get("properties")
        if out.get("type") == "object" and isinstance(properties, dict):
            out["additionalProperties"] = False
            out["required"] = list(properties)
        return out

    return strictify(schema)

def derive_semantic_payload(section: str, *, model: str) -> dict[str, Any]:
    response = OpenAI().chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_schema", "json_schema": {"name": "case00_q1_acceptance_payload", "strict": True, "schema": semantic_payload_json_schema()}},
        messages=[
            {
                "role": "system",
                "content": (
                    "Convert the supplied attorney-approved Q1 benchmark section into a strict "
                    "machine-readable acceptance policy. Extract only requirements supported by "
                    "that section; do not add legal propositions. Return JSON with exactly: "
                    "required_criterion_ids (nonempty unique strings), evidence_constraints "
                    "(allowed_source_types, require_page_citations, max_excerpts_per_criterion), "
                    "semantic_preservation (require_same_party_roles, forbid_material_omissions, "
                    "require_preserve_negation), duplication_rules (forbid_duplicate_criterion_ids, "
                    "forbid_overlapping_evidence_spans, max_duplicate_phrase_ratio), criteria, and "
                    "structure_requirements. Each criterion must contain id, presence_phrases, "
                    "evidence_phrases, semantic_required_phrases, semantic_forbidden_phrases, "
                    "fallback_text, and category. Preserve attorney meaning verbatim where possible."
                ),
            },
            {"role": "user", "content": section},
        ],
    )
    content = response.choices[0].message.content
    if not content:
        raise ValueError("contract derivation returned empty content")
    return _json_object(content)


def build_contract(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "required_criterion_ids",
        "evidence_constraints",
        "semantic_preservation",
        "duplication_rules",
        "criteria",
        "structure_requirements",
    }
    if set(payload) != allowed:
        raise ValueError("contract derivation returned unexpected top-level fields")
    document = {
        "schema_version": ac.SCHEMA_VERSION,
        "contract_id": CONTRACT_ID,
        "version": VERSION,
        "identity": {"benchmark_id": BENCHMARK_ID, "question_id": QUESTION_ID},
        **payload,
        "object_key": OBJECT_KEY,
    }
    document["content_sha256"] = ac.compute_content_sha256(document)
    diagnostics = ac.validate_acceptance_contract_schema(document)
    if diagnostics:
        raise ValueError("derived contract failed strict schema validation")
    return document


def publish(*, model: str) -> dict[str, Any]:
    config = rebuild.B2Config.from_env()
    client = rebuild.create_b2_client(config)
    packet = client.get_object(
        Bucket=config.bucket, Key=CANONICAL_ATTORNEY_REVIEW_PACKET_OBJECT_KEY
    )["Body"].read()
    verify_canonical_packet_bytes(
        packet,
        expected_size=CANONICAL_ATTORNEY_REVIEW_PACKET_SIZE,
        expected_sha256=CANONICAL_ATTORNEY_REVIEW_PACKET_SHA256,
    )
    section = extract_q1_section(packet.decode("utf-8"))
    document = build_contract(derive_semantic_payload(section, model=model))
    body = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    client.put_object(
        Bucket=config.bucket,
        Key=OBJECT_KEY,
        Body=body,
        ContentType="application/json",
        Metadata={"content-sha256": document["content_sha256"]},
    )
    head = client.head_object(Bucket=config.bucket, Key=OBJECT_KEY)
    if int(head.get("ContentLength", -1)) != len(body):
        raise RuntimeError("published contract size verification failed")
    verified = ac.load_acceptance_contract_from_b2(
        client=client,
        bucket=config.bucket,
        object_key=OBJECT_KEY,
        expected_identity=ac.ContractIdentity(BENCHMARK_ID, QUESTION_ID),
        expected_content_sha256=document["content_sha256"],
    )
    if not verified.ok:
        raise RuntimeError("published contract authentication failed")
    return {
        "ok": True,
        "object_key": OBJECT_KEY,
        "version": VERSION_TOKEN,
        "content_sha256": document["content_sha256"],
        "size": len(body),
        "criterion_count": len(document["required_criterion_ids"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authorization-confirmed", action="store_true", required=True)
    parser.add_argument("--model", default=os.environ.get("LEGALAI_ACCEPTANCE_CONTRACT_MODEL", "gpt-5.1"))
    args = parser.parse_args()
    if not args.authorization_confirmed:
        return 2
    print(json.dumps(publish(model=args.model), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
