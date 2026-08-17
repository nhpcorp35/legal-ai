"""Privacy-safe Case-00 Q1 role-vocabulary diagnostic.

Prints aggregate counts for a fixed role taxonomy only. Never emits source text,
party names, page identifiers, filenames, object bodies, or credentials.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

import run_case00_b2_q1 as case_cli  # noqa: E402

ROLE_TERMS = (
    "insurer",
    "underwriter",
    "named insured",
    "additional insured",
    "insured",
    "insurance carrier",
    "owner",
    "property owner",
    "contractor",
    "general contractor",
    "subcontractor",
    "tenant",
    "landlord",
    "lessor",
    "lessee",
    "broker",
    "agent",
    "managing agent",
    "manager",
    "property manager",
    "operator",
    "developer",
    "employer",
    "employee",
    "seller",
    "purchaser",
)
RELATED_CUES = (
    "underlying action",
    "underlying case",
    "underlying litigation",
    "related action",
    "related case",
    "related litigation",
    "separate action",
    "separate case",
    "separate litigation",
    "third-party action",
    "third party action",
)
PROCEDURAL_ROLES = (
    "plaintiff",
    "defendant",
    "third-party plaintiff",
    "third party plaintiff",
    "third-party defendant",
    "third party defendant",
    "appellant",
    "respondent on appeal",
)


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)


def _counts(text: str, terms: tuple[str, ...]) -> dict[str, int]:
    lowered = text.lower()
    return {
        term: len(re.findall(r"(?<![a-z])" + re.escape(term) + r"(?![a-z])", lowered))
        for term in terms
        if re.search(r"(?<![a-z])" + re.escape(term) + r"(?![a-z])", lowered)
    }


def report_case_root(
    root: Path,
    *,
    benchmark_id: str = "Case-00-Triborough",
    question_id: str = "Q1",
) -> dict:
    page_records = json.loads(
        (root / "derived/page-extraction/canonical_page_records.json").read_text(
            encoding="utf-8"
        )
    )
    spec = case_cli.resolve_canonical_acceptance_contract_spec(
        benchmark_id=benchmark_id,
        question_id=question_id,
    )
    contract_bytes = case_cli.download_canonical_acceptance_contract_bytes(
        object_key=spec["object_key"]
    )
    contract = json.loads(contract_bytes.decode("utf-8"))
    evidence_text = "\n".join(_strings(page_records))
    contract_text = "\n".join(_strings(contract))
    return {
        "ok": True,
        "benchmark_id": benchmark_id,
        "question_id": question_id,
        "privacy": "aggregate_allowlisted_vocabulary_only",
        "evidence": {
            "role_terms": _counts(evidence_text, ROLE_TERMS),
            "related_cues": _counts(evidence_text, RELATED_CUES),
            "procedural_roles": _counts(evidence_text, PROCEDURAL_ROLES),
        },
        "acceptance_contract": {
            "role_terms": _counts(contract_text, ROLE_TERMS),
            "related_cues": _counts(contract_text, RELATED_CUES),
            "procedural_roles": _counts(contract_text, PROCEDURAL_ROLES),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark-id", default="Case-00-Triborough")
    parser.add_argument("--question-id", default="Q1")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="case00-role-diagnostic-") as tmp:
        root = Path(tmp)
        subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "rebuild_case00_derived.py"),
                "--case-root",
                str(root),
                "--b2-prefix",
            ],
            cwd=REPO_ROOT,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=os.environ.copy(),
        )
        print(
            json.dumps(
                report_case_root(
                    root,
                    benchmark_id=args.benchmark_id,
                    question_id=args.question_id,
                ),
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
