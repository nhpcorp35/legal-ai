"""Bounded direct-B2 reads for verified LegalAI source PDFs.

The browser never receives B2 credentials.  The caller supplies the service's
already-configured B2 client; this module only returns one PDF after checking
the immutable case identity, source set, descriptor, manifest, archive digest,
and selected archive member.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from typing import Any


CASE_ID_RE = re.compile(r"^NY-[A-Za-z]+-[0-9]{6}-[0-9]{4}-[A-Za-z0-9-]{2,80}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PDF_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,180}\.pdf$")
RANGE_BLOCK_BYTES = 1_048_576
MAX_PDF_BYTES = 80 * 1_048_576


class RangeObjectReader(io.RawIOBase):
    """Seekable cached reader that bounds each B2 fetch to one MiB."""

    def __init__(self, client: Any, bucket: str, key: str, size: int) -> None:
        self._client, self._bucket, self._key, self._size = client, bucket, key, size
        self._position = 0
        self._blocks: dict[int, bytes] = {}

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._position

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            target = offset
        elif whence == io.SEEK_CUR:
            target = self._position + offset
        elif whence == io.SEEK_END:
            target = self._size + offset
        else:
            raise ValueError("invalid archive seek mode")
        if not 0 <= target <= self._size:
            raise ValueError("archive seek is outside the verified source")
        self._position = target
        return target

    def readinto(self, buffer: bytearray) -> int:
        if self._position >= self._size:
            return 0
        wanted, copied = min(len(buffer), self._size - self._position), 0
        while copied < wanted:
            index = self._position // RANGE_BLOCK_BYTES
            block = self._blocks.get(index)
            if block is None:
                start = index * RANGE_BLOCK_BYTES
                end = min(self._size - 1, start + RANGE_BLOCK_BYTES - 1)
                response = self._client.get_object(
                    Bucket=self._bucket, Key=self._key, Range=f"bytes={start}-{end}"
                )
                stream = response["Body"]
                try:
                    block = stream.read()
                finally:
                    stream.close()
                if not block:
                    raise ValueError("verified source returned an empty range")
                self._blocks[index] = block
            offset = self._position % RANGE_BLOCK_BYTES
            take = min(wanted - copied, len(block) - offset)
            if take <= 0:
                raise ValueError("verified source returned an invalid range")
            buffer[copied:copied + take] = block[offset:offset + take]
            copied += take
            self._position += take
        return copied


def _prefix(case_id: str, source_sha256: str) -> str:
    if not CASE_ID_RE.fullmatch(case_id) or not SHA256_RE.fullmatch(source_sha256):
        raise ValueError("invalid verified source identity")
    return f"cases/{case_id}/intake/source/{source_sha256}/"


def _read_json(client: Any, bucket: str, key: str) -> dict[str, Any]:
    payload = json.loads(client.get_object(Bucket=bucket, Key=key)["Body"].read())
    if not isinstance(payload, dict):
        raise ValueError("verified source metadata is invalid")
    return payload


def _verified_source_set(client: Any, bucket: str, case_id: str) -> list[str]:
    identity = _read_json(client, bucket, f"cases/{case_id}/intake/case_identity.json")
    original = identity.get("source_sha256")
    if not isinstance(original, str) or not SHA256_RE.fullmatch(original):
        raise ValueError("case has an invalid original source identity")
    try:
        source_set = _read_json(client, bucket, f"cases/{case_id}/intake/source_set.json")
    except Exception as exc:
        code = str((getattr(exc, "response", {}) or {}).get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchKey", "NotFound"}:
            return [original]
        raise
    entries = source_set.get("sources")
    if (
        source_set.get("schema_version") != "verified-case-source-set.v1"
        or source_set.get("case_id") != case_id
        or not isinstance(entries, list)
    ):
        raise ValueError("verified source set is invalid")
    digests = [entry.get("source_sha256") for entry in entries if isinstance(entry, dict)]
    if (
        not digests
        or any(not isinstance(item, str) or not SHA256_RE.fullmatch(item) for item in digests)
        or len(set(digests)) != len(digests)
        or original not in digests
    ):
        raise ValueError("verified source set is invalid")
    return digests


def _manifest_member(manifest: dict[str, Any], document_name: str) -> dict[str, Any]:
    files = manifest.get("files")
    if not isinstance(files, list):
        raise ValueError("verified contents manifest is invalid")
    matches = [
        entry for entry in files
        if isinstance(entry, dict)
        and str(entry.get("filename", "")).rsplit("/", 1)[-1] == document_name
    ]
    if len(matches) != 1:
        raise ValueError("document is not uniquely present in the verified manifest")
    return matches[0]


def open_verified_source_pdf(
    client: Any, bucket: str, case_id: str, source_sha256: str, document_name: str
) -> bytes:
    """Return one manifest-listed PDF from a hash-verified ZIP with range reads."""
    if not PDF_NAME_RE.fullmatch(document_name):
        raise ValueError("document name is invalid")
    prefix = _prefix(case_id, source_sha256)
    if source_sha256 not in _verified_source_set(client, bucket, case_id):
        raise ValueError("source is not in the verified source set")
    manifest = _read_json(client, bucket, prefix + "contents_manifest.json")
    manifest_member = _manifest_member(manifest, document_name)
    descriptor = _read_json(client, bucket, prefix + "source_descriptor.json")
    source_key = descriptor.get("source_object_key")
    if not isinstance(source_key, str) or not source_key.startswith(prefix):
        raise ValueError("verified source descriptor is invalid")
    head = client.head_object(Bucket=bucket, Key=source_key)
    size = int(head.get("ContentLength", 0))
    metadata_sha = str((head.get("Metadata") or {}).get("sha256") or "")
    if size <= 0 or metadata_sha != source_sha256:
        raise ValueError("verified source archive integrity check failed")
    try:
        reader = io.BufferedReader(RangeObjectReader(client, bucket, source_key, size))
        with zipfile.ZipFile(reader) as archive:
            members = [info for info in archive.infolist() if info.filename.rsplit("/", 1)[-1] == document_name]
            if len(members) != 1:
                raise ValueError("document is not uniquely present in the verified archive")
            member = members[0]
            if member.is_dir() or member.file_size <= 0 or member.file_size > MAX_PDF_BYTES:
                raise ValueError("selected PDF is outside the bounded reader limit")
            pdf = archive.read(member)
    except zipfile.BadZipFile as exc:
        raise ValueError("verified source is not a readable ZIP archive") from exc
    if not pdf.startswith(b"%PDF-"):
        raise ValueError("selected archive member is not a PDF")
    expected_pdf_sha = manifest_member.get("sha256")
    if isinstance(expected_pdf_sha, str) and SHA256_RE.fullmatch(expected_pdf_sha):
        if hashlib.sha256(pdf).hexdigest() != expected_pdf_sha:
            raise ValueError("selected PDF does not match the verified manifest")
    return pdf


def open_hash_verified_pdf_object(
    client: Any, bucket: str, key: str, expected_sha256: str, max_bytes: int
) -> bytes:
    """Return a bounded standalone PDF only after streaming its exact digest."""
    if not SHA256_RE.fullmatch(expected_sha256) or not isinstance(key, str) or not key:
        raise ValueError("invalid standalone source identity")
    stream = client.get_object(Bucket=bucket, Key=key)["Body"]
    try:
        pdf = stream.read(max_bytes + 1)
    finally:
        stream.close()
    if len(pdf) == 0 or len(pdf) > max_bytes or not pdf.startswith(b"%PDF-"):
        raise ValueError("standalone source is not a bounded PDF")
    if hashlib.sha256(pdf).hexdigest() != expected_sha256:
        raise ValueError("standalone source integrity check failed")
    return pdf
