import importlib.util
import io
import json
import os
import pathlib
import sys
import types
import unittest


sys.modules.setdefault("boto3", types.SimpleNamespace(client=None))
os.environ.setdefault("B2_BUCKET", "test-bucket")
MODULE_PATH = pathlib.Path(__file__).with_name("scripts") / "run_verified_case_draft.py"
SPEC = importlib.util.spec_from_file_location("verified_case_draft", MODULE_PATH)
WORKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WORKER)


class FakeS3:
    source = "a" * 64
    pages = [
        {"filename": "B Filing.pdf", "page_number": 2, "text": "Unusual record language without the request terms."},
        {"filename": "A Filing.pdf", "page_number": 1, "text": "Another verified page with OCR variation."},
    ]

    def get_object(self, **kwargs):
        if kwargs["Key"].endswith("case_identity.json"):
            return {"Body": io.BytesIO(json.dumps({"source_sha256": self.source}).encode())}
        if kwargs["Key"].endswith("source_set.json"):
            raise RuntimeError("legacy original-only source set")
        return {"Body": io.BytesIO(("\n".join(json.dumps(page) for page in self.pages)).encode())}


class MatchingEvidenceS3(FakeS3):
    pages = [
        {"filename": "Complaint.pdf", "page_number": 3, "text": "The complaint alleges breach of contract claims."},
        {"filename": "Answer.pdf", "page_number": 1, "text": "Defendant asserts affirmative defenses."},
    ]


class EvidenceFailClosedTests(unittest.TestCase):
    def test_no_match_does_not_select_arbitrary_verified_pages(self):
        with self.assertRaisesRegex(ValueError, "no matching verified evidence"):
            WORKER.evidence(
                FakeS3(),
                "NY-Suffolk-600371-2021-DeSousa-v-Calvagno-II-Karcher",
                "Indemnification escrow schedule details?",
            )

    def test_matching_retrieval_selects_scored_pages_only(self):
        pages = WORKER.evidence(
            MatchingEvidenceS3(),
            "NY-Suffolk-600371-2021-DeSousa-v-Calvagno-II-Karcher",
            "What breach of contract claims appear in the complaint?",
        )
        self.assertEqual([page["filename"] for page in pages], ["Complaint.pdf"])
        self.assertTrue(all(page["source_sha256"] == "a" * 64 for page in pages))
        self.assertIn("breach of contract", pages[0]["text"].casefold())


class RecordWidePleadingCoverageTests(unittest.TestCase):
    def test_broad_party_claim_question_keeps_captions_and_operational_pleading_pages(self):
        class PleadingS3(FakeS3):
            pages = [
                {"filename": "Summons and Complaint.pdf", "page_number": 1,
                 "text": "ANDRZEJ SZYM CZYK, Plaintiff, against HUDSON 36 LLC and HUDSON 37 LLC, Defendants."},
                {"filename": "Summons and Complaint.pdf", "page_number": 2,
                 "text": "Background facts about the work site."},
                {"filename": "Summons and Complaint.pdf", "page_number": 3,
                 "text": "FIRST CAUSE OF ACTION -- NEGLIGENCE. WHEREFORE plaintiff demands judgment."},
                {"filename": "Hudson 36 Answer.pdf", "page_number": 1,
                 "text": "HUDSON 36 LLC answers the verified complaint and denies each allegation."},
                {"filename": "Hudson 36 Answer.pdf", "page_number": 2,
                 "text": "FIRST AFFIRMATIVE DEFENSE: failure to state a cause of action."},
                {"filename": "First Third Party Complaint.pdf", "page_number": 1,
                 "text": "HUDSON 37 LLC, third-party plaintiff, against FORWARD HEATING CORP., third-party defendant."},
                {"filename": "First Third Party Complaint.pdf", "page_number": 3,
                 "text": "FIRST CAUSE OF ACTION: contractual indemnification. SECOND CAUSE OF ACTION: contribution."},
            ]

        pages = WORKER.evidence(
            PleadingS3(),
            "NY-Suffolk-600371-2021-DeSousa-v-Calvagno-II-Karcher",
            "What are the parties, claims, defenses, and requested relief in the verified record?",
        )
        selected = {(page["filename"], page["page_number"]) for page in pages}
        self.assertTrue({
            ("Summons and Complaint.pdf", 1),
            ("Summons and Complaint.pdf", 3),
            ("Hudson 36 Answer.pdf", 1),
            ("Hudson 36 Answer.pdf", 2),
            ("First Third Party Complaint.pdf", 1),
            ("First Third Party Complaint.pdf", 3),
        }.issubset(selected))


if __name__ == "__main__":
    unittest.main()
