import hashlib
import io
import json
import unittest
import zipfile

from verified_source_pdf import open_hash_verified_pdf_object, open_verified_source_pdf


CASE = "NY-Nassau-613561-2026-Desousa-v-Rennick"
PDF_NAME = "ORDER_TO_SHOW_CAUSE_32.pdf"
PDF = b"%PDF-1.4\nverified test source\n"


class Body(io.BytesIO):
    def close(self):
        pass


class FakeB2:
    def __init__(self, objects):
        self.objects = objects

    def get_object(self, *, Bucket, Key, Range=None):
        raw = self.objects[Key]["body"]
        if Range:
            start, end = (int(value) for value in Range.removeprefix("bytes=").split("-"))
            raw = raw[start:end + 1]
        return {"Body": Body(raw)}

    def head_object(self, *, Bucket, Key):
        item = self.objects[Key]
        return {"ContentLength": len(item["body"]), "Metadata": item.get("metadata", {})}


def fixture():
    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("docket/" + PDF_NAME, PDF)
    archive_bytes = bundle.getvalue()
    source_sha = hashlib.sha256(archive_bytes).hexdigest()
    prefix = f"cases/{CASE}/intake/source/{source_sha}/"
    def raw(value):
        return {"body": json.dumps(value).encode()}
    return source_sha, FakeB2({
        f"cases/{CASE}/intake/case_identity.json": raw({"source_sha256": source_sha}),
        f"cases/{CASE}/intake/source_set.json": raw({"schema_version": "verified-case-source-set.v1", "case_id": CASE, "sources": [{"source_sha256": source_sha}]}),
        prefix + "contents_manifest.json": raw({"files": [{"filename": "docket/" + PDF_NAME, "sha256": hashlib.sha256(PDF).hexdigest()}]}),
        prefix + "source_descriptor.json": raw({"source_object_key": prefix + "source.zip"}),
        prefix + "source.zip": {"body": archive_bytes, "metadata": {"sha256": source_sha}},
        "case00/test.pdf": {"body": PDF},
    })


class VerifiedSourcePdfTests(unittest.TestCase):
    def test_opens_only_manifest_listed_hash_verified_pdf(self):
        source_sha, client = fixture()
        self.assertEqual(open_verified_source_pdf(client, "bucket", CASE, source_sha, PDF_NAME), PDF)

    def test_rejects_document_not_in_manifest(self):
        source_sha, client = fixture()
        with self.assertRaisesRegex(ValueError, "manifest"):
            open_verified_source_pdf(client, "bucket", CASE, source_sha, "OTHER.pdf")

    def test_rejects_archive_digest_mismatch(self):
        source_sha, client = fixture()
        key = f"cases/{CASE}/intake/source/{source_sha}/source.zip"
        client.objects[key]["metadata"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "integrity"):
            open_verified_source_pdf(client, "bucket", CASE, source_sha, PDF_NAME)

    def test_opens_only_hash_verified_standalone_pdf(self):
        _, client = fixture()
        self.assertEqual(open_hash_verified_pdf_object(client, "bucket", "case00/test.pdf", hashlib.sha256(PDF).hexdigest(), 1024), PDF)

    def test_rejects_standalone_hash_mismatch(self):
        _, client = fixture()
        with self.assertRaisesRegex(ValueError, "integrity"):
            open_hash_verified_pdf_object(client, "bucket", "case00/test.pdf", "0" * 64, 1024)


if __name__ == "__main__":
    unittest.main()
