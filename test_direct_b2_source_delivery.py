import os
import unittest
from unittest.mock import patch

import app as legalai


CASE_ID = "NY-Nassau-613561-2026-Desousa-v-Rennick"
SOURCE_SHA256 = "a" * 64
PDF = b"%PDF-1.4\nverified source\n"


class DirectB2SourceDeliveryTests(unittest.TestCase):
    def test_generic_pdf_uses_direct_b2_and_never_calls_gateway(self):
        client = object()
        with patch.object(
            legalai, "_operator_regeneration_b2_client", return_value=(client, "bucket")
        ), patch.object(
            legalai, "open_verified_source_pdf", return_value=PDF
        ) as direct_read, patch.object(
            legalai.urllib.request, "urlopen"
        ) as gateway:
            result = legalai.open_indexed_case_pdf(
                CASE_ID, SOURCE_SHA256, "Record.pdf"
            )

        self.assertEqual(result, PDF)
        direct_read.assert_called_once_with(
            client, "bucket", CASE_ID, SOURCE_SHA256, "Record.pdf"
        )
        gateway.assert_not_called()

    def test_generic_b2_validation_failure_does_not_downgrade_to_gateway(self):
        client = object()
        with patch.object(
            legalai, "_operator_regeneration_b2_client", return_value=(client, "bucket")
        ), patch.object(
            legalai, "open_verified_source_pdf", side_effect=ValueError("bad manifest")
        ), patch.object(legalai.urllib.request, "urlopen") as gateway:
            result = legalai.open_indexed_case_pdf(
                CASE_ID, SOURCE_SHA256, "Record.pdf"
            )

        self.assertIsNone(result)
        gateway.assert_not_called()

    def test_case00_pdf_uses_direct_b2_and_never_calls_gateway(self):
        source = {"filename": "Complaint.pdf", "source_sha256": SOURCE_SHA256}
        with patch.object(legalai, "load_case00_source_map", return_value=[source]), patch.object(
            legalai.os.path, "isfile", return_value=False
        ), patch.object(
            legalai, "_operator_regeneration_b2_client", return_value=(object(), "bucket")
        ), patch.object(
            legalai, "open_hash_verified_pdf_object", return_value=PDF
        ) as direct_read, patch.object(
            legalai, "open_indexed_case_pdf"
        ) as gateway:
            result = legalai.open_case00_source_pdf("Complaint.pdf")

        self.assertEqual(result, PDF)
        direct_read.assert_called_once()
        gateway.assert_not_called()

    def test_case00_b2_validation_failure_does_not_downgrade_to_gateway(self):
        source = {"filename": "Complaint.pdf", "source_sha256": SOURCE_SHA256}
        with patch.object(legalai, "load_case00_source_map", return_value=[source]), patch.object(
            legalai.os.path, "isfile", return_value=False
        ), patch.object(
            legalai, "_operator_regeneration_b2_client", return_value=(object(), "bucket")
        ), patch.object(
            legalai, "open_hash_verified_pdf_object", side_effect=ValueError("bad hash")
        ), patch.object(legalai, "open_indexed_case_pdf") as gateway:
            result = legalai.open_case00_source_pdf("Complaint.pdf")

        self.assertIsNone(result)
        gateway.assert_not_called()


if __name__ == "__main__":
    unittest.main()
