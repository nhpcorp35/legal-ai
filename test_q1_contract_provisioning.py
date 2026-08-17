"""Privacy-safe unit tests for Q1 contract provisioning."""

import importlib.util
import unittest
from pathlib import Path


def load_module():
    path = Path(__file__).parent / "scripts" / "provision_case00_q1_acceptance_contract.py"
    spec = importlib.util.spec_from_file_location("provision_q1_contract", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


P = load_module()


class ProvisionTests(unittest.TestCase):
    def test_extracts_only_q1_section(self):
        text = "# Packet\n## Q1. Parties\nApproved Q1 material.\n## Q2. Relief\nPrivate Q2 material.\n"
        section = P.extract_q1_section(text)
        self.assertIn("Approved Q1 material", section)
        self.assertNotIn("Private Q2 material", section)

    def test_contract_identity_and_hash_are_forced(self):
        payload = {
            "required_criterion_ids": ["party-identification"],
            "evidence_constraints": {"allowed_source_types": ["complaint"], "require_page_citations": True, "max_excerpts_per_criterion": 3},
            "semantic_preservation": {"require_same_party_roles": True, "forbid_material_omissions": True, "require_preserve_negation": True},
            "duplication_rules": {"forbid_duplicate_criterion_ids": True, "forbid_overlapping_evidence_spans": False, "max_duplicate_phrase_ratio": 0.25},
            "criteria": [{"id": "party-identification", "presence_phrases": ["party"], "evidence_phrases": ["caption"], "semantic_required_phrases": ["role"], "semantic_forbidden_phrases": [], "fallback_text": "Identify supported parties and roles.", "category": "party_roles"}],
            "structure_requirements": {"required_kinds": [], "required_ranges": [], "required_categories": ["party_roles"]},
        }
        contract = P.build_contract(payload)
        self.assertEqual(contract["identity"], {"benchmark_id": P.BENCHMARK_ID, "question_id": "Q1"})
        self.assertEqual(contract["object_key"], P.OBJECT_KEY)
        self.assertEqual(len(contract["content_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
