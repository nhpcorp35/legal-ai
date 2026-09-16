"""Focused tests for the offline verified-authority registry and matcher."""

from __future__ import annotations

import unittest
from urllib.parse import urlsplit

from engines.verified_authority_registry import (
    TRUSTED_SOURCE_HOSTS,
    VERIFIED_NY_RESCISSION_AUTHORITIES,
    compute_authority_sha256,
    match_verified_authorities,
    validate_registry,
)


def _mutable_record(index: int = 0) -> dict:
    record = VERIFIED_NY_RESCISSION_AUTHORITIES[index]
    return {**record.as_canonical_dict(), "sha256": record.sha256}


class VerifiedAuthorityRegistryTests(unittest.TestCase):
    def test_registry_contains_exact_seed_pack_and_required_content(self):
        self.assertEqual(len(VERIFIED_NY_RESCISSION_AUTHORITIES), 3)
        self.assertEqual(
            [record.authority_id for record in VERIFIED_NY_RESCISSION_AUTHORITIES],
            [
                "ny-ins-law-3105",
                "ny-estiverne-mic-2024-06327",
                "ny-associated-industrial-farahnik-2025-03760",
            ],
        )
        for record in VERIFIED_NY_RESCISSION_AUTHORITIES:
            self.assertEqual(record.jurisdiction, "NY")
            self.assertTrue(record.citation)
            self.assertTrue(record.title)
            self.assertTrue(record.issuing_body)
            self.assertRegex(record.date, r"^\d{4}-\d{2}-\d{2}$")
            self.assertTrue(record.propositions)
            self.assertTrue(all(len(text) <= 500 for text in record.propositions))

    def test_canonical_hashes_are_stable_and_verified(self):
        expected = {
            "ny-ins-law-3105": (
                "08143aca44aabb2bb864bc61c967e76da4d3c142b3c25c2ad7f310788aee4ad7"
            ),
            "ny-estiverne-mic-2024-06327": (
                "4004a6bb7b2c920011d32cf194fc456965243bfc84657a94b4dcbc1464c3d75a"
            ),
            "ny-associated-industrial-farahnik-2025-03760": (
                "0f235fbec0e96e24d5c91d5b073ffcba051492774b9f10cca3d6cae7263bde6b"
            ),
        }
        for record in VERIFIED_NY_RESCISSION_AUTHORITIES:
            self.assertEqual(record.sha256, expected[record.authority_id])
            self.assertEqual(compute_authority_sha256(record), record.sha256)

    def test_sources_are_https_and_on_exact_trusted_hosts(self):
        for record in VERIFIED_NY_RESCISSION_AUTHORITIES:
            parsed = urlsplit(record.source_url)
            self.assertEqual(parsed.scheme, "https")
            self.assertIn(parsed.hostname, TRUSTED_SOURCE_HOSTS)
            self.assertIsNone(parsed.port)

    def test_duplicate_ids_are_rejected(self):
        record = _mutable_record()
        with self.assertRaisesRegex(ValueError, "duplicate authority_id"):
            validate_registry([record, dict(record)])

    def test_invalid_records_are_rejected(self):
        mutations = (
            ("jurisdiction", "NJ", "unsupported jurisdiction"),
            ("authority_type", "regulation", "unsupported authority_type"),
            ("source_url", "http://www.nysenate.gov/laws/3105", "source URL"),
            ("source_url", "https://example.com/laws/3105", "source URL"),
            ("date", "2025-99-01", "valid ISO date"),
            ("sha256", "0" * 64, "hash mismatch"),
        )
        for field, value, message in mutations:
            with self.subTest(field=field, value=value):
                record = _mutable_record()
                record[field] = value
                with self.assertRaisesRegex(ValueError, message):
                    validate_registry([record])

        missing = _mutable_record()
        del missing["title"]
        with self.assertRaisesRegex(ValueError, "malformed authority fields"):
            validate_registry([missing])

    def test_content_tampering_causes_hash_mismatch(self):
        record = _mutable_record()
        record["title"] = "Altered title"
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            validate_registry([record])


class VerifiedAuthorityMatcherTests(unittest.TestCase):
    def test_genuine_new_york_insurance_rescission_questions_match_full_pack(self):
        questions = (
            "Can a New York insurer rescind an insurance policy for a material "
            "misrepresentation in the application?",
            "Under NY Insurance Law § 3105, can an innocent material "
            "misrepresentation make coverage void ab initio?",
            "Does Estiverne allow underwriting proof to establish rescission "
            "of insurance coverage?",
        )
        for question in questions:
            with self.subTest(question=question):
                result = match_verified_authorities(question)
                self.assertIs(result, VERIFIED_NY_RESCISSION_AUTHORITIES)
                self.assertEqual(len(result), 3)

    def test_unrelated_and_generic_questions_do_not_match(self):
        questions = (
            "",
            "What is the weather in New York?",
            "What does this policy say about late payment?",
            "Is this fact material to the contract dispute?",
            "Was the witness representation accurate?",
            "Explain material representation policy in New York.",
            "Can a California insurer rescind an insurance policy?",
            "Can a New York landlord rescind a lease for fraud?",
            "What coverage does this New York insurance policy provide?",
        )
        for question in questions:
            with self.subTest(question=question):
                self.assertEqual(match_verified_authorities(question), ())

    def test_matching_is_deterministic(self):
        question = (
            "New York insurance rescission for material misrepresentation"
        )
        first = match_verified_authorities(question)
        second = match_verified_authorities(question)
        self.assertEqual(first, second)
        self.assertEqual(
            [record.authority_id for record in first],
            [record.authority_id for record in second],
        )


if __name__ == "__main__":
    unittest.main()
