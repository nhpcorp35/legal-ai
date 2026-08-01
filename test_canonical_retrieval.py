"""Focused tests for provenance-preserving canonical record retrieval."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

import matter_builder as mb


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


def _corpus():
    complaint = mb.normalize_document(
        _doc(
            10,
            "complaint",
            [
                "Acme Holdings LLC v. Beta Insurance Co. "
                "Plaintiff alleges premium payment was completed. "
                "FIRST CAUSE OF ACTION for breach of contract. "
                "Policy No. POL-998877 governs coverage. "
                "The occurrence was filed on January 15, 2024.",
                "EXHIBIT A",
                "Lease agreement body continuing without label " + ("x" * 80),
            ],
        ),
        include_exhibit_segments=True,
    )
    answer = mb.normalize_document(
        _doc(
            11,
            "answer",
            [
                "Defendant alleges premium payment was never completed. "
                "FIRST AFFIRMATIVE DEFENSE of failure to perform. "
                "Notice of Motion is not in this pleading.",
            ],
        ),
        include_exhibit_segments=True,
    )
    motion = mb.normalize_document(
        _doc(
            12,
            "motion",
            [
                "Notice of Motion for Summary Judgment returnable March 1, 2024. "
                "Movant respectfully seeks dismissal.",
            ],
        ),
        include_exhibit_segments=True,
    )
    order = mb.normalize_document(
        _doc(
            13,
            "order",
            [
                "Decision and Order. IT IS HEREBY ORDERED that the motion is held.",
            ],
        ),
        include_exhibit_segments=True,
    )
    return [complaint, answer, motion, order]


class CanonicalRetrievalCoreTests(unittest.TestCase):
    def setUp(self):
        self.docs = _corpus()
        self.case_map = mb.build_case_map_from_documents(self.docs)

    def test_exact_phrase_and_token_retrieval(self):
        phrase = mb.retrieve_canonical_records(
            self.docs,
            "premium payment was completed",
            case_map=self.case_map,
            top_k=10,
        )
        self.assertTrue(phrase["results"])
        top = phrase["results"][0]
        self.assertEqual(top["nyscef_document_number"], 10)
        self.assertIn("premium payment was completed", top["excerpt"].lower())
        self.assertGreater(top["component_scores"]["exact_phrase"], 0)

        tokens = mb.retrieve_canonical_records(
            self.docs,
            "Beta Insurance coverage",
            case_map=self.case_map,
            top_k=10,
        )
        self.assertTrue(tokens["results"])
        self.assertTrue(
            any(r["nyscef_document_number"] == 10 for r in tokens["results"])
        )

    def test_party_date_policy_motion_order_queries(self):
        party = mb.retrieve_canonical_records(
            self.docs, "Acme Holdings LLC", case_map=self.case_map
        )
        self.assertTrue(any(r["nyscef_document_number"] == 10 for r in party["results"]))

        date = mb.retrieve_canonical_records(
            self.docs, "January 15, 2024", case_map=self.case_map
        )
        self.assertTrue(date["results"])
        self.assertIn("january 15, 2024", date["results"][0]["excerpt"].lower())

        policy = mb.retrieve_canonical_records(
            self.docs, "Policy No. POL-998877", case_map=self.case_map
        )
        self.assertTrue(policy["results"])
        self.assertTrue(
            any("POL-998877" in (r["excerpt"] or "") for r in policy["results"])
        )

        motion = mb.retrieve_canonical_records(
            self.docs, "Notice of Motion for Summary Judgment", case_map=self.case_map
        )
        self.assertTrue(
            any(r["nyscef_document_number"] == 12 for r in motion["results"])
        )
        self.assertTrue(
            any(r["document_type"] == "motion" for r in motion["results"])
        )

        order = mb.retrieve_canonical_records(
            self.docs, "IT IS HEREBY ORDERED", case_map=self.case_map
        )
        self.assertTrue(
            any(r["nyscef_document_number"] == 13 for r in order["results"])
        )

    def test_exhibit_retrieval(self):
        result = mb.retrieve_canonical_records(
            self.docs, "Exhibit A lease agreement", case_map=self.case_map
        )
        exhibit_hits = [
            r
            for r in result["results"]
            if (r.get("exhibit_segment") or {}).get("exhibit_label") == "A"
        ]
        self.assertTrue(exhibit_hits)
        hit = exhibit_hits[0]
        self.assertEqual(hit["nyscef_document_number"], 10)
        self.assertTrue(hit["page_id"].startswith("nyscef-010-page-"))
        self.assertIn("segment_id", hit["exhibit_segment"])

    def test_case_map_linkage_resolves_to_pages(self):
        result = mb.retrieve_canonical_records(
            self.docs, "breach of contract", case_map=self.case_map
        )
        linked = [r for r in result["results"] if r.get("case_map_linkage")]
        self.assertTrue(linked)
        for item in linked:
            self.assertTrue(item.get("page_id"))
            self.assertIsNotNone(item.get("nyscef_document_number"))
            self.assertTrue(item.get("pdf_page"))
            linkage = item["case_map_linkage"]
            self.assertTrue(linkage.get("node_id"))
            # Never a bare case-map assertion without citation fields.
            self.assertTrue(item.get("excerpt") is not None)

    def test_allegation_vs_fact_classification_retained(self):
        result = mb.retrieve_canonical_records(
            self.docs, "premium payment", case_map=self.case_map
        )
        allegation_hits = [
            r
            for r in result["results"]
            if "allegation" in (r.get("classifications") or [])
        ]
        self.assertTrue(allegation_hits)
        for hit in allegation_hits:
            self.assertEqual(hit.get("assertion_kind"), "party_allegation")
            self.assertNotIn("verified_fact", hit.get("classifications") or [])

    def test_conflicting_sources_both_retrievable(self):
        result = mb.retrieve_canonical_records(
            self.docs, "premium payment", case_map=self.case_map, top_k=20
        )
        filings = {r["nyscef_document_number"] for r in result["results"]}
        self.assertIn(10, filings)
        self.assertIn(11, filings)
        excerpts = " ".join(r["excerpt"].lower() for r in result["results"])
        self.assertIn("completed", excerpts)
        self.assertIn("never", excerpts)

    def test_deduplication_and_filing_diversity(self):
        # Large filing repeats the same term across many pages; small filing
        # has a single strong hit. Diversity should surface both filings.
        large_texts = [f"contract clause number {i} boilerplate" for i in range(1, 16)]
        large = mb.normalize_document(
            _doc(50, "memo", large_texts),
            include_exhibit_segments=True,
        )
        small = mb.normalize_document(
            _doc(51, "complaint", ["Unique contract claim from plaintiff filing."]),
            include_exhibit_segments=True,
        )
        payload = mb.retrieve_canonical_records(
            [large, small],
            "contract",
            build_case_map_if_missing=True,
            top_k=5,
            filing_diversity_penalty=0.35,
        )
        filings = [r["nyscef_document_number"] for r in payload["results"]]
        self.assertIn(50, filings)
        self.assertIn(51, filings)
        page_ids = [r["page_id"] for r in payload["results"]]
        self.assertEqual(len(page_ids), len(set(page_ids)))

    def test_filters(self):
        by_filing = mb.retrieve_canonical_records(
            self.docs,
            "premium payment",
            case_map=self.case_map,
            filters={"nyscef_document_number": 11},
        )
        self.assertTrue(by_filing["results"])
        self.assertTrue(
            all(r["nyscef_document_number"] == 11 for r in by_filing["results"])
        )

        by_type = mb.retrieve_canonical_records(
            self.docs,
            "motion summary judgment",
            case_map=self.case_map,
            filters={"document_type": "motion"},
        )
        self.assertTrue(by_type["results"])
        self.assertTrue(all(r["document_type"] == "motion" for r in by_type["results"]))

        by_class = mb.retrieve_canonical_records(
            self.docs,
            "premium payment",
            case_map=self.case_map,
            filters={"classification": "allegation"},
        )
        self.assertTrue(by_class["results"])
        self.assertTrue(
            all(
                "allegation" in (r.get("classifications") or [])
                for r in by_class["results"]
            )
        )

        by_exhibit = mb.retrieve_canonical_records(
            self.docs,
            "lease agreement",
            case_map=self.case_map,
            filters={"exhibit_segment": "A"},
        )
        self.assertTrue(by_exhibit["results"])
        self.assertTrue(
            all(
                (r.get("exhibit_segment") or {}).get("exhibit_label") == "A"
                for r in by_exhibit["results"]
            )
        )

        by_cmap = mb.retrieve_canonical_records(
            self.docs,
            "breach of contract",
            case_map=self.case_map,
            filters={"case_map_category": "claims"},
        )
        self.assertTrue(by_cmap["results"])
        self.assertTrue(
            all(
                (r.get("case_map_linkage") or {}).get("collection") == "claims"
                for r in by_cmap["results"]
            )
        )

    def test_deterministic_ranking(self):
        a = mb.retrieve_canonical_records(
            self.docs, "premium payment", case_map=self.case_map, top_k=10
        )
        b = mb.retrieve_canonical_records(
            self.docs, "premium payment", case_map=self.case_map, top_k=10
        )
        self.assertTrue(mb.ranking_is_deterministic(a["results"], b["results"]))

        bench = mb.retrieve_canonical_records_benchmark(
            self.docs, "premium payment", case_map=self.case_map, top_k=10
        )
        self.assertTrue(bench["metrics"]["deterministic_ranking"])
        self.assertIn("citation_validity", bench["metrics"])
        self.assertIn("unique_filing_coverage", bench["metrics"])
        self.assertIn("duplicate_hit_rate", bench["metrics"])
        self.assertIn("unsupported_result_rate", bench["metrics"])
        self.assertIn("top_k_evidence", bench["metrics"])
        self.assertIn("gold labels", bench["metrics"]["notes"])

    def test_invalid_citation_rejection(self):
        page_lookup = mb._page_lookup_from_documents(self.docs)
        good = mb.retrieve_canonical_records(
            self.docs, "premium payment", case_map=self.case_map, top_k=1
        )["results"][0]
        self.assertTrue(mb.validate_canonical_result_citation(good, page_lookup))

        bad = copy.deepcopy(good)
        bad["page_id"] = "nyscef-999-page-0001"
        self.assertFalse(mb.validate_canonical_result_citation(bad, page_lookup))

        mismatched = copy.deepcopy(good)
        mismatched["nyscef_document_number"] = 999
        self.assertFalse(
            mb.validate_canonical_result_citation(mismatched, page_lookup)
        )

    def test_no_unsupported_results(self):
        payload = mb.retrieve_canonical_records_benchmark(
            self.docs, "policy POL-998877", case_map=self.case_map, top_k=20
        )
        self.assertEqual(payload["metrics"]["unsupported_result_rate"], 0.0)
        self.assertEqual(payload["metrics"]["citation_validity"], 1.0)
        for result in payload["results"]:
            self.assertTrue(result.get("result_id"))
            self.assertTrue(result.get("page_id"))
            self.assertIsNotNone(result.get("nyscef_document_number"))
            self.assertTrue(result.get("pdf_page"))
            self.assertTrue(result.get("source_filename"))
            self.assertIn("component_scores", result)
            self.assertIn("ranking_explanation", result)

    def test_backward_compatibility_default_get_matter(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            baseline = mb.get_matter(documents=[], matter_folder=str(folder))
            self.assertNotIn("canonical_retrieval", baseline)
            self.assertNotIn("case_map", baseline)
            for doc in baseline.get("documents") or []:
                self.assertNotIn("exhibit_segments", doc)

            opted = mb.get_matter(
                documents=self.docs,
                matter_folder=str(folder),
                canonical_retrieval_query="premium payment",
                canonical_retrieval_options={"top_k": 5},
            )
            self.assertIn("canonical_retrieval", opted)
            self.assertTrue(opted["canonical_retrieval"]["results"])
            # Opt-in query must not force case_map into default key unless requested.
            self.assertNotIn("case_map", opted)


class CanonicalRetrievalResultShapeTests(unittest.TestCase):
    def test_result_fields_and_classifications_vocab(self):
        docs = _corpus()
        payload = mb.retrieve_canonical_records(
            docs, "Plaintiff alleges premium payment", top_k=5
        )
        self.assertTrue(payload["results"])
        result = payload["results"][0]
        required = {
            "result_id",
            "page_id",
            "nyscef_document_number",
            "pdf_page",
            "source_filename",
            "excerpt",
            "component_scores",
            "ranking_explanation",
            "classifications",
        }
        self.assertTrue(required.issubset(result.keys()))
        for flag in result["classifications"]:
            self.assertIn(flag, mb.RETRIEVAL_CLASSIFICATIONS)


if __name__ == "__main__":
    unittest.main()
