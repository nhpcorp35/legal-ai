"""Synthetic regressions for party-role evidence-completeness corrections."""

from __future__ import annotations

import copy
import json
import re
import unittest

import matter_builder as mb
from engines import drafting_engine as de


def _page(page_number, text, nyscef_document_number, extraction_method="native"):
    return mb.build_page_record(
        page_number,
        text,
        extraction_method,
        nyscef_document_number,
    )


def _doc(nyscef, doc_type, texts, filename=None, **extra):
    pages = [
        _page(i, text, nyscef_document_number=nyscef)
        for i, text in enumerate(texts, start=1)
    ]
    document = {
        "filename": filename or f"nyscef_doc_no_{nyscef}_{doc_type}.pdf",
        "nyscef_document_number": nyscef,
        "type": doc_type,
        "pages": pages,
        "page_count": len(pages),
        "title": extra.pop("title", f"Doc {nyscef}"),
    }
    document.update(extra)
    return document


def _normalized(doc):
    return mb.normalize_document(doc, include_exhibit_segments=True)


def _long_caption_complaint():
    """Caption lists many parties; role labels appear only after a long name list."""
    plaintiffs = ", ".join(f"Summit Parcel Group {i} LLC" for i in range(1, 18))
    defendants = ", ".join(f"Coastal Hauler Carrier {i} Inc" for i in range(1, 18))
    caption = (
        "SUPREME COURT OF THE STATE OF NEW YORK\n"
        "COUNTY OF EXAMPLE\n"
        f"{plaintiffs},\n"
        "                                   Plaintiffs,\n"
        "                 -against-\n"
        f"{defendants},\n"
        "                                   Defendants.\n"
        "Index No. 555111/2024\n"
    )
    body = (
        "COMPLAINT\n"
        "Plaintiffs, by their attorneys, allege as follows.\n"
    )
    return _normalized(
        _doc(
            501,
            "complaint",
            [caption + body],
            filename="nyscef_doc_no_501_summons_complaint.pdf",
        )
    )


def _multipage_parties_complaint():
    """Initiating pleading with a multi-page PARTIES section then FACTS."""
    return _normalized(
        _doc(
            502,
            "complaint",
            [
                "SUPREME COURT OF THE STATE OF NEW YORK\n"
                "Riverbend Supply Co. v. Lakeshore Depot LLC\n"
                "Summons. Index No. 777888/2024.\n",
                "PARTIES\n"
                "1. Plaintiff Riverbend Supply Co. is a domestic corporation "
                "authorized to do business in this state.\n"
                "2. Defendant Lakeshore Depot LLC is a limited liability company.\n",
                "3. Meadow Bridge Repair Inc., third-party defendant, was joined "
                "herein as a necessary party.\n"
                "4. Prairie Notice Carrier LP is a notice defendant under the policy.\n"
                "5. Summit Named Insured Trust is the named insured on the policy.\n",
                "6. Canyon Guaranty Fund, appellant, seeks review of the order.\n"
                "7. Lakeshore Depot LLC, respondent on appeal, opposes.\n",
                "FACTS\n"
                "8. On January 2, 2024, a shipment was damaged in transit.\n"
                "9. The loss was reported to the carrier the next day.\n",
            ],
            filename="nyscef_doc_no_502_summons_complaint.pdf",
        )
    )


def _filler_filings():
    """High-volume procedural fillers that can crowd diversification/top-k."""
    docs = []
    for nyscef in range(601, 612):
        docs.append(
            _normalized(
                _doc(
                    nyscef,
                    "motion",
                    [
                        "Notice of Motion for Summary Judgment returnable June 1, 2024. "
                        "Movant seeks dismissal on procedural calendar grounds. "
                        + ("z" * 80)
                    ],
                    filename=f"nyscef_doc_no_{nyscef}_notice_of_motion.pdf",
                )
            )
        )
        docs.append(
            _normalized(
                _doc(
                    nyscef + 100,
                    "other",
                    [
                        "Request for Judicial Intervention. RJI addendum repeats a "
                        "caption without explaining party roles. "
                        + ("q" * 80)
                    ],
                    filename=f"nyscef_doc_no_{nyscef + 100}_rji.pdf",
                    title="RJI",
                )
            )
        )
    return docs


def _multi_role_paragraph_page():
    return _normalized(
        _doc(
            503,
            "complaint",
            [
                "SUPREME COURT caption page.\n"
                "Ironclad Freight LP v. Harbor Gate Carrier Inc.\n",
                "PARTIES\n"
                "1. Plaintiff Ironclad Freight LP is a limited liability partnership "
                "authorized to do business in this state.\n"
                "2. Defendant Harbor Gate Carrier Inc. is a domestic corporation.\n"
                "3. Mesa Trailer Repair LLC, third-party defendant, was joined herein "
                "as a necessary party.\n"
                "4. Delta Notice Carrier LLC is a notice defendant.\n"
                "5. Atlas Coverage Trust is the named insured on the relevant policy.\n",
            ],
            filename="nyscef_doc_no_503_complaint.pdf",
        )
    )


def _affirmation_with_caption_shell():
    return _normalized(
        _doc(
            504,
            "affirmation",
            [
                "SUPREME COURT OF THE STATE OF NEW YORK\n"
                "Ironclad Freight LP v. Harbor Gate Carrier Inc.\n"
                "                                   Plaintiffs,\n"
                "                 -against-\n"
                "Harbor Gate Carrier Inc.,\n"
                "                                   Defendants.\n"
                "Affirmation of service. Deponent mailed papers on May 1, 2024.\n"
                "Procedural calendar notation without role assignments.\n",
            ],
            filename="nyscef_doc_no_504_affirmation_of_service.pdf",
        )
    )


class PartyRoleEvidenceCompletenessTests(unittest.TestCase):
    def setUp(self):
        self.party_query = (
            "Who are the parties and what are their roles in this action?"
        )
        self.motion_query = (
            "What relief does the notice of motion for summary judgment seek?"
        )

    def test_multipage_parties_section_pages_all_included(self):
        docs = [_multipage_parties_complaint()] + _filler_filings()
        case_map = mb.build_case_map_from_documents(docs)
        result = mb.retrieve_canonical_records(
            docs,
            self.party_query,
            case_map=case_map,
            top_k=6,
        )
        complaint_pages = {
            hit["pdf_page"]
            for hit in result["results"]
            if hit["nyscef_document_number"] == 502
        }
        # PARTIES spans pages 2-4; page 5 begins FACTS and must not be required.
        self.assertTrue({2, 3, 4}.issubset(complaint_pages))
        for page in (2, 3, 4):
            hit = next(
                h
                for h in result["results"]
                if h["nyscef_document_number"] == 502 and h["pdf_page"] == page
            )
            self.assertTrue(hit.get("page_id"))
            self.assertEqual(hit["page_id"], f"nyscef-502-page-{page:04d}")

    def test_expansion_stops_at_next_major_section(self):
        docs = [_multipage_parties_complaint()]
        page_lookup = mb._page_lookup_from_documents(docs)
        section_ids = mb._collect_parties_section_page_ids(page_lookup)
        pages = []
        for page_id in section_ids:
            entry = page_lookup[page_id]
            pages.append(entry["page"]["page_number"])
        self.assertEqual(pages, [2, 3, 4])
        self.assertNotIn(5, pages)

        result = mb.retrieve_canonical_records(
            docs,
            self.party_query,
            top_k=10,
        )
        facts_hits = [
            hit
            for hit in result["results"]
            if hit["nyscef_document_number"] == 502 and hit["pdf_page"] == 5
        ]
        for hit in facts_hits:
            # FACTS may still rank lexically, but must not be injected by
            # contiguous PARTIES-section expansion.
            self.assertNotIn("party_role_section_expanded", hit)
            self.assertFalse(hit.get("party_role_section_expanded"))

    def test_long_caption_remains_material_despite_short_query_window(self):
        doc = _long_caption_complaint()
        page_text = doc["pages"][0]["text"]
        short_window = mb._retrieval_excerpt(
            page_text,
            phrase="parties roles",
            tokens=["parties", "roles"],
            phrases=["who are the parties"],
        )
        self.assertLessEqual(len(short_window), mb.RETRIEVAL_EXCERPT_MAX)
        # Short window can omit trailing role labels on a long caption.
        self.assertFalse(
            re.search(r"(?i)\bplaintiffs?\b", short_window)
            and re.search(r"(?i)\bdefendants?\b", short_window)
        )

        entry = {
            "page": doc["pages"][0],
            "document": doc,
            "nyscef_document_number": 501,
            "filename": doc["filename"],
            "document_type": "complaint",
            "segment": None,
        }
        focused = mb._party_role_evidence_excerpt(
            entry,
            page_text,
            phrase="parties roles",
            tokens=["parties", "roles"],
        )
        self.assertIn("Plaintiffs", focused)
        self.assertIn("Defendants", focused)
        self.assertIn("Summit Parcel Group 17 LLC", focused)
        self.assertIn("Coastal Hauler Carrier 17 Inc", focused)

        hit = {
            "result_id": "caption-1",
            "page_id": doc["pages"][0]["page_id"],
            "nyscef_document_number": 501,
            "pdf_page": 1,
            "source_filename": doc["filename"],
            "document_type": "complaint",
            "excerpt": short_window,
            "page_text": page_text,
            "classifications": [],
            "assertion_kind": "verified_record_fact",
        }
        self.assertTrue(de.hit_is_material_for_party_role_question(hit))
        hit_excerpt_only = dict(hit)
        hit_excerpt_only.pop("page_text")
        # Without full-page text, truncated caption window can fail materiality.
        self.assertFalse(de.hit_is_material_for_party_role_question(hit_excerpt_only))

    def test_late_listed_party_names_preserved_completely(self):
        doc = _long_caption_complaint()
        entry = {
            "page": doc["pages"][0],
            "document": doc,
            "nyscef_document_number": 501,
            "filename": doc["filename"],
            "document_type": "complaint",
            "segment": None,
        }
        excerpt = mb._party_role_evidence_excerpt(entry, doc["pages"][0]["text"])
        self.assertIn("Summit Parcel Group 17 LLC", excerpt)
        self.assertIn("Coastal Hauler Carrier 17 Inc", excerpt)
        # Never truncate mid-token: no partial final token artifact.
        self.assertNotRegex(excerpt, r"Carrier 17$")
        self.assertFalse(excerpt.endswith("Coastal"))
        self.assertFalse(excerpt.endswith("Summit"))

    def test_multiple_role_paragraphs_survive_evidence_construction(self):
        doc = _multi_role_paragraph_page()
        result = mb.retrieve_canonical_records(
            [doc],
            self.party_query,
            top_k=5,
        )
        parties_hit = next(
            hit
            for hit in result["results"]
            if hit["nyscef_document_number"] == 503 and hit["pdf_page"] == 2
        )
        excerpt = parties_hit["excerpt"]
        self.assertIn("Ironclad Freight LP is a limited liability partnership", excerpt)
        self.assertIn("Harbor Gate Carrier Inc. is a domestic corporation", excerpt)
        self.assertIn("joined herein as a necessary party", excerpt)
        self.assertIn("notice defendant", excerpt)
        self.assertIn("named insured", excerpt)

    def test_full_page_materiality_excludes_motion_and_rji(self):
        pleading = {
            "result_id": "p1",
            "page_id": "nyscef-502-p2",
            "nyscef_document_number": 502,
            "pdf_page": 2,
            "source_filename": "nyscef_doc_no_502_summons_complaint.pdf",
            "document_type": "complaint",
            "excerpt": "PARTIES",
            "page_text": (
                "PARTIES\n"
                "1. Plaintiff Riverbend Supply Co. is a domestic corporation.\n"
                "2. Defendant Lakeshore Depot LLC is a limited liability company.\n"
            ),
            "classifications": ["party_identity"],
            "assertion_kind": "verified_record_fact",
        }
        motion = {
            "result_id": "m1",
            "page_id": "nyscef-601-p1",
            "nyscef_document_number": 601,
            "pdf_page": 1,
            "source_filename": "nyscef_doc_no_601_notice_of_motion.pdf",
            "document_type": "motion",
            "excerpt": "Notice of Motion",
            "page_text": (
                "Notice of Motion for Summary Judgment returnable June 1, 2024. "
                "Movant seeks dismissal. Caption lists Riverbend Supply Co. against "
                "Lakeshore Depot LLC without assigning procedural roles."
            ),
            "classifications": ["motion"],
            "assertion_kind": "unknown",
        }
        rji = {
            "result_id": "r1",
            "page_id": "nyscef-701-p1",
            "nyscef_document_number": 701,
            "pdf_page": 1,
            "source_filename": "nyscef_doc_no_701_rji.pdf",
            "document_type": "other",
            "excerpt": "Request for Judicial Intervention",
            "page_text": (
                "Request for Judicial Intervention. RJI addendum repeats the caption "
                "Riverbend Supply Co. v. Lakeshore Depot LLC without explaining roles."
            ),
            "classifications": ["procedural"],
            "assertion_kind": "unknown",
        }
        name_only = {
            "result_id": "n1",
            "page_id": "nyscef-502-p1",
            "nyscef_document_number": 502,
            "pdf_page": 1,
            "source_filename": "nyscef_doc_no_502_summons_complaint.pdf",
            "document_type": "complaint",
            "excerpt": "Riverbend Supply Co.",
            "page_text": "Calendar exhibit list mentioning Riverbend Supply Co. only.",
            "classifications": [],
            "assertion_kind": "unknown",
        }
        self.assertTrue(de.hit_is_material_for_party_role_question(pleading))
        self.assertFalse(de.hit_is_material_for_party_role_question(motion))
        self.assertFalse(de.hit_is_material_for_party_role_question(rji))
        self.assertFalse(de.hit_is_material_for_party_role_question(name_only))

        packet = de.build_evidence_packet(
            self.party_query,
            {"query": self.party_query, "results": [pleading, motion, rji, name_only]},
        )
        page_ids = {hit["page_id"] for hit in packet["retrieval_hits"]}
        self.assertEqual(page_ids, {"nyscef-502-p2"})
        # Compact packet must not forward full page text into generation.
        for hit in packet["retrieval_hits"]:
            self.assertNotIn("page_text", hit)
            self.assertNotIn("full_page_text", hit)

    def test_affirmation_caption_does_not_trigger_complete_caption(self):
        affirmation = _affirmation_with_caption_shell()
        complaint = _multi_role_paragraph_page()
        entry = {
            "page": affirmation["pages"][0],
            "document": affirmation,
            "nyscef_document_number": 504,
            "filename": affirmation["filename"],
            "document_type": "affirmation",
            "segment": None,
        }
        self.assertTrue(
            mb._is_affirmation_or_service_filing(entry, affirmation["pages"][0]["text"])
        )
        self.assertFalse(
            mb._looks_like_caption_bearing_page(
                affirmation["pages"][0]["text"],
                page_number=1,
                kind="other",
            )
        )
        excerpt = mb._party_role_evidence_excerpt(
            entry, affirmation["pages"][0]["text"]
        )
        # Service affirmation may mention names, but must not receive complete
        # caption preservation treatment used for initiating pleadings.
        self.assertNotIn("complete_caption", excerpt.lower())
        result = mb.retrieve_canonical_records(
            [complaint, affirmation],
            self.party_query,
            top_k=8,
        )
        aff_hits = [
            hit
            for hit in result["results"]
            if hit["nyscef_document_number"] == 504
        ]
        for hit in aff_hits:
            self.assertNotEqual(
                hit.get("excerpt"),
                mb._extract_complete_pleading_caption(affirmation["pages"][0]["text"]),
            )

        # Materiality still excludes affirmation service noise.
        hit = {
            "result_id": "a1",
            "page_id": affirmation["pages"][0]["page_id"],
            "nyscef_document_number": 504,
            "pdf_page": 1,
            "source_filename": affirmation["filename"],
            "document_type": "affirmation",
            "excerpt": affirmation["pages"][0]["text"][:240],
            "page_text": affirmation["pages"][0]["text"],
            "classifications": ["procedural"],
            "assertion_kind": "unknown",
        }
        self.assertFalse(de.hit_is_material_for_party_role_question(hit))

    def test_expanded_pages_preserve_stable_citations(self):
        docs = [_multipage_parties_complaint()] + _filler_filings()
        result = mb.retrieve_canonical_records(
            docs,
            self.party_query,
            top_k=5,
        )
        by_page = {
            hit["pdf_page"]: hit
            for hit in result["results"]
            if hit["nyscef_document_number"] == 502 and hit["pdf_page"] in {2, 3, 4}
        }
        self.assertEqual(set(by_page), {2, 3, 4})
        for page, hit in by_page.items():
            self.assertEqual(hit["page_id"], f"nyscef-502-page-{page:04d}")
            self.assertEqual(hit["nyscef_document_number"], 502)
            self.assertEqual(hit["pdf_page"], page)
            self.assertTrue(str(hit["result_id"]).startswith("cret-nyscef-502-page-"))
            self.assertIn(f"{page:04d}", hit["result_id"])

    def test_non_party_and_motion_behavior_unchanged(self):
        docs = [_multipage_parties_complaint()] + _filler_filings()[:4]
        motion_result = mb.retrieve_canonical_records(
            docs,
            self.motion_query,
            top_k=5,
            include_diagnostics=True,
        )
        hints = motion_result["diagnostics"]["query_hints"]
        self.assertFalse(hints.get("party_role_intent"))
        self.assertEqual(motion_result["results"][0]["document_type"], "motion")
        for hit in motion_result["results"]:
            self.assertEqual(hit["component_scores"]["party_role_pleading"], 0.0)
            self.assertIsNone(hit.get("page_text"))
            self.assertNotIn("party_role_section_expanded", hit)

        # Diversification still returns at most top_k for non-party queries.
        self.assertLessEqual(len(motion_result["results"]), 5)

        motion_hit = {
            "result_id": "m1",
            "page_id": "nyscef-601-p1",
            "nyscef_document_number": 601,
            "pdf_page": 1,
            "source_filename": "nyscef_doc_no_601_notice_of_motion.pdf",
            "document_type": "motion",
            "excerpt": (
                "Notice of Motion for Summary Judgment returnable June 1, 2024. "
                "Movant seeks dismissal."
            ),
            "classifications": ["motion"],
            "assertion_kind": "unknown",
        }
        packet = de.build_evidence_packet(
            self.motion_query,
            {"query": self.motion_query, "results": [motion_hit]},
        )
        self.assertNotIn("materiality_filter", packet)
        self.assertEqual(packet["retrieval_hit_count"], 1)

    def test_no_provisional_or_gold_in_generation_inputs(self):
        docs = [_multi_role_paragraph_page()]
        retrieval = mb.retrieve_canonical_records(
            docs,
            self.party_query,
            top_k=5,
        )
        retrieval = dict(retrieval)
        retrieval["provisional_answer"] = "PROVISIONAL_SHOULD_NOT_APPEAR"
        retrieval["gold_answer"] = "GOLD_SHOULD_NOT_APPEAR"

        captured = {}

        def _model(system_prompt, user_prompt):
            captured["system"] = system_prompt
            captured["user"] = user_prompt
            packet = de.build_evidence_packet(self.party_query, retrieval)
            hit = packet["retrieval_hits"][0]
            return {
                "proposed_answer": "Parties are identified on the pleading.",
                "propositions": [
                    {
                        "proposition_id": "P1",
                        "text": "Plaintiff is identified on the complaint.",
                        "classification": "verified_record_fact",
                        "nyscef_document_number": hit["nyscef_document_number"],
                        "page_id": hit["page_id"],
                        "pdf_page": hit["pdf_page"],
                        "source_excerpt": (hit.get("excerpt") or "")[:80],
                        "confidence": 0.8,
                        "rationale": "From filtered pleading hit.",
                        "polarity": "supporting",
                    }
                ],
                "supporting_evidence": [],
                "contrary_evidence": [],
                "unresolved_questions": [],
                "documents_pages_reviewed": [],
                "confidence": 0.8,
                "attorney_review": {
                    "requires_attorney_review": True,
                    "review_notes": "Review party roster.",
                    "legal_conclusions_labeled": True,
                    "coverage_conclusion": None,
                },
                "review_scope": {
                    "completeness": "not_established",
                    "qualification": "Filtered packet only.",
                },
            }

        result = de.answer_attorney_record_question(
            self.party_query,
            retrieval,
            model_call=_model,
        )
        self.assertEqual(result["status"], de.STATUS_READY)
        blob = (captured["system"] + "\n" + captured["user"]).lower()
        self.assertNotIn("provisional_should_not_appear", blob)
        self.assertNotIn("gold_should_not_appear", blob)
        self.assertNotIn("provisional_answer", blob)
        self.assertNotIn("gold_answer", blob)
        user_packet = json.loads(captured["user"].split("\n\n", 1)[1])
        self.assertNotIn("provisional_answer", user_packet)
        self.assertNotIn("gold_answer", user_packet)
        for hit in user_packet.get("retrieval_hits") or []:
            self.assertNotIn("page_text", hit)


class PartyRoleExpansionBoundTests(unittest.TestCase):
    def test_section_expansion_respects_explicit_page_bound(self):
        pages = ["PARTIES\n1. Plaintiff Bound Test Co. is a corporation.\n"]
        for i in range(2, 12):
            pages.append(
                f"{i}. Defendant Bound Party {i} Inc. is a domestic corporation "
                "joined for completeness.\n"
            )
        pages.append("FACTS\nThe shipment failed.\n")
        doc = _normalized(
            _doc(
                509,
                "complaint",
                pages,
                filename="nyscef_doc_no_509_complaint.pdf",
            )
        )
        section_ids = mb._collect_parties_section_page_ids(
            mb._page_lookup_from_documents([doc])
        )
        self.assertLessEqual(len(section_ids), mb.PARTY_ROLE_SECTION_EXPAND_MAX_PAGES)
        self.assertEqual(len(section_ids), mb.PARTY_ROLE_SECTION_EXPAND_MAX_PAGES)


if __name__ == "__main__":
    unittest.main()
