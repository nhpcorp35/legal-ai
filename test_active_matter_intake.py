"""Focused regression coverage for verified active-matter intake."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import active_matter_intake as intake


CASE_ID = "NY-Nassau-613561-2026-Desousa-v-Rennick"
PDF_NAME = "613561_2026_MICHAEL_DESOUSA_et_al_v_GEORGE_RENNICK_et_al_COMPLAINT_2.pdf"
PDF_BYTES = b"%PDF-1.4\nsynthetic test bytes\n%%EOF\n"


def _make_pair(root: Path, *, contents: bytes = PDF_BYTES) -> tuple[Path, Path]:
    source = root / "source.zip"
    manifest = root / "manifest.json"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("RENNICK/" + PDF_NAME, contents)
    manifest.write_text(
        json.dumps(
            {
                "case_id": CASE_ID,
                "documents": [
                    {
                        "filename": PDF_NAME,
                        "size_bytes": len(contents),
                        "sha256": hashlib.sha256(contents).hexdigest(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return source, manifest


class VerifiedIntakeTests(unittest.TestCase):
    def test_verifies_and_materializes_exact_manifest_pair(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, manifest = _make_pair(root)
            verified = intake.verify_intake_bundle(source, manifest)
            self.assertEqual(verified.case_id, CASE_ID)
            self.assertEqual(len(verified.documents), 1)
            destination = intake.materialize_verified_pdfs(verified, root / "pdfs")
            self.assertEqual((destination / PDF_NAME).read_bytes(), PDF_BYTES)
            inventory = intake.build_filing_inventory(verified)
            self.assertEqual(inventory["filings"][0]["nyscef_document_number"], 2)

    def test_rejects_manifest_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, manifest = _make_pair(root)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["documents"][0]["sha256"] = "0" * 64
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(intake.ActiveMatterIntakeError, "SHA-256 mismatch"):
                intake.verify_intake_bundle(source, manifest)

    def test_rejects_unmanifested_archive_member(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, manifest = _make_pair(root)
            with zipfile.ZipFile(source, "a") as archive:
                archive.writestr("RENNICK/extra.pdf", PDF_BYTES)
            with self.assertRaisesRegex(intake.ActiveMatterIntakeError, "unmanifested"):
                intake.verify_intake_bundle(source, manifest)

    def test_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, manifest = _make_pair(root)
            with zipfile.ZipFile(source, "a") as archive:
                archive.writestr("../" + PDF_NAME, PDF_BYTES)
            with self.assertRaisesRegex(intake.ActiveMatterIntakeError, "unsafe path"):
                intake.verify_intake_bundle(source, manifest)

    def test_combines_verified_supplement(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, manifest = _make_pair(root)
            supplement_name = PDF_NAME.replace("_2.pdf", "_18.pdf")
            supplement = root / "supplement.zip"
            supplement_manifest = root / "supplement.json"
            with zipfile.ZipFile(supplement, "w") as archive:
                archive.writestr("SUPPLEMENT/" + supplement_name, PDF_BYTES)
            supplement_manifest.write_text(json.dumps({"case_id": CASE_ID, "documents": [{"filename": supplement_name, "size": len(PDF_BYTES), "sha256": hashlib.sha256(PDF_BYTES).hexdigest()}]}), encoding="utf-8")
            verified = intake.verify_active_matter_intake(source, manifest, supplements=((supplement, supplement_manifest),))
            self.assertEqual(len(verified.documents), 2)
            output = intake.materialize_verified_pdfs(verified, root / "pdfs")
            self.assertEqual(len(list(output.glob("*.pdf"))), 2)
