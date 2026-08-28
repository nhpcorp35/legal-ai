import unittest

from active_matter_review import ActiveMatterReviewError
from issue_packet import render_issue_packet, validate_issue_packet


PAGES = {(2, 1): {"page_id": "p1", "source_filename": "complaint.pdf", "text": "The verified complaint alleges a waterfront access dispute between the parties."}}
PACKET = {
    "case_id": "NY-Nassau-613561-2026-Desousa-v-Rennick",
    "issue": "What authorities and record proof bear on the requested temporary relief?",
    "question": "What does the verified complaint allege?",
    "proposed_answer": "It alleges a waterfront access dispute.",
    "findings": [{"statement": "The complaint alleges a waterfront access dispute.", "confidence": "strong", "evidence": [{"nyscef_document_number": 2, "page_number": 1, "quote": "waterfront access dispute between the parties"}]}],
    "authorities": [{"type": "statute", "citation": "Example Statute § 1", "source_url": "https://example.gov/statute/1", "proposition": "Sets a stated legal prerequisite.", "pinpoint": "§ 1(a)"}],
    "relief": [{"requested_relief": "Temporary relief", "legal_prerequisites": "Identify each governing prerequisite.", "record_support_or_gap": "Record proof is listed above; gaps remain for attorney review."}],
}


class SourcedIssuePacketTests(unittest.TestCase):
    def test_renders_authority_record_and_relief_sections(self):
        packet = validate_issue_packet(PACKET, PAGES)
        rendered = render_issue_packet(packet)
        self.assertIn("Controlling Authorities", rendered)
        self.assertIn("Relief Mapping", rendered)
        self.assertIn("NYSCEF 2, p. 1", rendered)

    def test_local_practice_requires_confirmation(self):
        payload = dict(PACKET)
        payload["authorities"] = [{"type": "local_practice", "citation": "Nassau clerk instruction", "source_url": "https://www.nycourts.gov/", "proposition": "Describes an OSC filing practice."}]
        packet = validate_issue_packet(payload, PAGES)
        self.assertTrue(packet["attorney_confirmation_required"])
        self.assertIn("Attorney/clerk confirmation required", render_issue_packet(packet))

    def test_rejects_unsourced_authority(self):
        payload = dict(PACKET)
        payload["authorities"] = [{"type": "case", "citation": "Example v. Example", "source_url": "", "proposition": "A rule."}]
        with self.assertRaisesRegex(ActiveMatterReviewError, "source_url"):
            validate_issue_packet(payload, PAGES)
