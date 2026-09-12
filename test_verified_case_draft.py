import importlib.util
import io
import json
import os
import pathlib
import sys
import types
import unittest
from unittest import mock


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


class ClaimsAndDefensesPromptTests(unittest.TestCase):
    def test_claims_and_defenses_prompt_preserves_party_role_and_pleading_limits(self):
        result = {"summary": "Internal draft.", "findings": [{"statement": "Pleading map.", "citations": [{"source_sha256": "a" * 64, "filename": "Complaint.pdf", "page_number": 1}]}], "missing_information": [], "limitations": []}
        response = mock.MagicMock()
        response.read.return_value = json.dumps({"output": [{"content": [{"text": json.dumps(result)}]}]}).encode()
        response.__enter__.return_value = response
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), mock.patch.object(WORKER.urllib.request, "urlopen", return_value=response) as urlopen:
            WORKER.generate("What claims and defenses affect summary judgment?", [{"source_sha256": "a" * 64, "filename": "Complaint.pdf", "page_number": 1, "text": "Private nuisance."}])
        instructions = json.loads(json.loads(urlopen.call_args.args[0].data.decode())["input"])["instructions"]
        self.assertIn("pleaded claims and party role", instructions)
        self.assertIn("identifies a named defendant as an owner", instructions)
        self.assertIn("pleading typo", instructions)


class PendingQueueTests(unittest.TestCase):
    class QueueS3:
        def list_objects_v2(self, **kwargs):
            if kwargs.get("Prefix") == "cases/":
                return {"CommonPrefixes": [{"Prefix": "cases/NY-NewYork-158068-2018-Szymczyk-v-Hudson-36-37/"}]}
            return {"Contents": [
                {"Key": "cases/NY-NewYork-158068-2018-Szymczyk-v-Hudson-36-37/derived/draft-requests/draft-2-bbbbbbbbbbbb.json"},
                {"Key": "cases/NY-NewYork-158068-2018-Szymczyk-v-Hudson-36-37/derived/draft-requests/draft-1-aaaaaaaaaaaa.json"},
            ]}

    def test_pending_requests_selects_only_queued_in_stable_order(self):
        with mock.patch.object(WORKER, "request_status", side_effect=["FAILED", "QUEUED"]):
            pending = list(WORKER.pending_requests(self.QueueS3()))
        self.assertEqual(pending, [("NY-NewYork-158068-2018-Szymczyk-v-Hudson-36-37", "draft-2-bbbbbbbbbbbb")])

    def test_pending_requests_can_limit_scan_to_one_case(self):
        with mock.patch.object(WORKER, "request_status", return_value="QUEUED"):
            pending = list(WORKER.pending_requests(self.QueueS3(), "NY-NewYork-158068-2018-Szymczyk-v-Hudson-36-37"))
        self.assertEqual(pending, [
            ("NY-NewYork-158068-2018-Szymczyk-v-Hudson-36-37", "draft-1-aaaaaaaaaaaa"),
            ("NY-NewYork-158068-2018-Szymczyk-v-Hudson-36-37", "draft-2-bbbbbbbbbbbb"),
        ])

    def test_pending_requests_reads_later_b2_listing_pages(self):
        class PaginatedQueueS3(self.QueueS3):
            def list_objects_v2(self, **kwargs):
                if kwargs.get("Prefix") == "cases/":
                    return super().list_objects_v2(**kwargs)
                if kwargs.get("ContinuationToken") is None:
                    return {
                        "Contents": [],
                        "IsTruncated": True,
                        "NextContinuationToken": "next-page",
                    }
                return {"Contents": [
                    {"Key": "cases/NY-NewYork-158068-2018-Szymczyk-v-Hudson-36-37/derived/draft-requests/draft-3-cccccccccccc.json"}
                ]}

        with mock.patch.object(WORKER, "request_status", return_value="QUEUED"):
            pending = list(WORKER.pending_requests(PaginatedQueueS3()))
        self.assertEqual(pending, [("NY-NewYork-158068-2018-Szymczyk-v-Hudson-36-37", "draft-3-cccccccccccc")])


class RecordWidePleadingCoverageTests(unittest.TestCase):
    def test_broad_party_claim_question_keeps_captions_and_operational_pleading_pages(self):
        class PleadingS3(FakeS3):
            pages = [
                {"filename": "Summons and Complaint.pdf", "page_number": 1,
                 "text": "ANDRZEJ SZYM CZYK, Plaintiff, against HUDSON 36 LLC and HUDSON 37 LLC, Defendants."},
                {"filename": "Summons and Complaint.pdf", "page_number": 2,
                 "text": "Background facts about the work site."},
                {"filename": "Summons and Complaint.pdf", "page_number": 4,
                 "text": "Patrick Karcher is an owner of the subject property."},
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
            ("Summons and Complaint.pdf", 4),
            ("Summons and Complaint.pdf", 3),
            ("Hudson 36 Answer.pdf", 1),
            ("Hudson 36 Answer.pdf", 2),
            ("First Third Party Complaint.pdf", 1),
            ("First Third Party Complaint.pdf", 3),
        }.issubset(selected))


class SzymczykFilenameCoverageTests(unittest.TestCase):
    def test_underscored_pleading_filename_is_classified(self):
        name = "158068_2018_ANDRZEJ_SZYMCZYK_v_HUDSON_36_LLC_et_al_ANSWER_3.pdf"
        self.assertRegex(WORKER.normalized_filename(name), WORKER.PLEADING_FILENAME_RE)

    def test_targeted_third_party_defense_question_reserves_page_17_before_exhibits(self):
        class ThirdPartyDefenseS3(FakeS3):
            pages = [
                {"filename": "158068_2018_ANSWER_TO_THIRD_PAR_10.pdf", "page_number": 15,
                 "text": "ANSWER TO THIRD-PARTY COMPLAINT. Third-party defendants answer."},
                {"filename": "158068_2018_ANSWER_TO_THIRD_PAR_10.pdf", "page_number": 17,
                 "text": "AS FOR A FIRST AFFIRMATIVE DEFENSE. Plaintiff was solely negligent."},
            ] + [
                {"filename": f"158068_2018_EXHIBIT_S_{index}.pdf", "page_number": 1,
                 "text": "third-party contractor indemnity defense provision"}
                for index in range(45)
            ]

        pages = WORKER.evidence(
            ThirdPartyDefenseS3(),
            "NY-Suffolk-600371-2021-DeSousa-v-Calvagno-II-Karcher",
            "Which verified filing contains the affirmative defenses against the third-party complaint, and what does page 17 state?",
        )
        selected = {(page["filename"], page["page_number"]) for page in pages}
        self.assertIn(("158068_2018_ANSWER_TO_THIRD_PAR_10.pdf", 17), selected)

    def test_targeted_third_party_complaint_keeps_operative_pages_after_caption(self):
        class ThirdPartyComplaintS3(FakeS3):
            pages = [
                {"filename": "158068_2018_THIRD_PARTY_SUMMONS_5.pdf", "page_number": 3,
                 "text": "HUDSON 37 LLC, third-party plaintiff, against FORWARD HEATING CORP. and FORWARD MECHANICAL CORP., third-party defendants."},
                {"filename": "158068_2018_THIRD_PARTY_SUMMONS_5.pdf", "page_number": 9,
                 "text": "FIRST CAUSE OF ACTION: contractual indemnification."},
                {"filename": "158068_2018_THIRD_PARTY_SUMMONS_5.pdf", "page_number": 11,
                 "text": "THIRD CAUSE OF ACTION: breach of insurance-procurement obligations."},
                {"filename": "158068_2018_THIRD_PARTY_SUMMONS_5.pdf", "page_number": 12,
                 "text": "WHEREFORE Hudson 37 requests damages, costs, and disbursements."},
            ] + [
                {"filename": f"158068_2018_EXHIBIT_S_{index}.pdf", "page_number": 1,
                 "text": "Hudson Forward Heating Mechanical claims relief third-party complaint"}
                for index in range(45)
            ]

        pages = WORKER.evidence(
            ThirdPartyComplaintS3(),
            "NY-Suffolk-600371-2021-DeSousa-v-Calvagno-II-Karcher",
            "What claims and relief does Hudson 37 assert against Forward Heating and Forward Mechanical in its third-party complaint?",
        )
        selected = {(page["filename"], page["page_number"]) for page in pages}
        self.assertTrue({
            ("158068_2018_THIRD_PARTY_SUMMONS_5.pdf", 3),
            ("158068_2018_THIRD_PARTY_SUMMONS_5.pdf", 9),
            ("158068_2018_THIRD_PARTY_SUMMONS_5.pdf", 11),
            ("158068_2018_THIRD_PARTY_SUMMONS_5.pdf", 12),
        }.issubset(selected))

    def test_merits_pleadings_are_reserved_ahead_of_high_scoring_contract_pages(self):
        class DenseS3(FakeS3):
            pages = [
                {"filename": "158068_2018_ANDRZEJ_SZYMCZYK_v_HUDSON_36_LLC_et_al_ANSWER_3.pdf",
                 "page_number": 1, "text": "HUDSON 36 LLC denies the complaint."},
                {"filename": "158068_2018_ANDRZEJ_SZYMCZYK_v_HUDSON_36_LLC_et_al_SUMMONS___COMPLAINT_1.pdf",
                 "page_number": 1, "text": "ANDRZEJ SZYMCZYK, Plaintiff, against HUDSON 36 LLC."},
                {"filename": "158068_2018_ANDRZEJ_SZYMCZYK_v_HUDSON_36_LLC_et_al_FIRST_THIRD_PARTY_COMPLAINT_7.pdf",
                 "page_number": 3, "text": "FIRST CAUSE OF ACTION: contractual indemnification."},
            ] + [
                {"filename": f"158068_2018_EXHIBIT_S_{index}.pdf", "page_number": 1,
                 "text": "claims defenses relief claims defenses relief"}
                for index in range(40)
            ]

        pages = WORKER.evidence(
            DenseS3(),
            "NY-Suffolk-600371-2021-DeSousa-v-Calvagno-II-Karcher",
            "What are the parties, claims, defenses, and requested relief in the verified record?",
        )
        selected = {page["filename"] for page in pages}
        self.assertIn("158068_2018_ANDRZEJ_SZYMCZYK_v_HUDSON_36_LLC_et_al_ANSWER_3.pdf", selected)
        self.assertIn("158068_2018_ANDRZEJ_SZYMCZYK_v_HUDSON_36_LLC_et_al_SUMMONS___COMPLAINT_1.pdf", selected)
        self.assertIn("158068_2018_ANDRZEJ_SZYMCZYK_v_HUDSON_36_LLC_et_al_FIRST_THIRD_PARTY_COMPLAINT_7.pdf", selected)


    def test_filing_led_coverage_retains_caption_claim_defense_and_prayer_pages(self):
        class FilingLedS3(FakeS3):
            pages = [
                {"filename": "Complaint.pdf", "page_number": 1, "text": "Plaintiff against Defendant."},
                {"filename": "Complaint.pdf", "page_number": 3, "text": "FIRST CAUSE OF ACTION: negligence."},
                {"filename": "Complaint.pdf", "page_number": 4, "text": "WHEREFORE plaintiff requests damages."},
                {"filename": "Answer.pdf", "page_number": 1, "text": "Defendant answers the complaint."},
                {"filename": "Answer.pdf", "page_number": 2, "text": "FIRST AFFIRMATIVE DEFENSE."},
                {"filename": "Answer.pdf", "page_number": 3, "text": "Defendant denies the remaining allegations."},
            ] + [
                {"filename": f"Exhibit {index}.pdf", "page_number": 1,
                 "text": "parties claims defenses relief"}
                for index in range(40)
            ]

        pages = WORKER.evidence(
            FilingLedS3(),
            "NY-Suffolk-600371-2021-DeSousa-v-Calvagno-II-Karcher",
            "What are the parties, claims, defenses, and requested relief in the verified record?",
        )
        selected = {(page["filename"], page["page_number"]) for page in pages}
        self.assertTrue({
            ("Complaint.pdf", 1), ("Complaint.pdf", 3), ("Complaint.pdf", 4),
            ("Answer.pdf", 1), ("Answer.pdf", 2), ("Answer.pdf", 3),
        }.issubset(selected))


    def test_bundled_later_answer_gets_its_own_caption_and_defense_pages(self):
        class BundledS3(FakeS3):
            pages = [
                {"filename": "Answer to Third Party.pdf", "page_number": 1,
                 "text": "VERIFIED ANSWER TO THIRD-PARTY COMPLAINT. Defendant denies the complaint."},
                {"filename": "Answer to Third Party.pdf", "page_number": 13,
                 "text": "DEMAND FOR A VERIFIED BILL OF PARTICULARS."},
                {"filename": "Answer to Third Party.pdf", "page_number": 15,
                 "text": "ANSWER TO THIRD-PARTY COMPLAINT. Third-party defendants answer."},
                {"filename": "Answer to Third Party.pdf", "page_number": 17,
                 "text": "AS FOR A FIRST AFFIRMATIVE DEFENSE. Plaintiff was solely negligent."},
                {"filename": "Answer to Third Party.pdf", "page_number": 22,
                 "text": "WHEREFORE the third-party defendants demand dismissal."},
            ] + [
                {"filename": f"Exhibit {index}.pdf", "page_number": 1,
                 "text": "parties claims defenses relief"}
                for index in range(45)
            ]

        pages = WORKER.evidence(
            BundledS3(),
            "NY-Suffolk-600371-2021-DeSousa-v-Calvagno-II-Karcher",
            "What are the parties, claims, defenses, and requested relief in the verified record?",
        )
        selected = {(page["filename"], page["page_number"]) for page in pages}
        self.assertTrue({
            ("Answer to Third Party.pdf", 15),
            ("Answer to Third Party.pdf", 17),
            ("Answer to Third Party.pdf", 22),
        }.issubset(selected))


    def test_late_bundled_section_survives_full_mandatory_context_budget(self):
        filler = "x" * 2200
        class FullBudgetS3(FakeS3):
            pages = [
                {"filename": f"A{index:02d} Answer.pdf", "page_number": page,
                 "text": f"{'VERIFIED ANSWER TO COMPLAINT' if page == 1 else 'AS FOR A FIRST AFFIRMATIVE DEFENSE' if page == 2 else 'WHEREFORE defendant requests relief'} {filler}"}
                for index in range(13) for page in (1, 2, 3)
            ] + [
                {"filename": "Z Bundled Answer.pdf", "page_number": 1,
                 "text": f"VERIFIED ANSWER TO THIRD-PARTY COMPLAINT. Defendant denies. {filler}"},
                {"filename": "Z Bundled Answer.pdf", "page_number": 15,
                 "text": f"ANSWER TO THIRD-PARTY COMPLAINT. Third-party defendants answer. {filler}"},
                {"filename": "Z Bundled Answer.pdf", "page_number": 17,
                 "text": f"AS FOR A FIRST AFFIRMATIVE DEFENSE. {filler}"},
                {"filename": "Z Bundled Answer.pdf", "page_number": 22,
                 "text": f"WHEREFORE third-party defendants demand dismissal. {filler}"},
            ]

        pages = WORKER.evidence(
            FullBudgetS3(),
            "NY-Suffolk-600371-2021-DeSousa-v-Calvagno-II-Karcher",
            "What are the parties, claims, defenses, and requested relief in the verified record?",
        )
        selected = {(page["filename"], page["page_number"]) for page in pages}
        self.assertTrue({
            ("Z Bundled Answer.pdf", 15),
            ("Z Bundled Answer.pdf", 17),
            ("Z Bundled Answer.pdf", 22),
        }.issubset(selected))


    def test_late_affirmative_defense_heading_precedes_high_scoring_continuations(self):
        filler = "parties claims defenses relief"
        class HeadingPriorityS3(FakeS3):
            pages = [
                {"filename": f"A{index:02d} Answer.pdf", "page_number": page,
                 "text": "AS FOR A FIRST AFFIRMATIVE DEFENSE." if page == 2 else filler}
                for index in range(30) for page in (2, 3)
            ] + [
                {"filename": "Z Answer to Third Party.pdf", "page_number": 15,
                 "text": "ANSWER TO THIRD-PARTY COMPLAINT."},
                {"filename": "Z Answer to Third Party.pdf", "page_number": 17,
                 "text": "AS FOR A FIRST AFFIRMATIVE DEFENSE."},
            ]

        pages = WORKER.evidence(
            HeadingPriorityS3(),
            "NY-Suffolk-600371-2021-DeSousa-v-Calvagno-II-Karcher",
            "What are the parties, claims, defenses, and requested relief in the verified record?",
        )
        self.assertIn(
            ("Z Answer to Third Party.pdf", 17),
            {(page["filename"], page["page_number"]) for page in pages},
        )

    def test_first_defense_page_per_section_precedes_later_defense_headings(self):
        class FirstDefenseS3(FakeS3):
            pages = [
                {"filename": f"A{index:02d} Answer.pdf", "page_number": page,
                 "text": "AS FOR AN AFFIRMATIVE DEFENSE parties claims defenses relief"}
                for index in range(23) for page in (2, 3)
            ] + [
                {"filename": "Z Answer to Third Party.pdf", "page_number": 15,
                 "text": "ANSWER TO THIRD-PARTY COMPLAINT."},
                {"filename": "Z Answer to Third Party.pdf", "page_number": 17,
                 "text": "AS FOR A FIRST AFFIRMATIVE DEFENSE."},
            ]

        pages = WORKER.evidence(
            FirstDefenseS3(),
            "NY-Suffolk-600371-2021-DeSousa-v-Calvagno-II-Karcher",
            "What are the parties, claims, defenses, and requested relief in the verified record?",
        )
        self.assertIn(
            ("Z Answer to Third Party.pdf", 17),
            {(page["filename"], page["page_number"]) for page in pages},
        )

    def test_pre_generation_gate_blocks_when_required_defense_pages_exceed_budget(self):
        class TooManyDefenseSectionsS3(FakeS3):
            pages = [
                {"filename": f"Answer {index:02d}.pdf", "page_number": 2,
                 "text": "AS FOR A FIRST AFFIRMATIVE DEFENSE parties claims defenses relief"}
                for index in range(WORKER.MAX_PAGES + 1)
            ]

        with self.assertRaisesRegex(WORKER.PreGenerationGateError, "missing_first_affirmative_defense_page"):
            WORKER.evidence(
                TooManyDefenseSectionsS3(),
                "NY-Suffolk-600371-2021-DeSousa-v-Calvagno-II-Karcher",
                "What are the parties, claims, defenses, and requested relief in the verified record?",
            )


class AttackSurfaceRetrievalTests(unittest.TestCase):
    def test_v4_prompt_requires_named_party_propositions_and_two_sided_citations(self):
        result = {
            "summary": "Internal draft.",
            "findings": [{
                "statement": "Rank 1 — Contradiction — Hudson 37's position conflicts with the court order.",
                "citations": [{"source_sha256": "a" * 64, "filename": "Order.pdf", "page_number": 4}],
            }],
            "missing_information": [],
            "limitations": [],
        }
        response = mock.MagicMock()
        response.read.return_value = json.dumps({
            "output": [{"content": [{"text": json.dumps(result)}]}]
        }).encode()
        response.__enter__.return_value = response
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), mock.patch.object(WORKER.urllib.request, "urlopen", return_value=response) as urlopen:
            WORKER.generate(
                "Prepare the v4.0 Top Attack Surfaces Report from the verified record.",
                [{"source_sha256": "a" * 64, "filename": "Order.pdf", "page_number": 4, "text": "Hudson 37 LLC."}],
            )

        payload = json.loads(urlopen.call_args.args[0].data.decode())
        instructions = json.loads(payload["input"])["instructions"]
        self.assertIn("identify the affected party or litigation position", instructions)
        self.assertIn("specific record proposition on each side", instructions)
        self.assertIn("must cite each of the two conflicting verified propositions", instructions)
        self.assertIn("Do not rank a defense merely because", instructions)
        self.assertIn("return fewer when fewer qualify", instructions)

    def test_v4_reserves_room_for_sworn_and_party_linked_exhibit_material(self):
        class AttackSurfaceS3(FakeS3):
            pages = [
                {
                    "filename": f"Answer {index:02d}.pdf",
                    "page_number": 2,
                    "text": "AS FOR A FIRST AFFIRMATIVE DEFENSE. Plaintiff denies the claims.",
                }
                for index in range(30)
            ] + [
                {
                    "filename": "158068_2018_EXHIBIT_S_111.pdf",
                    "page_number": 4,
                    "text": "AFFIDAVIT OF JANE DOE. I am sworn and state the following facts.",
                },
                {
                    "filename": "158068_2018_EXHIBIT_S_112.pdf",
                    "page_number": 7,
                    "text": "Email correspondence from Hudson 37 LLC regarding the incident report.",
                },
            ]

        pages = WORKER.evidence(
            AttackSurfaceS3(),
            "NY-Suffolk-600371-2021-DeSousa-v-Calvagno-II-Karcher",
            "Prepare the v4.0 Top Attack Surfaces Report from the verified record.",
        )
        selected = [(page["filename"], page["page_number"]) for page in pages]
        self.assertIn(("158068_2018_EXHIBIT_S_111.pdf", 4), selected)
        self.assertIn(("158068_2018_EXHIBIT_S_112.pdf", 7), selected)
        self.assertLess(
            selected.index(("158068_2018_EXHIBIT_S_111.pdf", 4)),
            selected.index(("Answer 18.pdf", 2)),
        )


if __name__ == "__main__":
    unittest.main()
