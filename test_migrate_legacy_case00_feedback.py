"""Regression tests for the runtime legacy attorney-feedback migration."""

from __future__ import annotations

import hashlib
import json
import unittest
from io import BytesIO

from botocore.exceptions import ClientError

from scripts import migrate_legacy_case00_feedback as migration


class FakeB2:
    def __init__(self, objects: dict[str, bytes]):
        self.objects = dict(objects)
        self.puts: list[str] = []

    def get_object(self, *, Bucket, Key):
        del Bucket
        if Key not in self.objects:
            raise ClientError(
                {
                    "Error": {"Code": "NoSuchKey", "Message": "missing"},
                    "ResponseMetadata": {"HTTPStatusCode": 404},
                },
                "GetObject",
            )
        return {"Body": BytesIO(self.objects[Key])}

    def put_object(self, *, Bucket, Key, Body, ContentType, Metadata):
        del Bucket, ContentType
        raw = bytes(Body)
        assert Metadata["sha256"] == hashlib.sha256(raw).hexdigest()
        self.objects[Key] = raw
        self.puts.append(Key)
        return {"ETag": '"fixture"'}


def canonical_json(value) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def source_objects() -> dict[str, bytes]:
    payloads = {
        migration.PACKET_FILENAME: b"# Private packet fixture\n",
        migration.FEEDBACK_FILENAME: b"Full private feedback fixture\n",
        migration.EVALUATION_FILENAME: canonical_json(
            {
                "evaluations": [
                    {
                        "question_id": question_id,
                        "normalized_status": f"legacy-{question_id}",
                        "reviewer_wording": f"private {question_id} fixture",
                    }
                    for question_id in ("Q1", "Q2", "Q3", "Q4", "Q5")
                ]
            }
        ),
    }
    manifest = {
        "archive_id": migration.SOURCE_ARCHIVE_ID,
        "files": [
            {
                "filename": filename,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size": len(raw),
            }
            for filename, raw in payloads.items()
        ],
    }
    return {
        **{
            migration.SOURCE_PREFIX + filename: raw
            for filename, raw in payloads.items()
        },
        migration.SOURCE_PREFIX + migration.MANIFEST_FILENAME: canonical_json(
            manifest
        ),
    }


class LegacyFeedbackMigrationTests(unittest.TestCase):
    def setUp(self):
        objects = source_objects()
        # Existing online submissions are opaque to this migration and must
        # remain byte-for-byte unchanged.
        self.q4_key = (
            migration.REVIEWS_ROOT
            + "/review-20260829-existing-q4/evaluation.json"
        )
        self.q5_key = (
            migration.REVIEWS_ROOT
            + "/review-20260829-existing-q5/evaluation.json"
        )
        objects[self.q4_key] = b'{"question_id":"Q4","existing":true}'
        objects[self.q5_key] = b'{"question_id":"Q5","existing":true}'
        self.client = FakeB2(objects)
        self.existing = {
            self.q4_key: objects[self.q4_key],
            self.q5_key: objects[self.q5_key],
        }

    def target_json(self, question_id: str, filename: str):
        key = (
            f"{migration.REVIEWS_ROOT}/{migration.archive_id_for(question_id)}/"
            f"{filename}"
        )
        return json.loads(self.client.objects[key])

    def test_q1_q3_are_imported_once_with_required_mapping(self):
        result = migration.migrate_legacy_feedback(self.client, "fixture-bucket")

        self.assertEqual(result, {"created": ["Q1", "Q2", "Q3"], "unchanged": []})
        self.assertEqual(len(self.client.puts), 12)
        for question_id, disposition in migration.DISPOSITIONS.items():
            evaluation = self.target_json(
                question_id, migration.EVALUATION_FILENAME
            )
            self.assertEqual(evaluation["question_id"], question_id)
            self.assertEqual(evaluation["reviewer"], "John Cuomo")
            self.assertEqual(evaluation["received_at"], migration.RECEIVED_AT)
            self.assertEqual(evaluation["disposition"], disposition)
            self.assertEqual(
                evaluation["provenance"]["kind"],
                "legacy_pre_online_intake",
            )
            self.assertEqual(
                evaluation["legacy_evaluation"]["question_id"], question_id
            )
            manifest = self.target_json(question_id, migration.MANIFEST_FILENAME)
            self.assertEqual(manifest["question_id"], question_id)
            self.assertEqual(manifest["schema_version"], "1.0")

        target_manifests = [
            key
            for key in self.client.objects
            if key.startswith(migration.REVIEWS_ROOT + "/review-20260802-")
            and key.endswith("/" + migration.MANIFEST_FILENAME)
            and migration.SOURCE_ARCHIVE_ID not in key
        ]
        self.assertEqual(len(target_manifests), 3)

    def test_rerun_is_noop_and_q4_q5_remain_unchanged(self):
        migration.migrate_legacy_feedback(self.client, "fixture-bucket")
        puts_after_first_run = list(self.client.puts)
        result = migration.migrate_legacy_feedback(self.client, "fixture-bucket")

        self.assertEqual(result, {"created": [], "unchanged": ["Q1", "Q2", "Q3"]})
        self.assertEqual(self.client.puts, puts_after_first_run)
        self.assertEqual(
            {key: self.client.objects[key] for key in self.existing},
            self.existing,
        )


if __name__ == "__main__":
    unittest.main()
