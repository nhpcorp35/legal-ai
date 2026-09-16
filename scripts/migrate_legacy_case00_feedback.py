"""Import the August 2026 legacy Q1-Q3 review into the online B2 schema.

The migration deliberately uses deterministic archive IDs and writes each
manifest last.  A manifest is therefore the commit marker for one review, and
re-running the migration either verifies the existing review or repairs an
interrupted write without creating another history entry.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any, Mapping


SOURCE_ARCHIVE_ID = "review-20260802-2122f82dafe3"
REVIEWS_ROOT = (
    "Benchmarks/Case-00-Triborough/derived/attorney-feedback-eval/"
    "attorney-reviews"
)
SOURCE_PREFIX = f"{REVIEWS_ROOT}/{SOURCE_ARCHIVE_ID}/"
PACKET_FILENAME = "attorney_review_packet_02-original.md"
FEEDBACK_FILENAME = "John-Cuomo-Case00-Attorney-Feedback-Email-2026-08-02.md"
EVALUATION_FILENAME = "John-Cuomo-Case00-Structured-Evaluation-2026-08-02.json"
MANIFEST_FILENAME = "John-Cuomo-Case00-Feedback-Preservation-Manifest.json"
RECEIVED_AT = "2026-08-02T20:41:34-04:00"
RECEIVED_AT_UTC = "2026-08-03T00:41:34+00:00"
DISPOSITIONS = {"Q1": "incorrect", "Q2": "correct", "Q3": "correct"}
DECISIONS = {"Q1": "reject", "Q2": "accept", "Q3": "accept"}
MAX_OBJECT_BYTES = 1_000_000


class MigrationError(RuntimeError):
    """Raised when source or target data cannot be safely verified."""


@dataclass(frozen=True)
class B2Config:
    bucket: str
    endpoint: str
    region: str
    key_id: str
    application_key: str

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "B2Config":
        env = os.environ if environ is None else environ
        names = (
            "B2_BUCKET",
            "B2_ENDPOINT",
            "B2_REGION",
            "B2_KEY_ID",
            "B2_APPLICATION_KEY",
        )
        missing = [name for name in names if not str(env.get(name, "")).strip()]
        if missing:
            raise MigrationError(
                "legacy feedback migration requires: " + ", ".join(missing)
            )
        return cls(
            bucket=str(env["B2_BUCKET"]),
            endpoint=str(env["B2_ENDPOINT"]).rstrip("/"),
            region=str(env["B2_REGION"]),
            key_id=str(env["B2_KEY_ID"]),
            application_key=str(env["B2_APPLICATION_KEY"]),
        )

    def __repr__(self) -> str:
        return (
            f"B2Config(bucket={self.bucket!r}, endpoint={self.endpoint!r}, "
            f"region={self.region!r}, key_id=<redacted>, "
            "application_key=<redacted>)"
        )


def create_b2_client(config: B2Config):
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=config.endpoint,
        region_name=config.region,
        aws_access_key_id=config.key_id,
        aws_secret_access_key=config.application_key,
        config=Config(retries={"max_attempts": 4, "mode": "standard"}),
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def archive_id_for(question_id: str) -> str:
    digest = _sha256(f"{SOURCE_ARCHIVE_ID}:{question_id}".encode("ascii"))[:12]
    return f"review-20260802-{digest}"


def _read_object(client, bucket: str, key: str) -> bytes:
    response = client.get_object(Bucket=bucket, Key=key)
    body = response["Body"].read(MAX_OBJECT_BYTES + 1)
    if len(body) > MAX_OBJECT_BYTES:
        raise MigrationError(f"B2 object exceeds migration limit: {key}")
    return body


def _read_optional_object(client, bucket: str, key: str) -> bytes | None:
    try:
        return _read_object(client, bucket, key)
    except Exception as exc:
        response = getattr(exc, "response", {})
        code = str(response.get("Error", {}).get("Code", ""))
        status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
            return None
        raise


def _load_json(raw: bytes, key: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MigrationError(f"invalid JSON source object: {key}") from exc
    if not isinstance(value, dict):
        raise MigrationError(f"JSON source object is not a mapping: {key}")
    return value


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _load_verified_source(client, bucket: str) -> dict[str, bytes]:
    manifest_key = SOURCE_PREFIX + MANIFEST_FILENAME
    manifest_raw = _read_object(client, bucket, manifest_key)
    manifest = _load_json(manifest_raw, manifest_key)
    if manifest.get("archive_id") != SOURCE_ARCHIVE_ID:
        raise MigrationError("legacy source manifest archive_id mismatch")

    declared = manifest.get("files")
    if not isinstance(declared, list):
        raise MigrationError("legacy source manifest has no files list")
    declarations = {
        item.get("filename"): item
        for item in declared
        if isinstance(item, dict) and isinstance(item.get("filename"), str)
    }

    result: dict[str, bytes] = {}
    for filename in (PACKET_FILENAME, FEEDBACK_FILENAME, EVALUATION_FILENAME):
        item = declarations.get(filename)
        if not isinstance(item, dict):
            raise MigrationError(f"legacy manifest omits {filename}")
        raw = _read_object(client, bucket, SOURCE_PREFIX + filename)
        if item.get("size") != len(raw) or item.get("sha256") != _sha256(raw):
            raise MigrationError(f"legacy source integrity mismatch: {filename}")
        result[filename] = raw
    return result


def _question_evaluations(source: Mapping[str, bytes]) -> dict[str, dict[str, Any]]:
    source_eval = _load_json(
        source[EVALUATION_FILENAME], SOURCE_PREFIX + EVALUATION_FILENAME
    )
    evaluations = source_eval.get("evaluations")
    if not isinstance(evaluations, list):
        raise MigrationError("legacy evaluation has no evaluations list")
    selected: dict[str, dict[str, Any]] = {}
    for item in evaluations:
        if not isinstance(item, dict):
            continue
        question_id = item.get("question_id")
        if question_id in DISPOSITIONS:
            if question_id in selected:
                raise MigrationError(f"duplicate legacy evaluation for {question_id}")
            selected[question_id] = item
    if set(selected) != set(DISPOSITIONS):
        raise MigrationError("legacy evaluation does not contain exactly Q1-Q3")
    return selected


def _target_objects(
    question_id: str,
    legacy_evaluation: Mapping[str, Any],
    source: Mapping[str, bytes],
) -> tuple[str, dict[str, bytes]]:
    archive_id = archive_id_for(question_id)
    prefix = f"{REVIEWS_ROOT}/{archive_id}/"
    evaluation = {
        "case_id": "Case-00-Triborough",
        "question_id": question_id,
        "reviewer": "John Cuomo",
        "decision": DECISIONS[question_id],
        "disposition": DISPOSITIONS[question_id],
        "received_at": RECEIVED_AT,
        "provenance": {
            "kind": "legacy_pre_online_intake",
            "source_archive_id": SOURCE_ARCHIVE_ID,
            "source_prefix": SOURCE_PREFIX,
        },
        "legacy_evaluation": legacy_evaluation,
    }
    payloads = {
        PACKET_FILENAME: source[PACKET_FILENAME],
        FEEDBACK_FILENAME: source[FEEDBACK_FILENAME],
        EVALUATION_FILENAME: _canonical_json(evaluation),
    }
    manifest = {
        "archive_id": archive_id,
        "archived_at": RECEIVED_AT_UTC,
        "archived_by": "migration:legacy-attorney-feedback",
        "canonical_storage": "Backblaze B2",
        "case_id": "Case-00-Triborough",
        "evaluation_date": "2026-08-02",
        "files": [
            {
                "filename": filename,
                "sha256": _sha256(raw),
                "size": len(raw),
            }
            for filename, raw in payloads.items()
        ],
        "provenance": "legacy_pre_online_intake",
        "question_id": question_id,
        "received_at": RECEIVED_AT,
        "reviewer": "John Cuomo",
        "schema_version": "1.0",
    }
    payloads[MANIFEST_FILENAME] = _canonical_json(manifest)
    return prefix, payloads


def _verify_payloads(
    client, bucket: str, prefix: str, payloads: Mapping[str, bytes]
) -> bool:
    for filename, expected in payloads.items():
        actual = _read_optional_object(client, bucket, prefix + filename)
        if actual is None:
            return False
        if not hashlib.sha256(actual).digest() == hashlib.sha256(expected).digest():
            raise MigrationError(f"existing target differs: {prefix}{filename}")
    return True


def migrate_legacy_feedback(client, bucket: str) -> dict[str, list[str]]:
    source = _load_verified_source(client, bucket)
    evaluations = _question_evaluations(source)
    created: list[str] = []
    unchanged: list[str] = []

    for question_id in ("Q1", "Q2", "Q3"):
        prefix, payloads = _target_objects(
            question_id, evaluations[question_id], source
        )
        existing_manifest = _read_optional_object(
            client, bucket, prefix + MANIFEST_FILENAME
        )
        if (
            existing_manifest is not None
            and existing_manifest != payloads[MANIFEST_FILENAME]
        ):
            raise MigrationError(
                f"existing target differs: {prefix}{MANIFEST_FILENAME}"
            )
        if _verify_payloads(client, bucket, prefix, payloads):
            unchanged.append(question_id)
            continue

        # The manifest is the commit marker and is always written last.
        for filename in (PACKET_FILENAME, FEEDBACK_FILENAME, EVALUATION_FILENAME):
            key = prefix + filename
            existing = _read_optional_object(client, bucket, key)
            if existing is not None and existing != payloads[filename]:
                raise MigrationError(f"partial target differs: {key}")
            if existing is None:
                client.put_object(
                    Bucket=bucket,
                    Key=key,
                    Body=payloads[filename],
                    ContentType=(
                        "application/json"
                        if filename.endswith(".json")
                        else "text/markdown; charset=utf-8"
                    ),
                    Metadata={"sha256": _sha256(payloads[filename])},
                )
        client.put_object(
            Bucket=bucket,
            Key=prefix + MANIFEST_FILENAME,
            Body=payloads[MANIFEST_FILENAME],
            ContentType="application/json",
            Metadata={"sha256": _sha256(payloads[MANIFEST_FILENAME])},
        )
        if not _verify_payloads(client, bucket, prefix, payloads):
            raise MigrationError(f"target verification failed for {question_id}")
        created.append(question_id)

    return {"created": created, "unchanged": unchanged}


def main() -> int:
    config = B2Config.from_env()
    result = migrate_legacy_feedback(create_b2_client(config), config.bucket)
    print(json.dumps({"ok": True, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
