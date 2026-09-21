import importlib.util
import io
import json
import os
import pathlib
import sys
import types
import unittest
import urllib.request
from unittest import mock


sys.modules.setdefault("boto3", types.SimpleNamespace(client=None))
os.environ.setdefault("B2_BUCKET", "test-bucket")
MODULE_PATH = pathlib.Path(__file__).with_name("scripts") / "run_verified_case_draft.py"
SPEC = importlib.util.spec_from_file_location("verified_case_draft", MODULE_PATH)
WORKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WORKER)

CASE00_PATH = pathlib.Path(__file__).with_name("scripts") / "run_case00_internal_draft.py"
CASE00_SPEC = importlib.util.spec_from_file_location("case00_internal_draft", CASE00_PATH)
CASE00 = importlib.util.module_from_spec(CASE00_SPEC)
with mock.patch.dict(sys.modules, {
    "scripts.run_verified_case_draft": WORKER,
    "scripts.rebuild_case00_derived": types.SimpleNamespace(),
}):
    CASE00_SPEC.loader.exec_module(CASE00)

LEGAL_QUESTION = "Under New York insurance law, may an insurer obtain rescission for a material misrepresentation?"


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
    def test_record_only_generation_schema_requires_a_page_citation(self):
        schema = WORKER.finding_schema(
            {
                "source_sha256": {"type": "string"},
                "filename": {"type": "string"},
                "page_number": {"type": "integer"},
            },
            litigation_map=True,
        )
        citations = schema["properties"]["findings"]["items"]["properties"]["citations"]
        self.assertEqual(citations["minItems"], 1)

    def test_case00_cache_uses_newest_canonical_page_records(self):
        class CacheS3:
            def list_objects_v2(self, **_kwargs):
                return {"Contents": [
                    {
                        "Key": WORKER.CASE00_RUNTIME_CACHE_PREFIX
                        + "old" + WORKER.CASE00_PAGE_CACHE_SUFFIX,
                        "LastModified": "2026-08-01T00:00:00Z",
                    },
                    {
                        "Key": WORKER.CASE00_RUNTIME_CACHE_PREFIX
                        + "new" + WORKER.CASE00_PAGE_CACHE_SUFFIX,
                        "LastModified": "2026-08-02T00:00:00Z",
                    },
                ], "IsTruncated": False}

            def get_object(self, **kwargs):
                page = 2 if "/new/" in kwargs["Key"] else 1
                return {"Body": io.BytesIO(json.dumps({"pages": [
                    {"source_filename": "Complaint.pdf", "page_number": page,
                     "text": "Cause of action."}
                ]}).encode())}

        pages = WORKER.case00_cached_pages(CacheS3())
        self.assertEqual(pages[0]["page_number"], 2)

    def test_case00_uses_shared_model_free_validation_boundary(self):
        pages = [
            {
                "source_sha256": WORKER.CASE00_BENCHMARK_ID,
                "filename": "Complaint.pdf",
                "page_number": 1,
                "text": "Plaintiff alleges a cause of action.",
            }
        ] + [
            {
                "source_sha256": WORKER.CASE00_BENCHMARK_ID,
                "filename": f"Correspondence {index}.pdf",
                "page_number": 1,
                "text": "main case counterclaims cross claims third party claims relief",
            }
            for index in range(WORKER.MAX_PAGES + 5)
        ]
        with mock.patch.object(WORKER, "case00_evidence", return_value=pages):
            report = WORKER.validate_retrieval(
                object(),
                WORKER.CASE00_BENCHMARK_ID,
                WORKER.RETRIEVAL_VALIDATION_PROFILES["consolidated"],
            )
        self.assertEqual(report["status"], "PASSED")
        self.assertFalse(report["model_called"])
        self.assertLessEqual(report["selected_page_count"], WORKER.MAX_PAGES)
        self.assertEqual(report["pleading_document_count"], 1)

    def test_retrieval_validation_profiles_cover_each_supported_layer(self):
        self.assertEqual(
            set(WORKER.RETRIEVAL_VALIDATION_PROFILES),
            {"main-action", "counter-cross", "third-party", "consolidated"},
        )
        self.assertTrue(WORKER.MAIN_ACTION_ONLY_QUESTION_RE.search(
            WORKER.RETRIEVAL_VALIDATION_PROFILES["main-action"]
        ))
        self.assertTrue(WORKER.CROSS_CLAIM_ONLY_QUESTION_RE.search(
            WORKER.RETRIEVAL_VALIDATION_PROFILES["counter-cross"]
        ))
        self.assertTrue(WORKER.THIRD_PARTY_ONLY_QUESTION_RE.search(
            WORKER.RETRIEVAL_VALIDATION_PROFILES["third-party"]
        ))
        self.assertTrue(WORKER.CONSOLIDATED_LITIGATION_MAP_RE.search(
            WORKER.RETRIEVAL_VALIDATION_PROFILES["consolidated"]
        ))

    def test_retrieval_validation_is_read_only_and_model_free(self):
        report = WORKER.validate_retrieval(
            type(
                "RetrievalValidationS3",
                (FakeS3,),
                {
                    "pages": [{
                        "filename": "Complaint.pdf",
                        "page_number": 3,
                        "text": "FIRST CAUSE OF ACTION: breach of contract.",
                    }]
                },
            )(),
            "NY-Suffolk-600371-2021-DeSousa-v-Calvagno-II-Karcher",
            "What breach of contract claims appear in the complaint?",
        )
        self.assertEqual(report["status"], "PASSED")
        self.assertFalse(report["model_called"])
        self.assertEqual(report["selected_page_count"], 1)
        self.assertEqual(report["selected_document_count"], 1)
        self.assertEqual(report["pleading_document_count"], 1)
        self.assertEqual(
            set(report["coverage"]),
            {
                "party_role_candidate_count",
                "party_role_retrieved_count",
                "party_role_outside_initial_slice",
                "claim_page_count",
                "relief_page_count",
                "verified_pleading_inventory_count",
                "third_party_action_count",
                "third_party_answered_action_count",
                "third_party_unresolved_action_count",
            },
        )
        self.assertEqual(
            report["pleading_signal_counts"]["causes of action or relief"],
            1,
        )

    def test_third_party_validation_reports_absent_layer_without_model(self):
        class NoThirdPartyS3(FakeS3):
            pages = [{
                "filename": "COMPLAINT_1.pdf",
                "page_number": 1,
                "text": "Plaintiff alleges private nuisance against defendants.",
            }]

        report = WORKER.validate_retrieval(
            NoThirdPartyS3(),
            "NY-Suffolk-600371-2021-DeSousa-v-Calvagno-II-Karcher",
            WORKER.RETRIEVAL_VALIDATION_PROFILES["third-party"],
        )

        self.assertEqual(report["status"], "PASSED")
        self.assertFalse(report["model_called"])
        self.assertFalse(report["layer_present"])
        self.assertEqual(report["gate_reason"], "missing_third_party_complaint")
        self.assertEqual(report["selected_page_count"], 0)

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
    def test_party_specific_cross_claim_answer_does_not_require_main_case_section(self):
        question = (
            "Based solely on the verified record, identify every counterclaim and cross-claim "
            "asserted by Quality Facilities Solutions Corp., the parties against whom each is "
            "asserted, the requested relief, and the strongest expressly pleaded defenses."
        )
        page = {
            "source_sha256": "a" * 64,
            "filename": "ANSWER_WITH_CROSS_C_81.pdf",
            "page_number": 6,
            "text": "Quality Facilities Solutions Corp. asserts a cross-claim.",
        }
        result = {
            "summary": "Quality Facilities Solutions Corp. pleads counterclaims and cross-claims.",
            "findings": [{
                "section": "Counterclaims and cross-claims",
                "statement": "Quality Facilities Solutions Corp., claimant: negligence; defenses: affirmative defenses; relief: liability over.",
                "citations": [{key: page[key] for key in ("source_sha256", "filename", "page_number")}],
                "authority_citations": [],
            }],
            "missing_information": [],
            "limitations": [],
        }
        self.assertIs(WORKER.validate(result, [page], question=question), result)

    def test_verified_pleading_inventory_blocks_false_missing_filing_claim(self):
        class PleadingInventoryS3(FakeS3):
            pages = [
                {"filename": "SUMMONS___COMPLAINT_1.pdf", "page_number": 1, "text": "SUPREME COURT Plaintiff against Defendant. Verified complaint."},
                {"filename": "SUMMONS___COMPLAINT_1.pdf", "page_number": 2, "text": "First cause of action for negligence."},
                {"filename": "SUMMONS___COMPLAINT_1.pdf", "page_number": 6, "text": "WHEREFORE plaintiff demands damages."},
                {"filename": "THIRD_PARTY_SUMMONS_5.pdf", "page_number": 1, "text": "Third-party summons and complaint against Forward Heating Corp."},
                {"filename": "THIRD_PARTY_SUMMONS_5.pdf", "page_number": 4, "text": "Cause of action for contractual indemnification."},
            ]

        question = "Identify the pleaded claims and party roles, defenses, and relief."
        pages = WORKER.evidence(PleadingInventoryS3(), "NY-NewYork-158068-2018-Szymczyk-v-Hudson-36-37", question)
        inventory = pages.coverage["verified_pleading_inventory"]
        self.assertEqual({item["filing_kind"] for item in inventory}, {"complaint", "third-party complaint"})
        result = {"summary": "The pleadings identify negligence and indemnification claims.", "findings": [{"section": "Main case", "statement": "Plaintiff and Defendant: negligence; defenses: none identified; relief: damages.", "citations": [{key: pages[0][key] for key in ("source_sha256", "filename", "page_number")}], "authority_citations": []}], "missing_information": ["The complete operative complaint is missing."], "limitations": []}
        with self.assertRaisesRegex(ValueError, "verified pleading called missing"):
            WORKER.validate(result, pages, question=question, coverage=pages.coverage)
        result["missing_information"] = ["The complete first, second, third, and fourth third-party complaints were not supplied."]
        with self.assertRaisesRegex(ValueError, "verified pleading called missing"):
            WORKER.validate(result, pages, question=question, coverage=pages.coverage)

        response = mock.MagicMock()
        response.read.return_value = json.dumps({"output": [{"content": [{"text": json.dumps({**result, "missing_information": []})}]}]}).encode()
        response.__enter__.return_value = response
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), mock.patch.object(WORKER.urllib.request, "urlopen", return_value=response) as urlopen:
            WORKER.generate(question, pages, pages.coverage)
        prompt = json.loads(json.loads(urlopen.call_args.args[0].data.decode())["input"])
        self.assertEqual(prompt["verified_pleading_inventory"], inventory)
        self.assertIn("authoritative presence metadata", prompt["instructions"])

    def test_action_map_allows_only_action_specific_missing_answer(self):
        page = {
            "source_sha256": "a" * 64,
            "filename": "THIRD_PARTY_SUMMONS_5.pdf",
            "page_number": 1,
            "text": "Third-party complaint. Alpha against Able.",
        }
        cite = {key: page[key] for key in ("source_sha256", "filename", "page_number")}
        question = "Validate the third-party-claims layer separately, including parties, claims, defenses, and relief."
        coverage = {
            "verified_pleading_inventory": [
                {"filing_kind": "third-party answer", "filename": "ANSWER_TO_THIRD_PARTY_10.pdf"}
            ],
            "third_party_actions": [
                {"ordinal": "first", "answer_present": False}
            ],
        }
        result = {
            "summary": "The third-party pleadings assert indemnification.",
            "findings": [{
                "section": "Third-party claims",
                "statement": "First action — Alpha against Able: indemnification; defenses: unresolved; relief: judgment over. No corresponding answer was identified.",
                "citations": [cite],
                "authority_citations": [],
            }],
            "missing_information": ["No corresponding answer was identified for the first action."],
            "limitations": [],
        }
        self.assertIs(
            WORKER.validate(result, [page], question=question, coverage=coverage),
            result,
        )
        result["missing_information"] = ["The third-party answer is missing."]
        with self.assertRaisesRegex(ValueError, "verified pleading called missing"):
            WORKER.validate(result, [page], question=question, coverage=coverage)

    def test_claims_and_defenses_prompt_preserves_party_role_and_pleading_limits(self):
        result = {"summary": "Internal draft.", "findings": [{"statement": "Pleading map.", "citations": [{"source_sha256": "a" * 64, "filename": "Complaint.pdf", "page_number": 1}]}], "missing_information": [], "limitations": []}
        response = mock.MagicMock()
        response.read.return_value = json.dumps({"output": [{"content": [{"text": json.dumps(result)}]}]}).encode()
        response.__enter__.return_value = response
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), mock.patch.object(WORKER.urllib.request, "urlopen", return_value=response) as urlopen:
            WORKER.generate("What claims and defenses affect summary judgment?", [{"source_sha256": "a" * 64, "filename": "Complaint.pdf", "page_number": 1, "text": "Private nuisance."}])
        instructions = json.loads(json.loads(urlopen.call_args.args[0].data.decode())["input"])["instructions"]
        for requirement in (
            "compact litigation map",
            "attorney-readable",
            "ownership assertion and a party's nonresidence",
            "pleading typo",
            "(1) Main case; (2) counterclaims and cross-claims; (3) third-party claims",
            "summary must be one sentence of no more than 28 words",
            "do not include party roles, ownership, control",
            "Return at most one finding for each populated heading",
            "Use labels only",
            "List no more than three material defense labels",
            "Collapse any additional routine defenses",
            "do not explain allegations, evidence, legal standards",
            "do not place a plaintiff-side ownership position, party-role statement",
            "do not place a plaintiff-side allegation, ownership position",
            "Do not invent, infer, or call out an unnamed party",
        ):
            self.assertIn(requirement, instructions)
        self.assertIn("procedural disposition, not a merits decision", instructions)

    def test_litigation_map_schema_requires_section_field_and_short_ordered_set(self):
        result = {"summary": "Internal draft.", "findings": [{"section": "Main case", "statement": "Plaintiff: negligence; defenses: none identified; relief: damages.", "citations": [{"source_sha256": "a" * 64, "filename": "Complaint.pdf", "page_number": 1}], "authority_citations": []}], "missing_information": [], "limitations": []}
        response = mock.MagicMock()
        response.read.return_value = json.dumps({"output": [{"content": [{"text": json.dumps(result)}]}]}).encode()
        response.__enter__.return_value = response
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), mock.patch.object(WORKER.urllib.request, "urlopen", return_value=response) as urlopen:
            WORKER.generate("Prepare a litigation map of the parties, claims, defenses, and relief.", [{"source_sha256": "a" * 64, "filename": "Complaint.pdf", "page_number": 1, "text": "Plaintiff alleges negligence."}])
        schema = json.loads(urlopen.call_args.args[0].data.decode())["text"]["format"]["schema"]
        findings = schema["properties"]["findings"]
        self.assertEqual(findings["maxItems"], 3)
        self.assertEqual(findings["items"]["properties"]["section"]["enum"], list(WORKER.LITIGATION_MAP_SECTIONS))
        self.assertIn("section", findings["items"]["required"])

    def test_litigation_map_validation_rejects_misordered_duplicate_and_truncated_output(self):
        page = {"source_sha256": "a" * 64, "filename": "Complaint.pdf", "page_number": 1, "text": "Plaintiff alleges negligence."}
        cite = {key: page[key] for key in ("source_sha256", "filename", "page_number")}
        question = "Prepare a litigation map of the parties, claims, defenses, and relief."
        def result(sections, statement="Party: negligence; defenses: limitations; relief: damages.", missing=()):
            return {"summary": "The pleadings identify negligence claims.", "findings": [{"section": section, "statement": statement, "citations": [cite], "authority_citations": []} for section in sections], "missing_information": list(missing), "limitations": []}
        self.assertIs(WORKER.validate(result(["Main case", "Third-party claims"]), [page], question=question)["findings"][0]["citations"][0], cite)
        unpunctuated = result(
            ["Main case"],
            statement="Party: negligence; defenses: limitations; relief: damages",
        )
        normalized = WORKER.validate(unpunctuated, [page], question=question)
        self.assertEqual(
            normalized["findings"][0]["statement"],
            "Party: negligence; defenses: limitations; relief: damages.",
        )
        for sections in (["Third-party claims", "Main case"], ["Main case", "Main case"]):
            with self.assertRaisesRegex(ValueError, "invalid litigation-map sections"):
                WORKER.validate(result(sections), [page], question=question)
        with self.assertRaisesRegex(ValueError, "incomplete output main case"):
            WORKER.validate(result(["Main case"], statement="Party: negligence and"), [page], question=question)
        quoted = result(["Main case"], statement="Party: negligence; relief: ‘damages’")
        self.assertEqual(
            WORKER.validate(quoted, [page], question=question)["findings"][0]["statement"],
            "Party: negligence; relief: ‘damages’.",
        )
        with self.assertRaisesRegex(ValueError, "unverified missing-page claim"):
            WORKER.validate(result(["Main case"], missing=["Complaint pages 2–18 were not supplied."]), [page], question=question)

    def test_third_party_action_validation_requires_every_complete_action(self):
        page = {"source_sha256": "a" * 64, "filename": "THIRD_PARTY_SUMMONS_5.pdf", "page_number": 1, "text": "Third-party complaint."}
        cite = {key: page[key] for key in ("source_sha256", "filename", "page_number")}
        question = "Validate the third-party-claims layer separately, including parties, claims, defenses, and relief."
        coverage = {
            "third_party_actions": [
                {"ordinal": "first", "answer_present": True},
                {"ordinal": "second", "answer_present": True},
                {"ordinal": "third", "answer_present": False},
                {"ordinal": "fourth", "answer_present": True},
            ],
        }
        statement = (
            "First action — A v. B: indemnification; defenses: limitations; relief: judgment over. "
            "Second action — C v. D: contribution; defenses: waiver; relief: damages. "
            "Third action — E v. F: breach; defenses: unresolved; relief: damages; no corresponding answer was identified. "
            "Fourth action — G v. H: indemnification; defenses: estoppel; relief: dismissal."
        )
        result = {"summary": "The pleadings identify four actions.", "findings": [{"section": "Third-party claims", "statement": statement, "citations": [cite], "authority_citations": []}], "missing_information": [], "limitations": []}
        self.assertIs(WORKER.validate(result, [page], question=question, coverage=coverage), result)
        result["findings"][0]["statement"] = statement.split("Fourth action")[0].rstrip()
        with self.assertRaisesRegex(ValueError, "incomplete third-party actions"):
            WORKER.validate(result, [page], question=question, coverage=coverage)

    def test_consolidated_map_requires_all_sections_in_order(self):
        page = {"source_sha256": "a" * 64, "filename": "Complaint.pdf", "page_number": 1, "text": "Plaintiff alleges negligence."}
        cite = {key: page[key] for key in ("source_sha256", "filename", "page_number")}
        question = "Prepare one consolidated map in order: Main case; Counterclaims and cross-claims; Third-party claims. Identify parties, claims, defenses, and relief."
        def result(sections):
            return {"summary": "The pleadings identify the requested layers.", "findings": [{"section": section, "statement": "Parties: claims; defenses: limitations; relief: damages.", "citations": [cite], "authority_citations": []} for section in sections], "missing_information": [], "limitations": []}
        with self.assertRaisesRegex(ValueError, "invalid litigation-map sections"):
            WORKER.validate(result(["Counterclaims and cross-claims"]), [page], question=question)
        complete = result(list(WORKER.LITIGATION_MAP_SECTIONS))
        self.assertIs(WORKER.validate(complete, [page], question=question), complete)

    def test_third_party_only_litigation_map_accepts_only_third_party_section(self):
        page = {
            "source_sha256": "a" * 64,
            "filename": "THIRD_PARTY_SUMMONS_5.pdf",
            "page_number": 4,
            "text": "Third-party plaintiff seeks contractual indemnification.",
        }
        cite = {key: page[key] for key in ("source_sha256", "filename", "page_number")}
        question = (
            "Validate the third-party-claims layer separately from the main action "
            "and all counterclaims/cross-claims. Identify the parties, claims, "
            "defenses, and relief."
        )

        def result(sections):
            return {
                "summary": "The third-party pleading asserts contractual indemnification.",
                "findings": [
                    {
                        "section": section,
                        "statement": "Third-party plaintiff and defendant: contractual indemnification; defenses: affirmative defenses; relief: indemnification.",
                        "citations": [cite],
                        "authority_citations": [],
                    }
                    for section in sections
                ],
                "missing_information": [],
                "limitations": [],
            }

        valid = result(["Third-party claims"])
        self.assertIs(WORKER.validate(valid, [page], question=question), valid)
        for sections in (["Main case"], ["Main case", "Third-party claims"]):
            with self.assertRaisesRegex(ValueError, "invalid litigation-map sections"):
                WORKER.validate(result(sections), [page], question=question)

    def test_death_and_substitution_stays_procedural_not_merits(self):
        page = {"source_sha256": "a" * 64, "filename": "Order.pdf", "page_number": 2, "text": "Motion denied due to death; substitution pending."}
        result = {"summary": "The order records a procedural disposition.", "findings": [{"section": "Main case", "statement": "Estate representative: substitution pending; defenses: not adjudicated; relief: motion denied procedurally.", "citations": [{key: page[key] for key in ("source_sha256", "filename", "page_number")}], "authority_citations": []}], "missing_information": [], "limitations": []}
        question = "Map the parties, claims, defenses, and relief after the party's death and substitution order."
        self.assertIs(WORKER.validate(result, [page], question=question), result)


class AuthorityAwareWorkerTests(unittest.TestCase):
    active_page = {"source_sha256": "a" * 64, "filename": "Policy.pdf", "page_number": 7, "text": "Application answer."}
    case00_page = {"filename": "Policy.pdf", "page_number": 7, "text": "Application answer."}

    @staticmethod
    def response(result):
        response = mock.MagicMock()
        response.read.return_value = json.dumps({"output": [{"content": [{"text": json.dumps(result)}]}]}).encode()
        response.__enter__.return_value = response
        return response

    def test_active_worker_prompt_selects_three_authorities_and_unrelated_selects_none(self):
        result = {"summary": "Rule.", "findings": [{"statement": "Rule.", "citations": [], "authority_citations": ["ny-ins-law-3105"]}], "missing_information": [], "limitations": []}
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), mock.patch.object(WORKER.urllib.request, "urlopen", return_value=self.response(result)) as urlopen:
            WORKER.generate(LEGAL_QUESTION, [self.active_page])
            legal_prompt = json.loads(json.loads(urlopen.call_args.args[0].data.decode())["input"])
            WORKER.generate("What parties appear in this contract dispute?", [self.active_page])
            unrelated_prompt = json.loads(json.loads(urlopen.call_args.args[0].data.decode())["input"])
        self.assertEqual(len(legal_prompt["legal_authorities"]), 3)
        self.assertEqual(
            {item["authority_id"] for item in legal_prompt["legal_authorities"]},
            {"ny-ins-law-3105", "ny-estiverne-mic-2024-06327", "ny-associated-industrial-farahnik-2025-03760"},
        )
        self.assertEqual(unrelated_prompt["legal_authorities"], [])
        self.assertNotIn("legal_authorities", legal_prompt["pages"][0])
        self.assertIn("Case-record facts cite only page citations", legal_prompt["instructions"])
        self.assertIn("legal rules cite only authority ids", legal_prompt["instructions"])
        self.assertIn("concise attorney answer", legal_prompt["instructions"])
        self.assertIn("State each legal rule once", legal_prompt["instructions"])
        legal_schema = json.loads(urlopen.call_args_list[0].args[0].data.decode())["text"]["format"]["schema"]
        finding = legal_schema["properties"]["findings"]
        self.assertEqual(finding["maxItems"], 8)
        self.assertEqual(legal_schema["properties"]["summary"]["maxLength"], 800)
        self.assertIn("End the summary with a complete sentence", legal_prompt["instructions"])
        self.assertEqual(
            finding["items"]["properties"]["section"]["enum"],
            list(WORKER.ATTORNEY_ANSWER_SECTIONS),
        )
        unrelated_schema = json.loads(urlopen.call_args_list[1].args[0].data.decode())["text"]["format"]["schema"]
        self.assertNotIn("section", unrelated_schema["properties"]["findings"]["items"]["properties"])

    def test_both_workers_accept_rule_and_mixed_findings_and_reject_bad_sources(self):
        authorities = WORKER.match_verified_authorities(LEGAL_QUESTION)
        rule = {"summary": "Rule.", "findings": [{"statement": "Rule.", "citations": [], "authority_citations": ["ny-ins-law-3105"]}]}
        mixed_active = {"summary": "Application.", "findings": [{"statement": "Application.", "citations": [{key: self.active_page[key] for key in ("source_sha256", "filename", "page_number")}], "authority_citations": ["ny-ins-law-3105"]}]}
        mixed_case00 = {"summary": "Application.", "findings": [{"statement": "Application.", "citations": [{"filename": "Policy.pdf", "page_number": 7}], "authority_citations": ["ny-ins-law-3105"]}]}
        self.assertIs(WORKER.validate(rule, [self.active_page], authorities), rule)
        self.assertIs(CASE00.validate(rule, [self.case00_page], authorities), rule)
        self.assertIs(WORKER.validate(mixed_active, [self.active_page], authorities), mixed_active)
        self.assertIs(CASE00.validate(mixed_case00, [self.case00_page], authorities), mixed_case00)
        for validator, pages in ((WORKER.validate, [self.active_page]), (CASE00.validate, [self.case00_page])):
            unknown = {"findings": [{"statement": "Rule.", "citations": [], "authority_citations": ["unknown-authority"]}]}
            neither = {"findings": [{"statement": "Unsupported.", "citations": [], "authority_citations": []}]}
            with self.assertRaisesRegex(ValueError, "unverified authority citation"):
                validator(unknown, pages, authorities)
            with self.assertRaisesRegex(ValueError, "uncited output"):
                validator(neither, pages, authorities)

    def test_case00_prompt_and_audit_keep_authorities_bounded_and_separate(self):
        request_id = "draft-1-aaaaaaaaaaaa"
        request_key = f"cases/{CASE00.CASE_ID}/derived/draft-requests/{request_id}.json"

        class AuditS3:
            def __init__(self):
                self.objects = {request_key: json.dumps({"question": LEGAL_QUESTION}).encode()}

            def get_object(self, **kwargs):
                if kwargs["Key"] not in self.objects:
                    raise KeyError(kwargs["Key"])
                return {"Body": io.BytesIO(self.objects[kwargs["Key"]])}

            def put_object(self, **kwargs):
                self.objects[kwargs["Key"]] = kwargs["Body"]

        client = AuditS3()
        result = {"summary": "Rule.", "findings": [{"statement": "Rule.", "citations": [], "authority_citations": ["ny-ins-law-3105"]}], "missing_information": [], "limitations": []}
        with mock.patch.object(CASE00, "evidence", return_value=[self.case00_page]), mock.patch.object(urllib.request, "urlopen", return_value=self.response(result)) as urlopen:
            CASE00.run_request(client, request_id)
        prompt = json.loads(json.loads(urlopen.call_args.args[0].data.decode())["input"])
        audit = json.loads(client.objects[CASE00.key(request_id, "input_audit.json")])
        self.assertEqual(len(prompt["legal_authorities"]), 3)
        self.assertIn("concise attorney answer", prompt["instructions"])
        self.assertIn("End the summary with a complete sentence", prompt["instructions"])
        self.assertIn("Put absent proof only in missing_information", prompt["instructions"])
        self.assertNotIn("legal_authorities", prompt["pages"][0])
        self.assertEqual(len(audit["legal_authorities"]), 3)
        expected = {"authority_id", "citation", "title", "source_url", "issuing_body", "date", "sha256"}
        self.assertTrue(all(set(item) == expected for item in audit["legal_authorities"]))
        self.assertTrue(all("propositions" not in item for item in audit["legal_authorities"]))
        self.assertTrue(all(len(item["sha256"]) == 64 for item in audit["legal_authorities"]))

    def test_case00_unrelated_prompt_has_no_authorities(self):
        request_id = "draft-2-bbbbbbbbbbbb"
        request_key = f"cases/{CASE00.CASE_ID}/derived/draft-requests/{request_id}.json"

        class PromptS3:
            def __init__(self):
                self.objects = {request_key: json.dumps({"question": "Who signed the construction contract?"}).encode()}
            def get_object(self, **kwargs):
                if kwargs["Key"] not in self.objects: raise KeyError(kwargs["Key"])
                return {"Body": io.BytesIO(self.objects[kwargs["Key"]])}
            def put_object(self, **kwargs):
                self.objects[kwargs["Key"]] = kwargs["Body"]

        result = {"summary": "Fact.", "findings": [{"statement": "Fact.", "citations": [{"filename": "Policy.pdf", "page_number": 7}], "authority_citations": []}], "missing_information": [], "limitations": []}
        with mock.patch.object(CASE00, "evidence", return_value=[self.case00_page]), mock.patch.object(urllib.request, "urlopen", return_value=self.response(result)) as urlopen:
            CASE00.run_request(PromptS3(), request_id)
        prompt = json.loads(json.loads(urlopen.call_args.args[0].data.decode())["input"])
        self.assertEqual(prompt["legal_authorities"], [])


class PartyRoleEvidenceTests(unittest.TestCase):
    def test_joint_owner_and_no_control_pages_survive_party_claims_retrieval(self):
        class RoleS3(FakeS3):
            pages = [
                {"filename": "Complaint.pdf", "page_number": 1, "text": "Plaintiff against Calvagno and Karcher."},
                {"filename": "Karcher Affidavit.pdf", "page_number": 1, "text": "Karcher never resided at the property and had no control."},
                {"filename": "Plaintiffs Opposition.pdf", "page_number": 3, "text": "Karcher is a joint owner of the premises by recorded deed."},
            ]
        pages = WORKER.evidence(RoleS3(), "NY-Suffolk-600371-2021-DeSousa-v-Calvagno-II-Karcher", "What claims and defenses affect Calvagno and Karcher?")
        selected = {page["filename"] for page in pages}
        self.assertTrue({"Karcher Affidavit.pdf", "Plaintiffs Opposition.pdf"}.issubset(selected))

    def test_audit_flags_party_role_evidence_outside_bounded_slice(self):
        class RoleS3(FakeS3):
            pages = [
                {"filename": "Karcher Affidavit.pdf", "page_number": 1, "text": "Karcher never resided at the property and had no control."},
                {"filename": "Plaintiffs Opposition.pdf", "page_number": 3, "text": "Karcher is a joint owner of the premises by recorded deed."},
            ]
        with mock.patch.object(WORKER, "MAX_PAGES", 1):
            pages = WORKER.evidence(RoleS3(), "NY-Suffolk-600371-2021-DeSousa-v-Calvagno-II-Karcher", "What claims and defenses affect Calvagno and Karcher?")
        coverage = pages.coverage["party_role_evidence"]
        self.assertEqual(coverage["candidate_count"], 2)
        self.assertEqual(coverage["retrieved_count"], 1)
        self.assertTrue(coverage["outside_initial_slice"])
        self.assertEqual(len(coverage["outside_initial_slice_citations"]), 1)


class PendingQueueTests(unittest.TestCase):
    def test_composed_finding_uses_cited_name_and_drops_incomplete_relief_tail(self):
        finding = {
            "section": "Main case",
            "statement": "Diance C. DeSousa: nuisance; defenses: denial; relief: damages, other just.",
            "citations": [{
                "source_sha256": "a" * 64,
                "filename": "Diane_C_DeSousa_v_Richard_Calvagno_COMPLAINT.pdf",
                "page_number": 1,
            }],
            "authority_citations": [],
        }
        cleaned = WORKER.clean_composed_finding(finding)
        self.assertEqual(
            cleaned["statement"],
            "Diane C. DeSousa: nuisance; defenses: denial; relief: damages.",
        )
        self.assertEqual(finding["statement"], "Diance C. DeSousa: nuisance; defenses: denial; relief: damages, other just.")

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

    def test_pending_requests_accepts_case00_benchmark(self):
        class Case00QueueS3(self.QueueS3):
            def list_objects_v2(self, **kwargs):
                if kwargs.get("Prefix") == "cases/":
                    return {"CommonPrefixes": [{"Prefix": "cases/Case-00-Triborough/"}]}
                return {"Contents": [
                    {"Key": "cases/Case-00-Triborough/derived/draft-requests/draft-3-cccccccccccc.json"}
                ]}

        with mock.patch.object(WORKER, "request_status", return_value="QUEUED"):
            pending = list(WORKER.pending_requests(Case00QueueS3()))
        self.assertEqual(pending, [("Case-00-Triborough", "draft-3-cccccccccccc")])

    def test_compose_validated_layers_reuses_ready_layer_drafts_without_model(self):
        case_id = "NY-NewYork-158068-2018-Szymczyk-v-Hudson-36-37"
        source = "a" * 64
        cite = {"source_sha256": source, "filename": "Pleading.pdf", "page_number": 1}
        ids = {
            "main": "draft-100-aaaaaaaaaaaa",
            "counter": "draft-200-bbbbbbbbbbbb",
            "third": "draft-300-cccccccccccc",
            "prior_composition": "draft-400-dddddddddddd",
        }
        def draft(request_id, question, section, statement):
            return {
                "schema_version": "legalai-internal-draft.v1",
                "case_id": case_id,
                "request_id": request_id,
                "question": question,
                "external_communication": False,
                "summary": "Validated layer.",
                "findings": [{"section": section, "statement": statement, "citations": [cite], "authority_citations": []}],
                "missing_information": [],
                "limitations": [],
            }
        objects = {}
        for layer, request_id in ids.items():
            objects[WORKER.key(case_id, request_id, "status.json")] = {"status": "READY"}
        objects[WORKER.key(case_id, ids["main"], "draft.json")] = draft(
            ids["main"], "Validate the main case.", "Main case",
            "Plaintiff against Defendant: negligence; defenses: limitations; relief: damages.",
        )
        objects[WORKER.key(case_id, ids["counter"], "draft.json")] = draft(
            ids["counter"], "Validate Quality Facilities counterclaims and cross-claims.", "Counterclaims and cross-claims",
            "Quality Facilities against Defendants: negligence; defenses: denial; relief: judgment over.",
        )
        third_statement = (
            "First action — A v. B: indemnification; defenses: limitations; relief: judgment over. "
            "Second action — C v. D: contribution; defenses: waiver; relief: damages. "
            "Third action — E v. F: breach; defenses: unresolved; relief: damages; no corresponding answer was identified. "
            "Fourth action — G v. H: indemnification; defenses: estoppel; relief: dismissal."
        )
        objects[WORKER.key(case_id, ids["third"], "draft.json")] = draft(
            ids["third"], "Validate the third-party-claims layer separately.", "Third-party claims", third_statement,
        )
        objects[WORKER.key(case_id, ids["third"], "input_audit.json")] = {
            "coverage": {"third_party_actions": [
                {"ordinal": "first", "answer_present": True},
                {"ordinal": "second", "answer_present": True},
                {"ordinal": "third", "answer_present": False},
                {"ordinal": "fourth", "answer_present": True},
            ]}
        }
        objects[WORKER.key(case_id, ids["prior_composition"], "draft.json")] = draft(
            ids["prior_composition"],
            "Prior consolidated map: Main case; Counterclaims and cross-claims; Third-party claims.",
            "Main case",
            "Prior composition: claims; defenses: limitations; relief: damages.",
        )
        class CompositionS3:
            def list_objects_v2(self, **kwargs):
                return {"Contents": [{"Key": key} for key in objects if key.endswith("/draft.json")]}
            def get_object(self, **kwargs):
                return {"Body": io.BytesIO(json.dumps(objects[kwargs["Key"]]).encode())}
        question = "Prepare one consolidated map in order: Main case; Counterclaims and cross-claims; Third-party claims. Identify parties, claims, defenses, and relief."
        with mock.patch.dict(os.environ, {"B2_BUCKET": "test"}):
            result, pages, coverage = WORKER.compose_validated_layers(CompositionS3(), case_id, question)
        self.assertEqual([item["section"] for item in result["findings"]], list(WORKER.LITIGATION_MAP_SECTIONS))
        self.assertEqual(coverage["composition_sources"], {
            "Main case": ids["main"],
            "Counterclaims and cross-claims": ids["counter"],
            "Third-party claims": ids["third"],
        })
        self.assertEqual(len(pages), 1)

    def test_run_request_dispatches_case00_to_benchmark_worker(self):
        benchmark_worker = types.SimpleNamespace(run_request=mock.Mock())
        with mock.patch.object(WORKER, "request_status", return_value="QUEUED"), mock.patch.dict(sys.modules, {"scripts.run_case00_internal_draft": benchmark_worker}):
            WORKER.run_request("client", "Case-00-Triborough", "draft-3-cccccccccccc")
        benchmark_worker.run_request.assert_called_once_with("client", "draft-3-cccccccccccc")

    def test_cancelled_case00_is_not_dispatched(self):
        benchmark_worker = types.SimpleNamespace(run_request=mock.Mock())
        with mock.patch.object(WORKER, "request_status", return_value="CANCELLED"), mock.patch.dict(sys.modules, {"scripts.run_case00_internal_draft": benchmark_worker}):
            WORKER.run_request("client", "Case-00-Triborough", "draft-3-cccccccccccc")
        benchmark_worker.run_request.assert_not_called()

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

    def test_model_http_failure_records_stage_and_safe_diagnostics(self):
        case_id = "NY-NewYork-158068-2018-Szymczyk-v-Hudson-36-37"
        request_id = "draft-3-cccccccccccc"
        http_error = WORKER.urllib.error.HTTPError(
            "https://api.openai.com/v1/responses", 429, "secret response text", {}, None
        )
        writes = []
        with mock.patch.object(WORKER, "put", side_effect=lambda *args: writes.append(args[3:])), \
             mock.patch.object(WORKER, "read_request", return_value="Identify claims."), \
             mock.patch.object(WORKER, "evidence", return_value=[]), \
             mock.patch.object(WORKER, "match_verified_authorities", return_value=()), \
             mock.patch.object(WORKER, "generate", side_effect=http_error), \
             mock.patch.object(WORKER, "request_status", return_value="QUEUED"), \
             mock.patch.object(WORKER, "log_failure") as log_failure:
            with self.assertRaises(WORKER.urllib.error.HTTPError):
                WORKER.run_request("client", case_id, request_id)
        failed = next(value for name, value in writes if name == "status.json" and value["status"] == "FAILED")
        self.assertEqual(failed["failure_code"], "model_http_error")
        self.assertEqual(failed["failure_stage"], "model_request")
        self.assertEqual(failed["exception_type"], "httperror")
        self.assertEqual(failed["http_status"], 429)
        self.assertNotIn("secret response text", json.dumps(failed))
        log_failure.assert_called_once()

    def test_failure_log_excludes_exception_message(self):
        diagnostics = WORKER.failure_diagnostics(ValueError("private source text"), "model_validation")
        stream = io.StringIO()
        with mock.patch.object(WORKER.sys, "stderr", stream):
            WORKER.log_failure("NY-NewYork-158068-2018-Szymczyk-v-Hudson-36-37", "draft-3-cccccccccccc", diagnostics)
        entry = json.loads(stream.getvalue())
        self.assertEqual(entry["failure_code"], "model_output_validation")
        self.assertEqual(entry["failure_stage"], "model_validation")
        self.assertNotIn("private source text", stream.getvalue())

    def test_pre_generation_gate_persists_only_allowlisted_reason(self):
        known = WORKER.failure_diagnostics(
            WORKER.PreGenerationGateError("ambiguous_third_party_answer"),
            "evidence_retrieval",
        )
        self.assertEqual(known["failure_code"], "pre_generation_gate")
        self.assertEqual(known["gate_reason"], "ambiguous_third_party_answer")

        unknown = WORKER.failure_diagnostics(
            WORKER.PreGenerationGateError("private source text"),
            "evidence_retrieval",
        )
        self.assertEqual(unknown["gate_reason"], "unspecified_pre_generation_gate")
        self.assertNotIn("private source text", json.dumps(unknown))

    def test_model_validation_persists_only_allowlisted_reason(self):
        known = WORKER.failure_diagnostics(
            ValueError("verified pleading called missing"),
            "model_validation",
        )
        self.assertEqual(known["failure_code"], "model_output_validation")
        self.assertEqual(
            known["validation_reason"],
            "verified_pleading_called_missing",
        )
        field_specific = WORKER.failure_diagnostics(
            ValueError("incomplete output counterclaims and cross claims"),
            "model_validation",
        )
        self.assertEqual(
            field_specific["validation_reason"],
            "incomplete_output_counterclaims_and_cross_claims",
        )
        field_subtype = WORKER.failure_diagnostics(
            ValueError("incomplete output counterclaims and cross claims connector ended"),
            "model_validation",
        )
        self.assertEqual(
            field_subtype["validation_reason"],
            "incomplete_output_counterclaims_and_cross_claims_connector_ended",
        )

        unknown = WORKER.failure_diagnostics(
            ValueError("private model output"),
            "model_validation",
        )
        self.assertEqual(
            unknown["validation_reason"],
            "unspecified_model_validation",
        )
        self.assertNotIn("private model output", json.dumps(unknown))

    def test_retrieval_diagnostic_backfills_reason_without_model_call(self):
        case_id = "NY-NewYork-158068-2018-Szymczyk-v-Hudson-36-37"
        request_id = "draft-3-cccccccccccc"
        status = {
            "schema_version": "legalai-internal-draft-status.v1",
            "case_id": case_id,
            "request_id": request_id,
            "status": "FAILED",
            "failure_code": "pre_generation_gate",
            "failure_stage": "evidence_retrieval",
            "updated_at": "2026-09-18T17:29:19Z",
        }
        s3 = mock.Mock()
        s3.get_object.return_value = {
            "Body": io.BytesIO(json.dumps(status).encode("utf-8"))
        }
        writes = []
        with mock.patch.object(WORKER, "read_request", return_value="third-party claims layer"), \
             mock.patch.object(WORKER, "evidence", side_effect=WORKER.PreGenerationGateError("ambiguous_third_party_answer")), \
             mock.patch.object(WORKER, "generate") as generate, \
             mock.patch.object(WORKER, "put", side_effect=lambda *args: writes.append(args[3:])):
            reason, detail, metrics = WORKER.diagnose_failed_retrieval(
                s3, case_id, request_id
            )
        self.assertEqual(reason, "ambiguous_third_party_answer")
        self.assertIsNone(detail)
        self.assertIsNone(metrics)
        self.assertEqual(writes[0][0], "status.json")
        self.assertEqual(writes[0][1]["gate_reason"], reason)
        self.assertEqual(writes[0][1]["updated_at"], status["updated_at"])
        generate.assert_not_called()

    def test_third_party_identity_gate_reports_only_allowlisted_subtype(self):
        duplicate = WORKER.failure_diagnostics(
            WORKER.PreGenerationGateError(
                "ambiguous_third_party_action_identity",
                "duplicate_explicit_ordinal",
            ),
            "evidence_retrieval",
        )
        self.assertEqual(duplicate["gate_detail"], "duplicate_explicit_ordinal")

        private = WORKER.failure_diagnostics(
            WORKER.PreGenerationGateError(
                "ambiguous_third_party_action_identity",
                "private source text",
            ),
            "evidence_retrieval",
        )
        self.assertNotIn("gate_detail", private)

    def test_pre_generation_gate_metrics_are_count_only_and_allowlisted(self):
        diagnostics = WORKER.failure_diagnostics(
            WORKER.PreGenerationGateError(
                "missing_first_affirmative_defense_page",
                metrics={
                    "mandatory_page_count": 48,
                    "missing_mandatory_page_count": 3,
                    "selected_page_count": 45,
                    "private_filename": "Answer.pdf",
                    "candidate_section_count": True,
                },
            ),
            "evidence_retrieval",
        )
        self.assertEqual(
            diagnostics["gate_metrics"],
            {
                "mandatory_page_count": 48,
                "missing_mandatory_page_count": 3,
                "selected_page_count": 45,
            },
        )

    def test_scan_worker_status_preserves_request_failure_diagnostics(self):
        case_id = "NY-NewYork-158068-2018-Szymczyk-v-Hudson-36-37"
        request_id = "draft-3-cccccccccccc"
        failure = RuntimeError("private")
        failure._legalai_failure_diagnostics = {
            "failure_code": "persistence_error",
            "failure_stage": "audit_write",
            "exception_type": "runtimeerror",
        }
        statuses = []
        with mock.patch.object(WORKER, "client", return_value="client"), \
             mock.patch.object(WORKER, "pending_requests", return_value=iter([(case_id, request_id)])), \
             mock.patch.object(WORKER, "run_request", side_effect=failure), \
             mock.patch.object(WORKER, "write_worker_status", side_effect=lambda *args, **kwargs: statuses.append((args, kwargs))), \
             mock.patch.object(WORKER.sys, "argv", ["worker", "--scan-pending"]):
            WORKER.main()
        _, failed = statuses[-1]
        self.assertEqual(failed["failure_code"], "persistence_error")
        self.assertEqual(failed["failure_stage"], "audit_write")
        self.assertEqual(failed["request_id"], request_id)


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

    def test_main_action_question_does_not_require_successive_third_party_layers(self):
        class LayeredPleadingS3(FakeS3):
            pages = [
                {"filename": "SUMMONS___COMPLAINT_1.pdf", "page_number": 1,
                 "text": "Andrzej Szymczyk, plaintiff, against Hudson 36 LLC and Hudson 37 LLC."},
                {"filename": "SUMMONS___COMPLAINT_1.pdf", "page_number": 8,
                 "text": "LABOR LAW SECTION 240(1)."},
                {"filename": "SUMMONS___COMPLAINT_1.pdf", "page_number": 9,
                 "text": "LABOR LAW SECTION 241(6)."},
                {"filename": "SUMMONS___COMPLAINT_1.pdf", "page_number": 10,
                 "text": "NEGLIGENCE AND LABOR LAW SECTION 200."},
                {"filename": "SUMMONS___COMPLAINT_1.pdf", "page_number": 11,
                 "text": "Plaintiff demands judgment for damages, costs and disbursements."},
                {"filename": "ANSWER_3.pdf", "page_number": 1,
                 "text": "Hudson 36 LLC and Hudson 37 LLC answer the complaint."},
                {"filename": "ANSWER_3.pdf", "page_number": 3,
                 "text": "AFFIRMATIVE DEFENSES. Failure to state a cause of action."},
            ] + [
                {"filename": f"THIRD_PARTY_COMPLAINT_{index}.pdf", "page_number": 1,
                 "text": "Third-party complaint for contractual indemnification. WHEREFORE judgment is demanded."}
                for index in range(50)
            ]

        pages = WORKER.evidence(
            LayeredPleadingS3(),
            "NY-NewYork-158068-2018-Szymczyk-v-Hudson-36-37",
            "Based solely on the verified record, identify the plaintiff's claims against Hudson 36 LLC and Hudson 37 LLC, each party's role, the requested relief, and the defendants' strongest expressly pleaded defenses.",
        )
        selected = {(page["filename"], page["page_number"]) for page in pages}
        self.assertTrue({
            ("SUMMONS___COMPLAINT_1.pdf", 1),
            ("SUMMONS___COMPLAINT_1.pdf", 8),
            ("SUMMONS___COMPLAINT_1.pdf", 9),
            ("SUMMONS___COMPLAINT_1.pdf", 10),
            ("SUMMONS___COMPLAINT_1.pdf", 11),
            ("ANSWER_3.pdf", 1),
            ("ANSWER_3.pdf", 3),
        }.issubset(selected))
        self.assertFalse(any("THIRD_PARTY" in filename for filename, _page in selected))

    def test_main_action_scope_survives_plain_apostrophe_normalization(self):
        self.assertIsNotNone(WORKER.MAIN_ACTION_ONLY_QUESTION_RE.search(
            "Identify the plaintiffs claims against Hudson 36 LLC and Hudson 37 LLC; "
            "cite the operative complaint and answer pages."
        ))
        self.assertIsNotNone(WORKER.MAIN_ACTION_ONLY_QUESTION_RE.search(
            "Identify the plaintiffs' claims against Calvagno and Karcher."
        ))

    def test_main_action_excludes_nyscef_abbreviated_related_pleadings(self):
        class ProductionNamesS3(FakeS3):
            pages = [
                {"filename": "158068_2018_SUMMONS___COMPLAINT_1.pdf", "page_number": 1,
                 "text": "Andrzej Szymczyk against Hudson 36 LLC and Hudson 37 LLC."},
                {"filename": "158068_2018_ANSWER_3.pdf", "page_number": 3,
                 "text": "AFFIRMATIVE DEFENSES."},
                {"filename": "158068_2018_ANSWER_TO_THIRD_PAR_10.pdf", "page_number": 14,
                 "text": "General denial."},
                {"filename": "158068_2018_ANSWER_WITH_CROSS_C_81.pdf", "page_number": 3,
                 "text": "General denial."},
                {"filename": "158068_2018_BILL_OF_PARTICULARS_11.pdf", "page_number": 4,
                 "text": "Plaintiff alleges negligence."},
            ]

        pages = WORKER.evidence(
            ProductionNamesS3(),
            "NY-NewYork-158068-2018-Szymczyk-v-Hudson-36-37",
            "Identify the plaintiff's claims against Hudson 36 LLC and Hudson 37 LLC; "
            "cite the operative complaint and answer pages.",
        )
        selected = {page["filename"] for page in pages}
        self.assertIn("158068_2018_SUMMONS___COMPLAINT_1.pdf", selected)
        self.assertIn("158068_2018_ANSWER_3.pdf", selected)
        self.assertFalse(any("THIRD_PAR" in filename for filename in selected))
        self.assertFalse(any("CROSS_C" in filename for filename in selected))
        self.assertFalse(any("BILL_OF_PARTICULARS" in filename for filename in selected))

    def test_main_action_excludes_derivative_answer_exhibits_before_defense_gate(self):
        class DerivativeAnswerCopiesS3(FakeS3):
            pages = [
                {
                    "filename": "SUMMONS___COMPLAINT_1.pdf",
                    "page_number": 1,
                    "text": (
                        "Thomas DeSousa, plaintiff, against Joseph Calvagno II "
                        "and Patrick Karcher, defendants."
                    ),
                },
                {
                    "filename": "ANSWER_2.pdf",
                    "page_number": 1,
                    "text": "Joseph Calvagno II answers the verified complaint.",
                },
                {
                    "filename": "ANSWER_2.pdf",
                    "page_number": 3,
                    "text": "AS FOR A FIRST AFFIRMATIVE DEFENSE.",
                },
            ] + [
                {
                    "filename": f"EXHIBIT_{index}_ANSWER_COPY.pdf",
                    "page_number": 2,
                    "text": (
                        "AS FOR A FIRST AFFIRMATIVE DEFENSE parties claims "
                        "defenses relief."
                    ),
                }
                for index in range(WORKER.MAX_PAGES + 1)
            ]

        pages = WORKER.evidence(
            DerivativeAnswerCopiesS3(),
            "NY-Suffolk-600371-2021-DeSousa-v-Calvagno-II-Karcher",
            (
                "Identify the plaintiffs' claims against Joseph Calvagno II "
                "and Patrick Karcher, the requested relief, and defenses."
            ),
        )
        selected = {(page["filename"], page["page_number"]) for page in pages}
        self.assertIn(("ANSWER_2.pdf", 3), selected)
        self.assertFalse(any(filename.startswith("EXHIBIT_") for filename, _ in selected))

    def test_main_action_deduplicates_identical_answers_across_source_sets(self):
        answer_pages = [
            (1, "Joseph Calvagno II answers the verified complaint."),
            (3, "AS FOR A FIRST AFFIRMATIVE DEFENSE."),
        ]

        class DuplicateSourceAnswersS3(FakeS3):
            pages = [
                {
                    "filename": "SUMMONS___COMPLAINT_1.pdf",
                    "page_number": 1,
                    "text": (
                        "Thomas DeSousa, plaintiff, against Joseph Calvagno II "
                        "and Patrick Karcher, defendants."
                    ),
                },
            ] + [
                {
                    "source_sha256": f"{index:064x}",
                    "filename": f"ANSWER_COPY_{index}.pdf",
                    "page_number": page,
                    "text": text,
                }
                for index in range(WORKER.MAX_PAGES + 1)
                for page, text in answer_pages
            ]

        pages = WORKER.evidence(
            DuplicateSourceAnswersS3(),
            "NY-Suffolk-600371-2021-DeSousa-v-Calvagno-II-Karcher",
            (
                "Identify the plaintiffs' claims against Joseph Calvagno II "
                "and Patrick Karcher, the requested relief, and defenses."
            ),
        )
        selected_answers = {
            (page["source_sha256"], page["filename"])
            for page in pages
            if "ANSWER_COPY" in page["filename"]
        }
        self.assertEqual(len(selected_answers), 1)


    def test_counterclaim_crossclaim_question_excludes_main_and_third_party_layers(self):
        class LayeredCrossClaimS3(FakeS3):
            pages = [
                {"filename": "SUMMONS___COMPLAINT_1.pdf", "page_number": 1,
                 "text": "Andrzej Szymczyk against Hudson 36 LLC and Hudson 37 LLC."},
                {"filename": "ANSWER_3.pdf", "page_number": 3,
                 "text": "AFFIRMATIVE DEFENSES to the complaint."},
                {"filename": "ANSWER_WITH_CROSS_C_81.pdf", "page_number": 1,
                 "text": "ANSWER WITH CROSS-CLAIMS AND COUNTERCLAIM."},
                {"filename": "ANSWER_WITH_CROSS_C_81.pdf", "page_number": 6,
                 "text": "CROSS-CLAIM for negligence. WHEREFORE judgment is demanded."},
                {"filename": "REPLY_TO_COUNTERCLAIM_82.pdf", "page_number": 1,
                 "text": "REPLY TO COUNTERCLAIM and affirmative defenses."},
                {"filename": "ANSWER_TO_THIRD_PAR_10.pdf", "page_number": 14,
                 "text": "ANSWER TO THIRD-PARTY COMPLAINT."},
                {"filename": "EXHIBIT_S__155.pdf", "page_number": 3,
                 "text": "QUALITY FACILITIES SOLUTIONS CORP. cross-claim evidence and requested relief."},
                {"filename": "TRIAL_DOCUMENTS_453.pdf", "page_number": 53,
                 "text": "QUALITY FACILITIES SOLUTIONS CORP. counterclaim and defenses."},
            ]

        pages = WORKER.evidence(
            LayeredCrossClaimS3(),
            "NY-NewYork-158068-2018-Szymczyk-v-Hudson-36-37",
            "Identify all counterclaims and cross-claims in the main action, the parties, relief, and defenses.",
        )
        selected = {page["filename"] for page in pages}
        self.assertIn("ANSWER_WITH_CROSS_C_81.pdf", selected)
        self.assertIn("REPLY_TO_COUNTERCLAIM_82.pdf", selected)
        self.assertNotIn("SUMMONS___COMPLAINT_1.pdf", selected)
        self.assertNotIn("ANSWER_3.pdf", selected)
        self.assertNotIn("ANSWER_TO_THIRD_PAR_10.pdf", selected)

    def test_counterclaim_slice_keeps_caption_all_claims_and_prayer(self):
        class MultiClaimCounterS3(FakeS3):
            pages = [
                {"filename": "ANSWER_WITH_COUNTER_4.pdf", "page_number": 1,
                 "text": "SUPREME COURT. Richard Roe, defendant and counterclaimant, against Pat Doe."},
                {"filename": "ANSWER_WITH_COUNTER_4.pdf", "page_number": 2,
                 "text": "FIRST COUNTERCLAIM. Malicious prosecution."},
                {"filename": "ANSWER_WITH_COUNTER_4.pdf", "page_number": 3,
                 "text": "SECOND COUNTERCLAIM. Private nuisance."},
                {"filename": "ANSWER_WITH_COUNTER_4.pdf", "page_number": 4,
                 "text": "THIRD COUNTERCLAIM. Harassment."},
                {"filename": "ANSWER_WITH_COUNTER_4.pdf", "page_number": 5,
                 "text": "FOURTH COUNTERCLAIM. Menacing."},
                {"filename": "ANSWER_WITH_COUNTER_4.pdf", "page_number": 6,
                 "text": "FIFTH CAUSE OF ACTION. Intentional infliction of emotional distress."},
                {"filename": "ANSWER_WITH_COUNTER_4.pdf", "page_number": 7,
                 "text": "WHEREFORE counterclaimant demands judgment and punitive damages."},
                {"filename": "COMPLAINT_2.pdf", "page_number": 1,
                 "text": "Plaintiff alleges an unrelated main-action claim."},
            ]

        pages = WORKER.evidence(
            MultiClaimCounterS3(),
            "NY-Suffolk-600371-2021-DeSousa-v-Calvagno-II-Karcher",
            "Separately validate only the counterclaim and cross-claim layer, including parties, claims, defenses, and relief.",
        )

        self.assertEqual(
            set(range(1, 8)),
            {
                page["page_number"]
                for page in pages
                if page["filename"] == "ANSWER_WITH_COUNTER_4.pdf"
            },
        )
        self.assertNotIn("COMPLAINT_2.pdf", {page["filename"] for page in pages})

    def test_main_action_slice_keeps_multi_page_prayer_continuation(self):
        class MultiPagePrayerS3(FakeS3):
            pages = [
                {"filename": "COMPLAINT_2.pdf", "page_number": 1,
                 "text": "SUPREME COURT. Plaintiffs against defendants."},
                {"filename": "COMPLAINT_2.pdf", "page_number": 2,
                 "text": "FIRST CAUSE OF ACTION. Private nuisance."},
                {"filename": "COMPLAINT_2.pdf", "page_number": 3,
                 "text": "Supporting allegations."},
                {"filename": "COMPLAINT_2.pdf", "page_number": 4,
                 "text": "WHEREFORE plaintiffs demand declaratory judgment."},
                {"filename": "COMPLAINT_2.pdf", "page_number": 5,
                 "text": "A. An injunction abating the condition."},
                {"filename": "COMPLAINT_2.pdf", "page_number": 6,
                 "text": "B. Compensatory and punitive monetary recovery."},
                {"filename": "COMPLAINT_2.pdf", "page_number": 7,
                 "text": "C. Such other and further relief as the Court deems just."},
            ]

        pages = WORKER.evidence(
            MultiPagePrayerS3(),
            "NY-Suffolk-600371-2021-DeSousa-v-Calvagno-II-Karcher",
            WORKER.RETRIEVAL_VALIDATION_PROFILES["main-action"],
        )

        selected = {
            page["page_number"] for page in pages
            if page["filename"] == "COMPLAINT_2.pdf"
        }
        self.assertTrue({4, 5, 6, 7}.issubset(selected))

    def test_party_specific_every_counterclaim_question_uses_crossclaim_slice(self):
        class PartySpecificCrossClaimS3(FakeS3):
            pages = [
                {"filename": "SUMMONS___COMPLAINT_1.pdf", "page_number": 1,
                 "text": "Andrzej Szymczyk against Hudson 36 LLC and Hudson 37 LLC."},
                {"filename": "ANSWER_3.pdf", "page_number": 3,
                 "text": "AFFIRMATIVE DEFENSES to the complaint."},
                {"filename": "ANSWER_WITH_CROSS_C_81.pdf", "page_number": 1,
                 "text": "QUALITY FACILITIES SOLUTIONS CORP. ANSWER WITH CROSS-CLAIMS AND COUNTERCLAIM."},
                {"filename": "ANSWER_WITH_CROSS_C_81.pdf", "page_number": 6,
                 "text": "QUALITY FACILITIES SOLUTIONS CORP. CROSS-CLAIM for negligence."},
                {"filename": "REPLY_TO_COUNTERCLAIM_82.pdf", "page_number": 1,
                 "text": "REPLY TO QUALITY FACILITIES SOLUTIONS CORP. COUNTERCLAIM."},
                {"filename": "ANSWER_WITH_CROSS_C_90.pdf", "page_number": 1,
                 "text": "HORSEPOWER ELECTRIC AND MAINTENANCE CORP. ANSWER WITH CROSS-CLAIMS."},
                {"filename": "ANSWER_WITH_CROSS_C_90.pdf", "page_number": 6,
                 "text": "HORSEPOWER ELECTRIC AND MAINTENANCE CORP. CROSS-CLAIM for negligence."},
                {"filename": "ANSWER_TO_THIRD_PAR_10.pdf", "page_number": 14,
                 "text": "ANSWER TO THIRD-PARTY COMPLAINT."},
            ]

        PartySpecificCrossClaimS3.pages.extend(
            {
                "filename": f"ANSWER_WITH_CROSS_C_{100 + index}.pdf",
                "page_number": 1,
                "text": f"UNRELATED PARTY {index} ANSWER WITH CROSS-CLAIMS AND AFFIRMATIVE DEFENSES.",
            }
            for index in range(50)
        )

        pages = WORKER.evidence(
            PartySpecificCrossClaimS3(),
            "NY-NewYork-158068-2018-Szymczyk-v-Hudson-36-37",
            "Based solely on the verified record, identify every counterclaim and cross-claim asserted by Quality Facilities Solutions Corp., the parties against whom each is asserted, the requested relief, and the strongest expressly pleaded defenses. Cite only the operative pleading and reply pages.",
        )
        selected = {page["filename"] for page in pages}
        self.assertEqual(
            {"ANSWER_WITH_CROSS_C_81.pdf", "REPLY_TO_COUNTERCLAIM_82.pdf"},
            selected,
        )


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

    def test_third_party_layer_reserves_each_successive_complaint(self):
        class SuccessiveThirdPartyS3(FakeS3):
            pages = [
                {"filename": "SUMMONS___COMPLAINT_1.pdf", "page_number": 1,
                 "text": "Plaintiff against defendants in the main action."},
                {"filename": "ANSWER_WITH_CROSS_C_81.pdf", "page_number": 1,
                 "text": "Counterclaims and cross-claims only."},
            ]

        for index, ordinal in enumerate(("", "SECOND_", "THIRD_", "FOURTH_"), start=1):
            filename = f"{ordinal}THIRD_PARTY_SUMMONS_{index}.pdf"
            SuccessiveThirdPartyS3.pages.extend([
                {"filename": filename, "page_number": 1,
                 "text": f"{ordinal.replace('_', ' ')}THIRD-PARTY PLAINTIFF against third-party defendant."},
                {"filename": filename, "page_number": 4,
                 "text": "FIRST CAUSE OF ACTION for contractual indemnification."},
                {"filename": filename, "page_number": 7,
                 "text": "WHEREFORE judgment, indemnification, costs, and disbursements are demanded."},
            ])
        SuccessiveThirdPartyS3.pages.extend([
            {"filename": "EXHIBIT_S__150.pdf", "page_number": 1,
             "text": "Exhibit copy of an answer to third-party complaint."},
            {"filename": "AFFIDAVIT_OR_AFFIRM_60.pdf", "page_number": 1,
             "text": "Attached third-party pleading described in an affirmation."},
        ])

        pages = WORKER.evidence(
            SuccessiveThirdPartyS3(),
            "NY-NewYork-158068-2018-Szymczyk-v-Hudson-36-37",
            "Validate the third-party-claims layer separately from the main action and all counterclaims/cross-claims. Identify the parties, claims, defenses, and relief.",
        )
        selected = {(page["filename"], page["page_number"]) for page in pages}
        for index, ordinal in enumerate(("", "SECOND_", "THIRD_", "FOURTH_"), start=1):
            filename = f"{ordinal}THIRD_PARTY_SUMMONS_{index}.pdf"
            self.assertTrue({(filename, 1), (filename, 4), (filename, 7)}.issubset(selected))
        excluded = {
            "SUMMONS___COMPLAINT_1.pdf",
            "ANSWER_WITH_CROSS_C_81.pdf",
            "EXHIBIT_S__150.pdf",
            "AFFIDAVIT_OR_AFFIRM_60.pdf",
        }
        self.assertFalse(any(filename in excluded for filename, _ in selected))

    def test_third_party_layer_slices_four_actions_and_pairs_answers(self):
        filler = "third-party claims defenses relief " * 120

        class FourActionS3(FakeS3):
            pages = []

        parties = (("Alpha", "Able"), ("Bravo", "Baker"), ("Charlie", "Cedar"), ("Delta", "Dover"))
        for index, (ordinal, names) in enumerate(zip(("", "SECOND_", "THIRD_", "FOURTH_"), parties), start=1):
            label = ordinal.replace("_", " ")
            complaint = f"{ordinal}THIRD_PARTY_SUMMONS_{index}.pdf"
            answer = f"{ordinal}ANSWER_TO_THIRD_PARTY_COMPLAINT_{index}.pdf"
            FourActionS3.pages.extend([
                {"filename": complaint, "page_number": 1, "text": f"{label}THIRD-PARTY COMPLAINT. {names[0]} against {names[1]}."},
                {"filename": complaint, "page_number": 3, "text": f"FIRST CAUSE OF ACTION contractual indemnification. {filler}"},
                {"filename": complaint, "page_number": 7, "text": "WHEREFORE judgment, costs and disbursements are demanded."},
                {"filename": answer, "page_number": 1, "text": f"ANSWER TO {label}THIRD-PARTY COMPLAINT. {names[1]} answers {names[0]}."},
                {"filename": answer, "page_number": 4, "text": f"AFFIRMATIVE DEFENSES. {filler}"},
                {"filename": answer, "page_number": 9, "text": "WHEREFORE dismissal is demanded."},
            ])
        FourActionS3.pages.extend([
            {"filename": f"EXHIBIT_S_{i}.pdf", "page_number": 1, "text": filler}
            for i in range(60)
        ])

        pages = WORKER.evidence(
            FourActionS3(),
            "NY-NewYork-158068-2018-Szymczyk-v-Hudson-36-37",
            "Validate the third-party-claims layer separately from the main action and all counterclaims/cross-claims. Identify the parties, claims, defenses, and relief.",
        )
        actions = pages.coverage["third_party_actions"]
        self.assertEqual([item["ordinal"] for item in actions], ["first", "second", "third", "fourth"])
        self.assertTrue(all(item["answer_present"] for item in actions))
        self.assertLessEqual(len(pages), WORKER.MAX_PAGES)
        for ordinal in ("", "SECOND_", "THIRD_", "FOURTH_"):
            self.assertTrue(any(page["filename"].startswith(f"{ordinal}THIRD_PARTY_SUMMONS") for page in pages))
            self.assertTrue(any(page["filename"].startswith(f"{ordinal}ANSWER_TO_THIRD_PARTY") for page in pages))

    def test_consolidated_map_preserves_main_cross_and_third_party_layers(self):
        class ConsolidatedS3(FakeS3):
            pages = [
                {"filename": "SUMMONS___COMPLAINT_1.pdf", "page_number": 1, "text": "Plaintiff against Defendant."},
                {"filename": "SUMMONS___COMPLAINT_1.pdf", "page_number": 3, "text": "FIRST CAUSE OF ACTION: negligence."},
                {"filename": "ANSWER_WITH_CROSS_C_3.pdf", "page_number": 1, "text": "Defendant answers and asserts a cross-claim."},
                {"filename": "ANSWER_WITH_CROSS_C_3.pdf", "page_number": 3, "text": "FIRST CROSS-CLAIM: contribution. WHEREFORE judgment is demanded."},
            ]

        filings = ((5, 10), (13, 19), (65, 70), (74, 86))
        for index, (complaint_number, answer_number) in enumerate(filings, start=1):
            ConsolidatedS3.pages.extend([
                {"filename": f"THIRD_PARTY_SUMMONS_{complaint_number}.pdf", "page_number": 1, "text": f"Third-party complaint action {index}. Alpha{index} against Able{index}."},
                {"filename": f"THIRD_PARTY_SUMMONS_{complaint_number}.pdf", "page_number": 3, "text": "FIRST CAUSE OF ACTION: contractual indemnification. WHEREFORE judgment is demanded."},
                {"filename": f"ANSWER_TO_THIRD_PARTY_{answer_number}.pdf", "page_number": 1, "text": f"Answer to third-party complaint. Able{index} answers Alpha{index}."},
                {"filename": f"ANSWER_TO_THIRD_PARTY_{answer_number}.pdf", "page_number": 3, "text": "FIRST AFFIRMATIVE DEFENSE. WHEREFORE dismissal is demanded."},
            ])

        pages = WORKER.evidence(
            ConsolidatedS3(),
            "NY-NewYork-158068-2018-Szymczyk-v-Hudson-36-37",
            "Prepare one consolidated map in order: Main case; Counterclaims and cross-claims; Third-party claims. Identify parties, claims, defenses, and relief.",
        )
        selected = {page["filename"] for page in pages}
        self.assertIn("SUMMONS___COMPLAINT_1.pdf", selected)
        self.assertIn("ANSWER_WITH_CROSS_C_3.pdf", selected)
        self.assertEqual(
            [action["ordinal"] for action in pages.coverage["third_party_actions"]],
            ["first", "second", "third", "fourth"],
        )

    def test_consolidated_map_fails_closed_on_unanswered_third_party_action(self):
        class UnansweredActionS3(FakeS3):
            pages = [
                {"filename": "COMPLAINT_1.pdf", "page_number": 1,
                 "text": "Plaintiff against Defendant for negligence."},
                {"filename": "THIRD_PARTY_SUMMONS_5.pdf", "page_number": 1,
                 "text": "Third-party complaint. Alpha against Able."},
            ]

        with self.assertRaisesRegex(
            WORKER.PreGenerationGateError,
            "unresolved_third_party_action",
        ):
            WORKER.evidence(
                UnansweredActionS3(),
                "NY-NewYork-158068-2018-Szymczyk-v-Hudson-36-37",
                WORKER.RETRIEVAL_VALIDATION_PROFILES["consolidated"],
            )

    def test_third_party_layer_groups_same_ordinal_complaint_filings(self):
        class SplitComplaintS3(FakeS3):
            pages = [
                {"filename": "SECOND_THIRD_PARTY_SUMMONS_13.pdf", "page_number": 1,
                 "text": "Second third-party summons. Bravo against Baker."},
                {"filename": "SECOND_THIRD_PARTY_COMPLAINT_14.pdf", "page_number": 1,
                 "text": "Second third-party complaint. Bravo against Baker."},
                {"filename": "SECOND_THIRD_PARTY_COMPLAINT_14.pdf", "page_number": 4,
                 "text": "FIRST CAUSE OF ACTION for contractual indemnification."},
                {"filename": "SECOND_ANSWER_TO_THIRD_PARTY_COMPLAINT_20.pdf", "page_number": 1,
                 "text": "Answer to second third-party complaint. Baker answers Bravo."},
                {"filename": "THIRD_PARTY_COMPLAINT_5.pdf", "page_number": 1,
                 "text": "Third-party complaint. Alpha against Able."},
            ]

        pages = WORKER.evidence(
            SplitComplaintS3(),
            "NY-NewYork-158068-2018-Szymczyk-v-Hudson-36-37",
            "Validate the third-party-claims layer separately from the main action.",
        )
        actions = pages.coverage["third_party_actions"]
        self.assertEqual([item["ordinal"] for item in actions], ["first", "second"])
        self.assertEqual(
            actions[1]["complaint_filenames"],
            ["SECOND_THIRD_PARTY_COMPLAINT_14.pdf", "SECOND_THIRD_PARTY_SUMMONS_13.pdf"],
        )
        self.assertTrue(actions[1]["answer_present"])

    def test_unlabeled_complaint_joins_unique_caption_match(self):
        documents = {
            ("a" * 64, "SECOND_THIRD_PARTY_SUMMONS_13.pdf"): [
                (1, "Second third-party summons. Bravo Builders against Baker Electric.")
            ],
            ("b" * 64, "SUPPLEMENTAL_COMPLAINT_14.pdf"): [
                (1, "Third-party complaint. Bravo Builders against Baker Electric.")
            ],
            ("c" * 64, "THIRD_PARTY_COMPLAINT_5.pdf"): [
                (1, "Third-party complaint. Alpha Owner against Able Contractor.")
            ],
        }
        actions = WORKER.third_party_action_slices(documents)
        self.assertEqual([item["ordinal"] for item in actions], ["first", "second"])
        self.assertEqual(len(actions[1]["complaints"]), 2)

    def test_multiple_unmatched_unlabeled_complaints_still_fail_closed(self):
        documents = {
            ("a" * 64, "SECOND_THIRD_PARTY_COMPLAINT_13.pdf"): [
                (1, "Second third-party complaint. Bravo against Baker.")
            ],
            ("b" * 64, "THIRD_PARTY_COMPLAINT_5.pdf"): [
                (1, "Third-party complaint. Alpha against Able.")
            ],
            ("c" * 64, "THIRD_PARTY_COMPLAINT_9.pdf"): [
                (1, "Third-party complaint. Charlie against Cedar.")
            ],
        }
        with self.assertRaisesRegex(
            WORKER.PreGenerationGateError,
            "ambiguous_third_party_action_identity",
        ):
            WORKER.third_party_action_slices(documents)

    def test_ordered_unlabeled_clusters_fill_explicit_ordinal_gaps(self):
        documents = {
            ("a" * 64, "SECOND_THIRD_PARTY_COMPLAINT_20.pdf"): [
                (1, "Second third-party complaint. Bravo against Baker.")
            ],
            ("b" * 64, "FOURTH_THIRD_PARTY_COMPLAINT_40.pdf"): [
                (1, "Fourth third-party complaint. Delta against Dover.")
            ],
            ("c" * 64, "THIRD_PARTY_COMPLAINT_10.pdf"): [
                (1, "Third-party complaint. Alpha against Able.")
            ],
            ("d" * 64, "THIRD_PARTY_COMPLAINT_30.pdf"): [
                (1, "Third-party complaint. Charlie against Cedar.")
            ],
        }
        actions = WORKER.third_party_action_slices(documents)
        self.assertEqual(
            [item["ordinal"] for item in actions],
            ["first", "second", "third", "fourth"],
        )
        self.assertEqual(actions[0]["complaint"]["filename"], "THIRD_PARTY_COMPLAINT_10.pdf")
        self.assertEqual(actions[2]["complaint"]["filename"], "THIRD_PARTY_COMPLAINT_30.pdf")

    def test_distinct_third_party_summons_filings_define_successive_actions(self):
        documents = {
            (character * 64, f"THIRD_PARTY_SUMMONS_{filing}.pdf"): [
                (1, "Second third-party summons and complaint. Hudson 37 against contractor.")
            ]
            for character, filing in zip("abcd", (5, 13, 65, 74))
        }
        actions = WORKER.third_party_action_slices(documents)
        self.assertEqual(
            [item["ordinal"] for item in actions],
            ["first", "second", "third", "fourth"],
        )
        self.assertEqual(
            [item["complaint"]["filename"] for item in actions],
            [
                "THIRD_PARTY_SUMMONS_5.pdf",
                "THIRD_PARTY_SUMMONS_13.pdf",
                "THIRD_PARTY_SUMMONS_65.pdf",
                "THIRD_PARTY_SUMMONS_74.pdf",
            ],
        )

    def test_answers_attach_to_most_recent_preceding_summons(self):
        documents = {
            (character * 64, f"THIRD_PARTY_SUMMONS_{filing}.pdf"): [
                (1, "Second third-party summons and complaint. Hudson 37 against contractor.")
            ]
            for character, filing in zip("abcd", (5, 13, 65, 74))
        }
        for character, filing in zip("efg", (10, 19, 86)):
            documents[(character * 64, f"ANSWER_{filing}.pdf")] = [
                (1, "Verified answer to second third-party complaint. Contractor answers Hudson 37.")
            ]
        actions = WORKER.third_party_action_slices(documents)
        self.assertEqual(
            [[answer["filename"] for answer in action["answers"]] for action in actions],
            [["ANSWER_10.pdf"], ["ANSWER_19.pdf"], [], ["ANSWER_86.pdf"]],
        )

    def test_third_party_mentions_do_not_promote_nonpleadings(self):
        documents = {
            ("a" * 64, "THIRD_PARTY_SUMMONS_5.pdf"): [
                (1, "Third-party summons and complaint. Alpha against Able.")
            ],
            ("b" * 64, "MEMORANDUM_OF_LAW_312.pdf"): [
                (1, "This memorandum discusses the third-party complaint and summons.")
            ],
            ("c" * 64, "DECISION_ORDER_354.pdf"): [
                (1, "Decision concerning the second third-party complaint and summons.")
            ],
            ("d" * 64, "ANSWER_19.pdf"): [
                (1, "This answer discusses a third-party complaint but is not captioned as an answer to it.")
            ],
        }
        actions = WORKER.third_party_action_slices(documents)
        self.assertEqual(len(actions), 1)
        self.assertEqual(
            [item["filename"] for item in actions[0]["complaints"]],
            ["THIRD_PARTY_SUMMONS_5.pdf"],
        )
        self.assertEqual(actions[0]["answers"], [])

    def test_third_party_layer_fails_closed_on_unmatched_answer(self):
        class AmbiguousAnswerS3(FakeS3):
            pages = [
                {"filename": "THIRD_PARTY_SUMMONS_5.pdf", "page_number": 1, "text": "Third-party complaint. Alpha against Able."},
                {"filename": "SECOND_THIRD_PARTY_SUMMONS_13.pdf", "page_number": 1, "text": "Second third-party complaint. Bravo against Baker."},
                {"filename": "ANSWER_TO_THIRD_PARTY_COMPLAINT_2.pdf", "page_number": 1, "text": "Answer to third-party complaint."},
            ]

        with self.assertRaisesRegex(WORKER.PreGenerationGateError, "(?:unmatched|ambiguous)_third_party_answer"):
            WORKER.evidence(
                AmbiguousAnswerS3(),
                "NY-NewYork-158068-2018-Szymczyk-v-Hudson-36-37",
                "Validate the third-party-claims layer separately from the main action and all counterclaims/cross-claims.",
            )

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

    def test_all_complaint_cause_and_prayer_pages_precede_dense_exhibits(self):
        class CompleteClaimsS3(FakeS3):
            pages = [
                {"filename": "Complaint.pdf", "page_number": 1, "text": "Plaintiff against Defendant."},
                *[
                    {"filename": "Complaint.pdf", "page_number": page, "text": f"{ordinal} CAUSE OF ACTION: pleaded claim {page}."}
                    for page, ordinal in ((3, "FIRST"), (4, "SECOND"), (5, "THIRD"), (6, "FOURTH"))
                ],
                {"filename": "Complaint.pdf", "page_number": 7, "text": "WHEREFORE plaintiff requests damages and costs."},
            ] + [
                {"filename": f"Exhibit {index}.pdf", "page_number": 1, "text": "parties claims defenses relief"}
                for index in range(40)
            ]

        pages = WORKER.evidence(
            CompleteClaimsS3(),
            "NY-Suffolk-600371-2021-DeSousa-v-Calvagno-II-Karcher",
            "What are the parties, claims, defenses, and requested relief in the verified record?",
        )
        selected = {page["page_number"] for page in pages if page["filename"] == "Complaint.pdf"}
        self.assertEqual(selected, {1, 3, 4, 5, 6, 7})

    def test_substantive_claim_headings_and_judgment_language_are_operatives(self):
        class SubstantiveHeadingsS3(FakeS3):
            pages = [
                {"filename": "SUMMONS___COMPLAINT_1.pdf", "page_number": 1,
                 "text": "Plaintiff against Hudson 36 LLC and Hudson 37 LLC."},
                {"filename": "SUMMONS___COMPLAINT_1.pdf", "page_number": 8,
                 "text": "LABOR LAW SECTION 240(1). Defendants failed to provide protection."},
                {"filename": "SUMMONS___COMPLAINT_1.pdf", "page_number": 9,
                 "text": "LABOR LAW § 241(6). Defendants violated applicable rules."},
                {"filename": "SUMMONS___COMPLAINT_1.pdf", "page_number": 10,
                 "text": "NEGLIGENCE AND LABOR LAW § 200. Defendants had notice."},
                {"filename": "SUMMONS___COMPLAINT_1.pdf", "page_number": 11,
                 "text": "Plaintiff demands judgment for damages, costs and disbursements."},
            ] + [
                {"filename": f"Exhibit {index}.pdf", "page_number": 1,
                 "text": "parties claims defenses relief"}
                for index in range(45)
            ]

        pages = WORKER.evidence(
            SubstantiveHeadingsS3(),
            "NY-NewYork-158068-2018-Szymczyk-v-Hudson-36-37",
            "Identify the pleaded claims and party roles, defenses, and relief.",
        )
        selected = {
            page["page_number"] for page in pages
            if page["filename"] == "SUMMONS___COMPLAINT_1.pdf"
        }
        self.assertEqual(selected, {1, 8, 9, 10, 11})
        operatives = pages.coverage["pleading_operatives"]
        self.assertEqual(operatives["claim_page_count"], 3)
        self.assertEqual(operatives["relief_page_count"], 1)
        self.assertEqual(
            {item["page_number"] for item in operatives["claim_citations"]},
            {8, 9, 10},
        )
        self.assertEqual(
            [item["page_number"] for item in operatives["relief_citations"]],
            [11],
        )


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

    def test_first_defense_precedes_claim_and_relief_within_answer_page_limit(self):
        class AnswerPagePriorityS3(FakeS3):
            pages = [
                {
                    "filename": "ANSWER_2.pdf",
                    "page_number": 1,
                    "text": "Defendant answers the verified complaint.",
                },
                {
                    "filename": "ANSWER_2.pdf",
                    "page_number": 2,
                    "text": "FIRST CAUSE OF ACTION.",
                },
                {
                    "filename": "ANSWER_2.pdf",
                    "page_number": 3,
                    "text": "WHEREFORE defendant requests dismissal.",
                },
                {
                    "filename": "ANSWER_2.pdf",
                    "page_number": 4,
                    "text": "AS FOR A FIRST AFFIRMATIVE DEFENSE.",
                },
            ]

        pages = WORKER.evidence(
            AnswerPagePriorityS3(),
            "NY-Suffolk-600371-2021-DeSousa-v-Calvagno-II-Karcher",
            "Identify the plaintiffs' claims against defendants, relief, and defenses.",
        )
        selected = {
            (page["filename"], page["page_number"])
            for page in pages
        }
        self.assertIn(("ANSWER_2.pdf", 4), selected)

    def test_procedural_posture_question_reserves_death_substitution_order(self):
        filler = "claims defenses relief summary judgment"

        class ProceduralOrderS3(FakeS3):
            pages = [
                {
                    "filename": "COMPLAINT_1.pdf",
                    "page_number": 1,
                    "text": "Plaintiffs against defendants for private nuisance.",
                },
                {
                    "filename": "ORDER_151.pdf",
                    "page_number": 3,
                    "text": (
                        "Motion denied due to death of Thomas DeSousa; "
                        "substitution pending and jurisdiction stayed."
                    ),
                },
            ] + [
                {
                    "filename": f"CORRESPONDENCE_{index}.pdf",
                    "page_number": 1,
                    "text": filler,
                }
                for index in range(WORKER.MAX_PAGES + 5)
            ]

        pages = WORKER.evidence(
            ProceduralOrderS3(),
            "NY-Suffolk-600371-2021-DeSousa-v-Calvagno-II-Karcher",
            (
                "Identify the plaintiffs' claims against defendants and the "
                "effect of death, substitution, and jurisdiction on summary judgment."
            ),
        )
        self.assertIn(
            ("ORDER_151.pdf", 3),
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


class StrategicAnalysisRetrievalTests(unittest.TestCase):
    QUESTION = "What elements or issues are weakest for Defendants?"

    def test_generic_weakness_question_selects_full_case_theory_categories(self):
        class StrategicS3(FakeS3):
            pages = [
                {
                    "filename": "Complaint.pdf",
                    "page_number": 1,
                    "text": "Plaintiff alleges interference and seeks equitable relief.",
                },
                {
                    "filename": "Plaintiff Expert Affidavit.pdf",
                    "page_number": 7,
                    "text": "Licensed professional engineer expert opinion based on the site plan.",
                },
                {
                    "filename": "Survey.pdf",
                    "page_number": 3,
                    "text": "The waterfront boundary measures 120 feet and the setback is 50 feet.",
                },
                {
                    "filename": "Plaintiff Memorandum.pdf",
                    "page_number": 12,
                    "text": "Plaintiff argues that the DEC regulation and riparian navigation rule require equitable access.",
                },
                {
                    "filename": "Defendant Brief.pdf",
                    "page_number": 9,
                    "text": "Defendant contends that its permit supersedes plaintiff's claimed access right.",
                },
            ]

        pages = WORKER.evidence(
            StrategicS3(),
            "NY-Suffolk-600371-2021-DeSousa-v-Calvagno-II-Karcher",
            self.QUESTION,
        )
        selected = {(page["filename"], page["page_number"]) for page in pages}
        for expected in (
            ("Plaintiff Expert Affidavit.pdf", 7),
            ("Survey.pdf", 3),
            ("Plaintiff Memorandum.pdf", 12),
            ("Defendant Brief.pdf", 9),
        ):
            self.assertIn(expected, selected)

    def test_expert_document_pages_are_expanded_and_balanced(self):
        class ExpertDocumentsS3(FakeS3):
            pages = [
                {
                    "filename": "Plaintiff Affidavit.pdf",
                    "page_number": page,
                    "text": (
                        "Retained professional engineer gives an expert opinion."
                        if page == 1
                        else f"Plaintiff calculation detail page {page}."
                    ),
                }
                for page in range(1, 11)
            ] + [
                {
                    "filename": "Defendant Affidavit.pdf",
                    "page_number": page,
                    "text": (
                        "Licensed surveyor gives an expert opinion."
                        if page == 1
                        else f"Defendant calculation detail page {page}."
                    ),
                }
                for page in range(1, 11)
            ]

        pages = WORKER.evidence(
            ExpertDocumentsS3(),
            "NY-Suffolk-600371-2021-DeSousa-v-Calvagno-II-Karcher",
            self.QUESTION,
        )
        by_document = {}
        for page in pages:
            by_document.setdefault(page["filename"], set()).add(page["page_number"])
        self.assertGreaterEqual(len(by_document["Plaintiff Affidavit.pdf"]), 6)
        self.assertGreaterEqual(len(by_document["Defendant Affidavit.pdf"]), 6)
        self.assertIn(6, by_document["Plaintiff Affidavit.pdf"])
        self.assertIn(6, by_document["Defendant Affidavit.pdf"])

    def test_strategic_prompt_requires_direct_balanced_assessment(self):
        page = {
            "source_sha256": "a" * 64,
            "filename": "Expert Affidavit.pdf",
            "page_number": 7,
            "text": "The expert gives an opinion about the disputed condition.",
        }
        result = {
            "summary": "The verified record identifies a material weakness.",
            "findings": [{
                "section": "Assessment",
                "statement": "The expert opinion supports plaintiff, while defendants retain a factual counterargument.",
                "citations": [{key: page[key] for key in ("source_sha256", "filename", "page_number")}],
                "authority_citations": [],
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
            WORKER.generate(self.QUESTION, [page])

        payload = json.loads(urlopen.call_args.args[0].data.decode())
        prompt = json.loads(payload["input"])
        schema = payload["text"]["format"]["schema"]
        self.assertIn("Give a direct attorney answer, not a source list", prompt["instructions"])
        self.assertIn("extract the concrete opinions", prompt["instructions"])
        self.assertIn("Compare the parties' best arguments point by point", prompt["instructions"])
        self.assertIn("give the strongest counterargument", prompt["instructions"])
        self.assertEqual(
            schema["properties"]["findings"]["items"]["properties"]["section"]["enum"],
            list(WORKER.STRATEGIC_ANALYSIS_SECTIONS),
        )

    def test_strategic_validation_requires_ordered_assessment(self):
        page = {
            "source_sha256": "a" * 64,
            "filename": "Expert Affidavit.pdf",
            "page_number": 7,
            "text": "Expert opinion.",
        }
        cite = {key: page[key] for key in ("source_sha256", "filename", "page_number")}

        def result(sections):
            return {
                "summary": "The record supports a qualified assessment.",
                "findings": [{
                    "section": section,
                    "statement": "The cited evidence supports this part of the assessment.",
                    "citations": [cite],
                    "authority_citations": [],
                } for section in sections],
                "missing_information": [],
                "limitations": [],
            }

        valid = result(list(WORKER.STRATEGIC_ANALYSIS_SECTIONS))
        self.assertIs(
            WORKER.validate(valid, [page], question=self.QUESTION), valid
        )
        repeated = result([
            "Case framework",
            "Evidence",
            "Evidence",
            "Competing positions",
            "Assessment",
            "Assessment",
        ])
        self.assertIs(
            WORKER.validate(repeated, [page], question=self.QUESTION), repeated
        )
        with self.assertRaisesRegex(ValueError, "invalid strategic-analysis sections"):
            WORKER.validate(
                result(["Assessment", "Evidence"]),
                [page],
                question=self.QUESTION,
            )
        with self.assertRaisesRegex(ValueError, "invalid strategic-analysis sections"):
            WORKER.validate(
                result(["Case framework", "Evidence", "Assessment"]),
                [page],
                question=self.QUESTION,
            )

    def test_strategic_prompt_integrates_existing_reasoning_engines_and_source_types(self):
        page = {
            "source_sha256": "a" * 64,
            "filename": "Defendant Expert Report.pdf",
            "page_number": 4,
            "text": "Professional engineer offers an expert opinion based on design experience and cites a DEC permit.",
        }
        result = {
            "summary": "The expert opinion is evidence rather than governing law.",
            "findings": [{
                "section": section,
                "statement": "The cited record supports this qualified part of the assessment.",
                "citations": [{key: page[key] for key in ("source_sha256", "filename", "page_number")}],
                "authority_citations": [],
            } for section in WORKER.STRATEGIC_ANALYSIS_SECTIONS],
            "missing_information": [],
            "limitations": [],
        }
        response = mock.MagicMock()
        response.read.return_value = json.dumps({
            "output": [{"content": [{"text": json.dumps(result)}]}]
        }).encode()
        response.__enter__.return_value = response
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), mock.patch.object(WORKER.urllib.request, "urlopen", return_value=response) as urlopen:
            WORKER.generate(self.QUESTION, [page])

        prompt = json.loads(json.loads(urlopen.call_args.args[0].data.decode())["input"])
        context = prompt["litigation_reasoning_context"]
        self.assertEqual(context["question_mode"], "strategic_analysis")
        self.assertEqual(context["page_classifications"][0]["source_type"], "expert_opinion")
        self.assertEqual(context["page_classifications"][0]["legal_status"], "record_evidence_not_law")
        self.assertEqual(context["page_classifications"][0]["expert_qualification_scope"], "design_or_technical")
        self.assertIn("issue_engine", context)
        self.assertIn("contradiction_engine", context)

    def test_john_framework_acceptance_requires_experts_dec_drawings_and_cited_authority(self):
        """Regression for the four gaps identified in the attorney's framework review."""
        question = (
            "Assess the defendants' riparian-access position. Weigh the expert "
            "opinions, DEC record, drawings showing available maneuvering room, "
            "and authorities cited by the parties; identify the strongest answer "
            "to each side rather than merely summarizing the filings."
        )
        framework_pages = [
            {
                "source_sha256": "a" * 64,
                "filename": "Austin Preliminary Expert Report.pdf",
                "page_number": 4,
                "text": (
                    "Professional engineer Austin gives a preliminary opinion that a "
                    "one-quarter allocation supports a twenty-foot corridor. Austin "
                    "acknowledges the rule is not adopted law and describes design "
                    "engineering experience, not regulatory expertise."
                ),
            },
            {
                "source_sha256": "a" * 64,
                "filename": "NYS DEC Permit and Inspection File.pdf",
                "page_number": 12,
                "text": (
                    "Department of Environmental Conservation permit, approved plan, "
                    "inspection, and certificate records address the dock work."
                ),
            },
            {
                "source_sha256": "a" * 64,
                "filename": "Survey and Dock Layout Drawing.pdf",
                "page_number": 2,
                "text": (
                    "Survey drawing and site plan show vessel locations, a forty-foot "
                    "turning area, measurements, and available maneuvering space."
                ),
            },
            {
                "source_sha256": "a" * 64,
                "filename": "Plaintiffs Memorandum of Law.pdf",
                "page_number": 8,
                "text": (
                    "Plaintiffs argue that 123 N.Y.3d 456 and a riparian navigation "
                    "rule support equitable access; the cited authority is their position."
                ),
            },
        ]

        framework_s3 = FakeS3()
        framework_s3.pages = framework_pages

        selected = WORKER.evidence(
            framework_s3,
            "NY-Suffolk-600371-2021-DeSousa-v-Calvagno-II-Karcher",
            question,
        )
        self.assertEqual(
            {page["filename"] for page in selected},
            {page["filename"] for page in framework_pages},
        )

        result = {
            "summary": "The record requires a comparative assessment of the expert, agency, drawing, and cited-authority evidence.",
            "findings": [{
                "section": section,
                "statement": "The cited record supports this part of the comparative assessment.",
                "citations": [{key: framework_pages[0][key] for key in ("source_sha256", "filename", "page_number")}],
                "authority_citations": [],
            } for section in WORKER.STRATEGIC_ANALYSIS_SECTIONS],
            "missing_information": [],
            "limitations": [],
        }
        response = mock.MagicMock()
        response.read.return_value = json.dumps({
            "output": [{"content": [{"text": json.dumps(result)}]}]
        }).encode()
        response.__enter__.return_value = response
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), mock.patch.object(
            WORKER.urllib.request, "urlopen", return_value=response
        ) as urlopen:
            WORKER.generate(question, selected)

        prompt = json.loads(json.loads(urlopen.call_args.args[0].data.decode())["input"])
        classifications = {
            item["filename"]: item
            for item in prompt["litigation_reasoning_context"]["page_classifications"]
        }
        self.assertEqual(
            classifications["Austin Preliminary Expert Report.pdf"]["source_type"],
            "expert_opinion",
        )
        self.assertEqual(
            classifications["Austin Preliminary Expert Report.pdf"]["legal_status"],
            "record_evidence_not_law",
        )
        self.assertEqual(
            classifications["Austin Preliminary Expert Report.pdf"]["expert_qualification_scope"],
            "design_or_technical",
        )
        self.assertEqual(
            classifications["NYS DEC Permit and Inspection File.pdf"]["source_type"],
            "regulatory_record",
        )
        self.assertEqual(
            classifications["Survey and Dock Layout Drawing.pdf"]["source_type"],
            "visual_or_measurement_evidence",
        )
        self.assertEqual(
            classifications["Plaintiffs Memorandum of Law.pdf"]["legal_status"],
            "party_position_not_verified_law",
        )
        self.assertIn("Analyze supplied DEC", prompt["instructions"])
        self.assertIn("drawings, surveys, plans, photographs, and measurements", prompt["instructions"])
        self.assertIn("cases and rules cited in party filings as attributed positions", prompt["instructions"])

    def test_motion_recommendation_has_dedicated_contract(self):
        question = "I need to make a motion. Which motions should I consider?"
        page = {
            "source_sha256": "a" * 64,
            "filename": "Decision and Order.pdf",
            "page_number": 2,
            "text": "The court ordered that discovery continue before dispositive motion practice.",
        }
        result = {
            "summary": "The present record supports a qualified motion recommendation.",
            "findings": [{
                "section": section,
                "statement": "The cited order controls this part of the recommendation.",
                "citations": [{key: page[key] for key in ("source_sha256", "filename", "page_number")}],
                "authority_citations": [],
            } for section in WORKER.MOTION_RECOMMENDATION_SECTIONS],
            "missing_information": [],
            "limitations": [],
        }
        response = mock.MagicMock()
        response.read.return_value = json.dumps({
            "output": [{"content": [{"text": json.dumps(result)}]}]
        }).encode()
        response.__enter__.return_value = response
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), mock.patch.object(WORKER.urllib.request, "urlopen", return_value=response) as urlopen:
            generated = WORKER.generate(question, [page])
        payload = json.loads(urlopen.call_args.args[0].data.decode())
        prompt = json.loads(payload["input"])
        sections = payload["text"]["format"]["schema"]["properties"]["findings"]["items"]["properties"]["section"]["enum"]
        self.assertEqual(prompt["litigation_reasoning_context"]["question_mode"], "motion_recommendation")
        self.assertIn("which motions to consider", prompt["instructions"])
        self.assertEqual(sections, list(WORKER.MOTION_RECOMMENDATION_SECTIONS))
        self.assertIs(WORKER.validate(generated, [page], question=question), generated)

    def test_motion_response_has_dedicated_contract(self):
        question = "My opponent filed this motion. How should I answer it?"
        page = {
            "source_sha256": "b" * 64,
            "filename": "Notice of Motion.pdf",
            "page_number": 1,
            "text": "Defendant moves for the relief stated in the accompanying papers.",
        }
        result = {
            "summary": "The response should address the verified motion and preserve record-supported procedural objections.",
            "findings": [{
                "section": section,
                "statement": "The cited motion supports this part of the response analysis.",
                "citations": [{key: page[key] for key in ("source_sha256", "filename", "page_number")}],
                "authority_citations": [],
            } for section in WORKER.MOTION_RESPONSE_SECTIONS],
            "missing_information": [],
            "limitations": [],
        }
        response = mock.MagicMock()
        response.read.return_value = json.dumps({
            "output": [{"content": [{"text": json.dumps(result)}]}]
        }).encode()
        response.__enter__.return_value = response
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), mock.patch.object(WORKER.urllib.request, "urlopen", return_value=response) as urlopen:
            generated = WORKER.generate(question, [page])

        payload = json.loads(urlopen.call_args.args[0].data.decode())
        prompt = json.loads(payload["input"])
        sections = payload["text"]["format"]["schema"]["properties"]["findings"]["items"]["properties"]["section"]["enum"]
        self.assertEqual(WORKER.question_mode(question), "motion_response")
        self.assertEqual(prompt["litigation_reasoning_context"]["question_mode"], "motion_response")
        self.assertIn("how to answer an opponent's motion", prompt["instructions"])
        self.assertEqual(sections, list(WORKER.MOTION_RESPONSE_SECTIONS))
        self.assertIs(WORKER.validate(generated, [page], question=question), generated)


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
        self.assertIn("do not prepend or return a claims-map summary", instructions)
        self.assertIn("procedural disposition, not a merits decision", instructions)

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
