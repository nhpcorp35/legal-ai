#!/usr/bin/env python3
"""Rebuild Case-00 derived artifacts from B2, then generate one attorney-feedback candidate.

This wrapper intentionally runs both phases in the same checkout so the ephemeral
derived artifacts created by the rebuild are immediately available to the
production candidate generator.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

AUTHORIZATION_ACKNOWLEDGEMENT = (
    "I_AUTHORIZE_PRIVATE_EVIDENCE_TRANSMISSION_TO_MODEL_PROVIDER"
)


def _run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _emit(payload: dict) -> None:
    print(json.dumps(payload, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild Case-00 from Backblaze B2 and immediately generate one "
            "attorney-feedback candidate in the same workspace."
        )
    )
    parser.add_argument("--case-root", required=True)
    parser.add_argument("--question-id", required=True)
    parser.add_argument("--required-commit", required=True)
    parser.add_argument("--candidate-output-root", required=True)
    parser.add_argument(
        "--authorization-confirmed",
        action="store_true",
        required=True,
        help="Confirms the caller already obtained authorization to transmit private evidence.",
    )
    parser.add_argument(
        "--generation-only",
        action="store_true",
        required=True,
        help="Required safety gate; evaluation is not run by this wrapper.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    rebuild_script = repo_root / "scripts" / "rebuild_case00_derived.py"
    generator_script = repo_root / "scripts" / "generate_attorney_feedback_candidate.py"

    rebuild = _run(
        [
            sys.executable,
            str(rebuild_script),
            "--case-root",
            args.case_root,
            "--b2-prefix",
        ],
        repo_root,
    )
    if rebuild.returncode != 0:
        _emit(
            {
                "ok": False,
                "phase": "rebuild",
                "return_code": rebuild.returncode,
                "stdout": rebuild.stdout,
                "stderr": rebuild.stderr,
            }
        )
        return rebuild.returncode or 1

    generation = _run(
        [
            sys.executable,
            str(generator_script),
            "--case-root",
            args.case_root,
            "--question-id",
            args.question_id,
            "--required-commit",
            args.required_commit,
            "--candidate-output-root",
            args.candidate_output_root,
            "--authorize-private-evidence-transmission",
            AUTHORIZATION_ACKNOWLEDGEMENT,
            "--generation-only",
            "--repo-root",
            str(repo_root),
        ],
        repo_root,
    )
    if generation.returncode != 0:
        _emit(
            {
                "ok": False,
                "phase": "generation",
                "return_code": generation.returncode,
                "stdout": generation.stdout,
                "stderr": generation.stderr,
            }
        )
        return generation.returncode or 1

    _emit(
        {
            "ok": True,
            "phase": "complete",
            "rebuild_stdout": rebuild.stdout,
            "generation_stdout": generation.stdout,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
