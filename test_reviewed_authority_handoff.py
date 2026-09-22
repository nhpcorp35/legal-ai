"""Regression tests for case-scoped independently reviewed authority intake."""
import io
import json
import os
import unittest
from unittest.mock import patch

from scripts import run_verified_case_draft as worker

CASE = "NY-Nassau-613561-2026-Desousa-v-Rennick"
SOURCE = "6394faf9d9ccdf258a061e231bf2ce9a7e27599c27e5187c4234613e876caf77"


class FakeB2:
    def __init__(self, objects): self.objects = objects
    def get_object(self, *, Bucket, Key): return {"Body": io.BytesIO(self.objects[Key])}


def reviewed():
    value = {"schema_version": "legalai-reviewed-authorities.v1", "case_id": CASE, "source_sha256": SOURCE, "records": [{
        "authority_id": "ny-ciringione-ryan-2018-03960",
        "citation": "Ciringione v. Ryan, 162 A.D.3d 634 (2d Dep't 2018)",
        "official_primary_source": "https://www.nycourts.gov/Reporter/3dseries/2018/2018_03960.htm",
        "exact_holding": "A prescriptive easement requires hostile, open and notorious, continuous and uninterrupted use for 10 years, proved by clear and convincing evidence.",
        "filing_proposition": "The filing cites Ciringione for the prescriptive-easement elements pleaded in the complaint.",
        "filing_record_citation": "613561_2026_MICHAEL_DESOUSA_et_al_v_GEORGE_RENNICK_et_al_AFFIDAVIT_OR_AFFIRM_8 (1).pdf, p. 7",
    }]}
    value["sha256"] = worker._reviewed_authority_hash(value)
    return value


class ReviewedAuthorityHandoffTests(unittest.TestCase):
    def setUp(self): self.env = patch.dict(os.environ, {"B2_BUCKET": "bucket"}); self.env.start()
    def tearDown(self): self.env.stop()
    def _load(self, objects):
        with patch.object(worker, "verified_sources", return_value=[SOURCE]):
            return worker.load_reviewed_authorities(FakeB2(objects), CASE)

    def test_unreviewed_party_citations_never_enter(self):
        self.assertEqual(self._load({}), ())

    def test_complete_reviewed_record_enters_with_source_holding_proposition_and_record_page(self):
        key = f"cases/{CASE}/derived/reviewed-authorities/{SOURCE}.json"
        authorities = self._load({key: json.dumps(reviewed()).encode()})
        self.assertEqual(len(authorities), 1)
        supplied = worker.authority_prompt(authorities)[0]
        self.assertIn("official_primary_source", supplied)
        self.assertIn("exact_holding", supplied)
        self.assertIn("filing_proposition", supplied)
        self.assertIn("p. 7", supplied["filing_record_citation"])

    def test_changed_or_hash_mismatched_record_is_rejected(self):
        value = reviewed(); value["records"][0]["exact_holding"] = "Changed"
        key = f"cases/{CASE}/derived/reviewed-authorities/{SOURCE}.json"
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self._load({key: json.dumps(value).encode()})

    def test_reviewed_town_code_from_designated_publisher_enters(self):
        value = reviewed()
        value["records"][0]["official_primary_source"] = (
            "https://ecode360.com/print/OY1221?guid=26878708"
        )
        value["sha256"] = worker._reviewed_authority_hash(value)
        key = f"cases/{CASE}/derived/reviewed-authorities/{SOURCE}.json"
        authorities = self._load({key: json.dumps(value).encode()})
        self.assertEqual(len(authorities), 1)
        self.assertTrue(authorities[0].official_primary_source.startswith("https://ecode360.com/"))


if __name__ == "__main__": unittest.main()
