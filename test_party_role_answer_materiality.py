"""Synthetic regressions for party-role answer-materiality filtering."""

from __future__ import annotations

import copy
import json
import unittest

from engines import drafting_engine as de


def _hit(
    *,
    result_id: str,
    nyscef: int,
    page: int,
    doc_type: str,
    filename: str,
    excerpt: str,
    classifications=None,
    assertion_kind: str = "verified_record_fact",
    score: float = 10.0,
):
    return {
        "result_id": result_id,
        "page_id": f"nyscef-{nyscef}-p{page}",
        "nyscef_document_number": nyscef,
        "pdf_page": page,
        "source_filename": filename,
        "document_type": doc_type,
        "excerpt": excerpt,
        "classifications": list(classifications or []),
        "assertion_kind": assertion_kind,
        "case_map_linkage": None,
        "exhibit_segment": None,
        "score": score,
    }


def _mixed_party_role_hits():
    pleading = _hit(
        result_id="plead-1",
        nyscef=201,
        page=5,
        doc_type="complaint",
        filename="nyscef_doc_no_201_summons_complaint.pdf",
        excerpt=(
            "PARTIES\n"
            "1. Plaintiff Alpine Freight LP is a limited liability partnership "
            "authorized to do business in this state.\n"
            "2. Defendant Harbor Gate Carrier Inc. is a domestic corporation.\n"
            "3. Mesa Trailer Repair LLC, third-party defendant, was joined herein "
            "as a necessary party."
        ),
        classifications=["party_identity"],
    )
    motion = _hit(
        result_id="motion-1",
        nyscef=202,
        page=1,
        doc_type="motion",
        filename="nyscef_doc_no_202_notice_of_motion.pdf",
        excerpt=(
            "Notice of Motion for Summary Judgment returnable June 1, 2024. "
            "Movant seeks dismissal. Caption lists Alpine Freight LP against "
            "Harbor Gate Carrier Inc. without assigning procedural roles."
        ),
        classifications=["motion"],
    )
    rji = _hit(
        result_id="rji-1",
        nyscef=203,
        page=1,
        doc_type="other",
        filename="nyscef_doc_no_203_rji.pdf",
        excerpt=(
            "Request for Judicial Intervention. RJI addendum repeats the caption "
            "Alpine Freight LP v. Harbor Gate Carrier Inc. and a conference date "
            "without explaining party roles."
        ),
        classifications=["procedural"],
    )
    amended = _hit(
        result_id="amended-1",
        nyscef=204,
        page=1,
        doc_type="complaint",
        filename="nyscef_doc_no_204_amended_complaint.pdf",
        excerpt=(
            "AMENDED COMPLAINT. Plaintiff Alpine Freight LP remains plaintiff. "
            "Harbor Gate Carrier Inc. is incorrectly named and is now known as "
            "Harbor Gate Logistics Inc., substituted as defendant. Party status "
            "as to Mesa Trailer Repair LLC is disputed."
        ),
        classifications=["party_identity"],
    )
    qualification = _hit(
        result_id="order-role-1",
        nyscef=205,
        page=1,
        doc_type="order",
        filename="nyscef_doc_no_205_decision_and_order.pdf",
        excerpt=(
            "Decision and Order. IT IS HEREBY ORDERED that Mesa Trailer Repair LLC "
            "is dismissed as a party, without prejudice to renewal if capacity is "
            "later established. The caption role conflict remains unresolved."
        ),
        classifications=["court_order"],
    )
    unrelated_affirmation = _hit(
        result_id="aff-1",
        nyscef=206,
        page=1,
        doc_type="affirmation",
        filename="nyscef_doc_no_206_affirmation_of_service.pdf",
        excerpt=(
            "Affirmation of service. Deponent mailed papers on May 1, 2024. "
            "Procedural calendar notation without role assignments."
        ),
        classifications=["procedural"],
    )
    unrelated_order = _hit(
        result_id="order-noise-1",
        nyscef=207,
        page=1,
        doc_type="order",
        filename="nyscef_doc_no_207_scheduling_order.pdf",
        excerpt=(
            "Scheduling Order. IT IS HEREBY ORDERED that the conference is adjourned "
            "and the procedural calendar is updated."
        ),
        classifications=["court_order"],
    )
    return [
        pleading,
        motion,
        rji,
        amended,
        qualification,
        unrelated_affirmation,
        unrelated_order,
    ]


class PartyRoleAnswerMaterialityTests(unittest.TestCase):
    def setUp(self):
        self.party_question = (
            "Who are the parties and what are their roles in this action?"
        )
        self.motion_question = (
            "What relief does the notice of motion for summary judgment seek?"
        )
        self.hits = _mixed_party_role_hits()
        self.retrieval = {
            "query": self.party_question,
            "results": copy.deepcopy(self.hits),
            # Poison inputs that must never enter generation.
            "provisional_answer": "PROVISIONAL_SHOULD_NOT_APPEAR",
            "gold_answer": "GOLD_SHOULD_NOT_APPEAR",
        }

    def test_detects_party_role_intent_not_motion(self):
        self.assertTrue(de.detect_party_role_question_intent(self.party_question))
        self.assertFalse(de.detect_party_role_question_intent(self.motion_question))
        self.assertFalse(
            de.detect_party_role_question_intent(
                "What did the court order regarding the conference date?"
            )
        )

    def test_mixed_evidence_excludes_motion_and_rji(self):
        packet = de.build_evidence_packet(self.party_question, self.retrieval)
        page_ids = {hit["page_id"] for hit in packet["retrieval_hits"]}
        self.assertIn("nyscef-201-p5", page_ids)
        self.assertNotIn("nyscef-202-p1", page_ids)
        self.assertNotIn("nyscef-203-p1", page_ids)
        self.assertNotIn("nyscef-206-p1", page_ids)
        self.assertNotIn("nyscef-207-p1", page_ids)
        self.assertEqual(packet["materiality_filter"]["intent"], "party_role")
        self.assertGreater(packet["materiality_filter"]["excluded_hit_count"], 0)

    def test_direct_pleading_evidence_remains(self):
        packet = de.build_evidence_packet(self.party_question, self.retrieval)
        kept = {
            hit["page_id"]: hit["excerpt"] for hit in packet["retrieval_hits"]
        }
        self.assertIn("nyscef-201-p5", kept)
        self.assertIn("Plaintiff Alpine Freight LP is a limited liability partnership", kept["nyscef-201-p5"])
        self.assertIn("joined herein", kept["nyscef-201-p5"])

    def test_amended_conflicting_or_changed_role_remains(self):
        packet = de.build_evidence_packet(self.party_question, self.retrieval)
        page_ids = {hit["page_id"] for hit in packet["retrieval_hits"]}
        self.assertIn("nyscef-204-p1", page_ids)
        amended = next(
            hit for hit in packet["retrieval_hits"] if hit["page_id"] == "nyscef-204-p1"
        )
        self.assertIn("incorrectly named", amended["excerpt"])
        self.assertIn("substituted as defendant", amended["excerpt"])

    def test_uncertainty_and_qualification_evidence_remains(self):
        packet = de.build_evidence_packet(self.party_question, self.retrieval)
        page_ids = {hit["page_id"] for hit in packet["retrieval_hits"]}
        self.assertIn("nyscef-205-p1", page_ids)
        order = next(
            hit for hit in packet["retrieval_hits"] if hit["page_id"] == "nyscef-205-p1"
        )
        self.assertIn("dismissed as a party", order["excerpt"])
        self.assertIn("capacity", order["excerpt"])
        self.assertIn("unresolved", order["excerpt"].lower())

    def test_motion_questions_keep_motion_evidence(self):
        motion_hit = self.hits[1]
        retrieval = {
            "query": self.motion_question,
            "results": copy.deepcopy(
                [motion_hit, self.hits[0], self.hits[2], self.hits[5]]
            ),
        }
        packet = de.build_evidence_packet(self.motion_question, retrieval)
        page_ids = [hit["page_id"] for hit in packet["retrieval_hits"]]
        self.assertEqual(len(page_ids), 4)
        self.assertIn("nyscef-202-p1", page_ids)
        self.assertIn("nyscef-203-p1", page_ids)
        self.assertNotIn("materiality_filter", packet)

    def test_generated_propositions_remain_citation_grounded(self):
        packet = de.build_evidence_packet(self.party_question, self.retrieval)
        allowed_page_ids = {hit["page_id"] for hit in packet["retrieval_hits"]}
        pleading = next(
            hit for hit in packet["retrieval_hits"] if hit["page_id"] == "nyscef-201-p5"
        )
        payload = {
            "proposed_answer": (
                "Alpine Freight LP is plaintiff; Harbor Gate Carrier Inc. is defendant."
            ),
            "propositions": [
                {
                    "proposition_id": "P1",
                    "text": "Alpine Freight LP is identified as plaintiff.",
                    "classification": "verified_record_fact",
                    "nyscef_document_number": pleading["nyscef_document_number"],
                    "page_id": pleading["page_id"],
                    "pdf_page": pleading["pdf_page"],
                    "source_excerpt": (
                        "Plaintiff Alpine Freight LP is a limited liability partnership"
                    ),
                    "confidence": 0.91,
                    "rationale": "Party identity appears on the operative pleading page.",
                    "polarity": "supporting",
                },
                {
                    "proposition_id": "P2",
                    "text": "Hallucinated citation outside the filtered packet.",
                    "classification": "verified_record_fact",
                    "nyscef_document_number": 202,
                    "page_id": "nyscef-202-p1",
                    "pdf_page": 1,
                    "source_excerpt": "Notice of Motion for Summary Judgment",
                    "confidence": 0.4,
                    "rationale": "Should be removed if not in retrieval context used.",
                    "polarity": "supporting",
                },
            ],
            "supporting_evidence": [],
            "contrary_evidence": [],
            "unresolved_questions": [],
            "documents_pages_reviewed": [],
            "confidence": 0.9,
            "attorney_review": {
                "requires_attorney_review": True,
                "review_notes": "Confirm party roster.",
                "legal_conclusions_labeled": True,
                "coverage_conclusion": None,
            },
            "review_scope": {
                "completeness": "not_established",
                "qualification": "Limited to filtered party-role evidence.",
            },
        }

        # Validate against the filtered generation packet hits only.
        filtered_retrieval = {
            "query": self.party_question,
            "results": list(packet["retrieval_hits"]),
        }
        validated = de.validate_attorney_qa_response(
            payload,
            question=self.party_question,
            retrieval=filtered_retrieval,
        )
        kept_ids = {p["proposition_id"] for p in validated["propositions"]}
        self.assertEqual(kept_ids, {"P1"})
        self.assertTrue(
            all(p["page_id"] in allowed_page_ids for p in validated["propositions"])
        )
        removed_ids = {
            item["proposition_id"]
            for item in validated["audit"]["removed_propositions"]
        }
        self.assertIn("P2", removed_ids)

    def test_no_provisional_or_gold_in_generation_inputs(self):
        captured = {}

        def _model(system_prompt, user_prompt):
            captured["system"] = system_prompt
            captured["user"] = user_prompt
            packet = de.build_evidence_packet(self.party_question, self.retrieval)
            pleading = packet["retrieval_hits"][0]
            return {
                "proposed_answer": "Parties are identified on the pleading.",
                "propositions": [
                    {
                        "proposition_id": "P1",
                        "text": "Plaintiff is identified on the complaint.",
                        "classification": "verified_record_fact",
                        "nyscef_document_number": pleading["nyscef_document_number"],
                        "page_id": pleading["page_id"],
                        "pdf_page": pleading["pdf_page"],
                        "source_excerpt": pleading["excerpt"][:80],
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
            self.party_question,
            self.retrieval,
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
        self.assertIn("materially useful", captured["system"].lower())
        self.assertIn("citation-grounded", captured["system"].lower())

    def test_non_party_questions_preserve_unfiltered_packet(self):
        order_hit = self.hits[6]
        retrieval = {
            "query": "What did the scheduling order adjourn?",
            "results": [order_hit, self.hits[1]],
        }
        packet = de.build_evidence_packet(
            "What did the scheduling order adjourn?",
            retrieval,
        )
        self.assertEqual(packet["retrieval_hit_count"], 2)
        self.assertNotIn("materiality_filter", packet)
        self.assertEqual(
            [hit["page_id"] for hit in packet["retrieval_hits"]],
            ["nyscef-207-p1", "nyscef-202-p1"],
        )


if __name__ == "__main__":
    unittest.main()
