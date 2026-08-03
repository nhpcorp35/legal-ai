#!/usr/bin/env python3
"""CLI for Case-00 Triborough attorney-feedback evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from case00_attorney_eval.evaluate import (
    ANSWER_VERSION_CANDIDATE,
    ANSWER_VERSION_ORIGINAL,
    evaluate_case00,
    format_human_summary,
    write_evaluation_outputs,
)
from case00_attorney_eval import paths as pathmod


def _load_candidates(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("Candidate answers file must be a JSON object of QID -> text")
    return {str(k): str(v) for k, v in data.items()}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Run Case-00 Triborough attorney-feedback evaluation against "
            "existing gold-label / packet / provisional artifacts."
        )
    )
    p.add_argument(
        "--case00-root",
        type=Path,
        default=None,
        help=(
            "Case-00 corpus root (default: $CASE00_TRIBOROUGH_ROOT or "
            "/app/data/case-00-triborough)."
        ),
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help=(
            "Output directory for machine-readable JSON and human summary "
            f"(default: $CASE00_ATTORNEY_EVAL_OUT or "
            f"{pathmod.DEFAULT_VOLUME_ROOT}/derived/attorney-feedback-eval)."
        ),
    )
    p.add_argument(
        "--candidate-answers",
        type=Path,
        default=None,
        help=(
            "Optional JSON object mapping question_id -> new LegalAI answer text. "
            "Original answers remain preserved in the evaluation record."
        ),
    )
    p.add_argument(
        "--answer-version",
        choices=(ANSWER_VERSION_ORIGINAL, ANSWER_VERSION_CANDIDATE),
        default=ANSWER_VERSION_ORIGINAL,
        help="Which answer version label to apply when no candidates are supplied.",
    )
    p.add_argument(
        "--stdout-json",
        action="store_true",
        help="Also print the full JSON result to stdout.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    candidates = _load_candidates(args.candidate_answers)
    result = evaluate_case00(
        args.case00_root,
        candidate_answers=candidates or None,
        answer_version=args.answer_version,
    )
    paths = write_evaluation_outputs(result, args.out)
    summary = format_human_summary(result)
    sys.stdout.write(summary)
    sys.stdout.write(f"\nWrote JSON: {paths['json']}\n")
    sys.stdout.write(f"Wrote summary: {paths['summary']}\n")
    if args.stdout_json:
        sys.stdout.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
