#!/usr/bin/env python3
"""Build page-level active-matter inputs from a verified ZIP + manifest.

No model provider is called.  The caller must supply the already-downloaded,
verified intake pair; the script verifies it again before canonical ingestion.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import active_matter_intake as intake  # noqa: E402
import scripts.rebuild_case00_derived as rebuild  # noqa: E402


def rebuild_active_matter_derived(
    *, case_root: Path, source_bundle: Path, manifest: Path,
    supplements: tuple[tuple[Path, Path], ...] = (), case_id: str | None = None,
) -> dict[str, Any]:
    verified = intake.verify_active_matter_intake(source_bundle, manifest, supplements=supplements, case_id=case_id)
    root = Path(case_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    inventory_path = root / "nyscef_filing_inventory.json"
    inventory = intake.build_filing_inventory(verified)
    inventory_path.write_text(json.dumps(inventory, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    with intake.verified_pdf_directory(verified) as temporary:
        source_dir = intake.materialize_verified_pdfs(verified, Path(temporary))
        documents = rebuild.ingest_source_directory(source_dir, inventory_path)
    if not documents:
        raise intake.ActiveMatterIntakeError("no PDFs were ingested from verified intake")
    payloads = rebuild.build_derived_payloads(documents, filing_inventory=inventory)
    written = rebuild.write_derived_artifacts(root, payloads)
    provenance = intake.write_active_matter_provenance(root, verified)
    return {
        "ok": True,
        "case_id": verified.case_id,
        "document_count": len(documents),
        "page_count": len(payloads["page_records"]["pages"]),
        "inventory_path": str(inventory_path),
        "provenance_path": str(provenance),
        "written": {key: str(value) for key, value in written.items()},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-root", type=Path, required=True)
    parser.add_argument("--source-bundle", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--supplement", type=Path, nargs=2, action="append", metavar=("SOURCE_BUNDLE", "MANIFEST"), help="Verified supplement ZIP and manifest; repeat as needed.")
    parser.add_argument("--case-id")
    args = parser.parse_args(argv)
    try:
        result = rebuild_active_matter_derived(
            case_root=args.case_root,
            source_bundle=args.source_bundle,
            manifest=args.manifest,
            supplements=tuple((pair[0], pair[1]) for pair in (args.supplement or [])),
            case_id=args.case_id,
        )
    except intake.ActiveMatterIntakeError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
