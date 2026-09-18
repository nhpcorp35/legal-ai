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
        for sections in (["Third-party claims", "Main case"], ["Main case", "Main case"]):
            with self.assertRaisesRegex(ValueError, "invalid litigation-map sections"):
                WORKER.validate(result(sections), [page], question=question)
        with self.assertRaisesRegex(ValueError, "incomplete output"):
            WORKER.validate(result(["Main case"], statement="Party: negligence and"), [page], question=question)
        with self.assertRaisesRegex(ValueError, "unverified missing-page claim"):
            WORKER.validate(result(["Main case"], missing=["Complaint pages 2–18 were not supplied."]), [page], question=question)

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
            with self.assertRaisesRegex(RuntimeError, "private"):
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
