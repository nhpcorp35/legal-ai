import base64
import os
import unittest
from unittest.mock import patch

import app as legalai


CASE_ID = "NY-Nassau-613561-2026-Desousa-v-Rennick"
SOURCE_SHA256 = "a" * 64


def _auth_headers():
    token = base64.b64encode(b"allen@example.com:secret").decode("ascii")
    return {"Authorization": f"Basic {token}"}


class WorkspaceSourceCitationTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(
            os.environ, {"LEGALAI_REVIEW_USERS_JSON": '{"allen@example.com":"secret"}'}, clear=False
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_verified_source_map_preserves_source_identity(self):
        with patch.object(legalai, "load_registered_cases", return_value=[{"case_id": CASE_ID, "stage": "Verified source indexed"}]), patch.object(
            legalai, "load_case_source_map", return_value=[{"source_sha256": SOURCE_SHA256, "filename": "Record.pdf", "pages": 2}]
        ):
            response = legalai.app.test_client().get(
                f"/workspace/matters/{CASE_ID}/sources", headers=_auth_headers()
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn(f"source_sha256={SOURCE_SHA256}", response.get_data(as_text=True))

    def test_case00_source_map_does_not_require_registered_case_entry(self):
        documents = [{"source_sha256": SOURCE_SHA256, "filename": "Complaint.pdf", "pages": 10}]
        with patch.object(legalai, "load_registered_cases", return_value=[]), patch.object(
            legalai, "load_case_source_map", return_value=documents
        ):
            response = legalai.app.test_client().get(
                f"/workspace/matters/{legalai.CASE00_ID}/sources",
                headers=_auth_headers(),
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Complaint.pdf", response.get_data(as_text=True))

    def test_rennick_framework_check_is_authenticated_and_model_free(self):
        result = {
            "categories": {"expert_opinion": [{"filename": "Austin.pdf", "page_number": 7, "snippet": "1/4 rule opinion"}]},
            "authority_verification": {
                "model_called": False,
                "analysis_guardrail": "A party citation is not governing law.",
                "candidates": [{
                    "citation": "N.Y. Navigation Law \u00a7 15",
                    "status": "party_cited_unverified",
                    "verification_requirement": "Verify from an official source.",
                    "record_citations": [{"filename": "Plaintiff Memorandum.pdf", "page_number": 4}],
                }],
            },
            "conflicts": [{
                "name": "opinion_vs_authority",
                "status": "candidate_tension",
                "guardrail": "Expert methodology is evidence, not law.",
                "left": {"record_role": "expert_opinion", "results": []},
                "right": {"record_role": "legal_authority", "results": []},
            }],
        }
        client = legalai.app.test_client()
        unauthorized = client.post(f"/workspace/matters/{CASE_ID}/framework-evidence")
        with patch.object(legalai, "run_framework_evidence_check", return_value=result):
            response = client.post(
                f"/workspace/matters/{CASE_ID}/framework-evidence", headers=_auth_headers()
            )
        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Completed with no model call.", page)
        self.assertIn("Framework conflict map", page)
        self.assertIn("Authority verification status", page)
        self.assertIn("party cited unverified", page)
        self.assertIn("Expert methodology is evidence, not law.", page)
        self.assertIn("1/4 rule opinion", page)

    def test_rennick_framework_check_shows_identity_match_without_calling_it_law(self):
        result = {
            "categories": {}, "conflicts": [],
            "authority_verification": {"model_called": False, "candidates": [{
                "citation": "193 A.D.3d 710",
                "status": "official_primary_source_identified",
                "verification_requirement": "The party's specific proposition remains unverified.",
                "primary_source": {
                    "title": "Kuzmicki v Bentley Yacht Club",
                    "issuing_body": "Appellate Division, Second Department",
                    "source_url": "https://www.nycourts.gov/reporter/files/bv/193AD3d.pdf",
                    "reporter_page": 710,
                },
                "record_citations": [{"filename": "Affirmation.pdf", "page_number": 7}],
            }]},
        }
        with patch.object(legalai, "run_framework_evidence_check", return_value=result):
            response = legalai.app.test_client().post(
                f"/workspace/matters/{CASE_ID}/framework-evidence", headers=_auth_headers()
            )
        page = response.get_data(as_text=True)
        self.assertIn("official primary source identified", page)
        self.assertIn("Kuzmicki v Bentley Yacht Club", page)
        self.assertIn("The party&#39;s specific proposition remains unverified.", page)

    def test_rennick_framework_check_caps_large_authority_audit_for_readability(self):
        candidates = [{
            "citation": f"N.Y. Navigation Law § {number}",
            "status": "party_cited_unverified",
            "verification_requirement": "Verify from an official source.",
            "record_citations": [{"filename": "Memorandum.pdf", "page_number": number}],
        } for number in range(1, 12)]
        result = {
            "categories": {}, "conflicts": [],
            "authority_verification": {"model_called": False, "candidates": candidates},
        }
        with patch.object(legalai, "run_framework_evidence_check", return_value=result):
            response = legalai.app.test_client().post(
                f"/workspace/matters/{CASE_ID}/framework-evidence", headers=_auth_headers()
            )
        page = response.get_data(as_text=True)
        self.assertIn("Showing the first 10 of 11", page)
        self.assertIn("N.Y. Navigation Law § 10", page)
        self.assertNotIn("N.Y. Navigation Law § 11", page)

    def test_verified_pdf_requires_and_forwards_the_cited_source(self):
        seen = {}

        def fake_open(case_id, source_sha256, filename):
            seen.update(case_id=case_id, source_sha256=source_sha256, filename=filename)
            return b"%PDF-1.4\n"

        with patch.object(legalai, "load_registered_cases", return_value=[{"case_id": CASE_ID, "stage": "Verified source indexed"}]), patch.object(
            legalai, "open_indexed_case_pdf", side_effect=fake_open
        ):
            client = legalai.app.test_client()
            response = client.get(
                f"/workspace/matters/{CASE_ID}/pdf/Record.pdf?source_sha256={SOURCE_SHA256}",
                headers=_auth_headers(),
            )
            missing = client.get(
                f"/workspace/matters/{CASE_ID}/pdf/Record.pdf", headers=_auth_headers()
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(seen, {"case_id": CASE_ID, "source_sha256": SOURCE_SHA256, "filename": "Record.pdf"})
        self.assertEqual(missing.status_code, 404)
