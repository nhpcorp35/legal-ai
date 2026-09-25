#!/usr/bin/env python3
"""Read-only cross-case retrieval regression checks; never calls a model."""

from __future__ import annotations

import json

from scripts.run_verified_case_draft import (
    classify_page,
    client,
    evidence,
    load_reviewed_authorities,
    pre_generation_checks,
)

RENNICK_CASE_ID = "NY-Nassau-613561-2026-Desousa-v-Rennick"
SZYMCZYK_CASE_ID = "NY-NewYork-158068-2018-Szymczyk-v-Hudson-36-37"

REGRESSION_TARGETS = (
    {
        "name": "rennick_motion_recommendation",
        "case_id": RENNICK_CASE_ID,
        "question": "I need to make a motion. Which motions should I consider?",
        "minimum_authority_count": 10,
        "required_source_types": (
            "expert_opinion",
            "regulatory_record",
            "visual_or_measurement_evidence",
        ),
    },
    {
        "name": "rennick_motion_response",
        "case_id": RENNICK_CASE_ID,
        "question": "My opponent made a motion. How should I answer it?",
        "minimum_authority_count": 10,
        "required_source_types": (
            "expert_opinion",
            "regulatory_record",
            "visual_or_measurement_evidence",
        ),
    },
    {
        "name": "szymczyk_main_action",
        "case_id": SZYMCZYK_CASE_ID,
        "question": (
            "Identify the plaintiffs claims in the main action against the defendants "
            "including defenses requested relief death substitution jurisdiction and "
            "summary judgment procedural disposition"
        ),
        "minimum_authority_count": 0,
        "required_source_types": ("pleading",),
    },
)


def evaluate_target(target, pages, authorities, coverage):
    """Validate one selected verified-record set without generating text."""
    preflight = pre_generation_checks(
        pages, authorities, target["question"], coverage
    )
    source_types = sorted({classify_page(page)["source_type"] for page in pages})
    missing_types = sorted(set(target["required_source_types"]) - set(source_types))
    if missing_types:
        raise AssertionError(
            target["name"] + " missing required source types: " + ", ".join(missing_types)
        )
    if len(authorities) < target["minimum_authority_count"]:
        raise AssertionError(
            target["name"] + " has too few reviewed authorities: "
            + str(len(authorities))
        )
    return {
        "case_id": target["case_id"],
        "selected_page_count": len(pages),
        "source_types": source_types,
        "reviewed_authority_count": len(authorities),
        "pre_generation_check": preflight,
    }


def main():
    s3 = client()
    results = {}
    for target in REGRESSION_TARGETS:
        selection = evidence(s3, target["case_id"], target["question"])
        pages = list(selection)
        authorities = load_reviewed_authorities(s3, target["case_id"])
        results[target["name"]] = evaluate_target(
            target, pages, authorities, getattr(selection, "coverage", {})
        )
    print(json.dumps({
        "result": "LEGALAI_CROSS_CASE_RETRIEVAL_REGRESSION_VERIFIED",
        "model_called": False,
        "draft_created": False,
        "b2_write": False,
        "targets": results,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
