import importlib.util
import unittest
from pathlib import Path


def load_probe():
    path = Path(__file__).parent / "scripts" / "probe_case00_c5_structure.py"
    spec = importlib.util.spec_from_file_location("case00_c5_probe", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


PROBE = load_probe()
REBUILD = PROBE.rebuild


class Case00C5StructureProbeTests(unittest.TestCase):
    def test_allowlisted_rebuild_cli_exposes_probe_flag(self):
        args = REBUILD.build_parser().parse_args(
            ["--case-root", "/tmp/unused", "--probe-c5-structure"]
        )

        self.assertTrue(args.probe_c5_structure)

    def test_probe_cache_digest_must_be_lowercase_sha256(self):
        with self.assertRaisesRegex(ValueError, "64 lowercase hex"):
            PROBE.main(cache_digest="not-a-digest")

    def test_reports_only_structural_measurements(self):
        report = PROBE.build_report(
            {
                "pages": [
                    {
                        "page_id": "synthetic-page-1",
                        "text": (
                            "Defendants in Action No.: 2\n"
                            "Synthetic caption filler.\n"
                            "Plaintiff in Action Number 1"
                        ),
                    },
                    {"page_id": "other", "text": "Plaintiff only."},
                ]
            }
        )

        self.assertEqual(report["matched_page_count"], 1)
        row = report["pages"][0]
        self.assertEqual(row["page_id"], "synthetic-page-1")
        self.assertEqual(
            row["token_order"],
            ["defendant", "action_2", "plaintiff", "action_1"],
        )
        self.assertGreater(row["minimum_covering_span_characters"], 0)
        self.assertEqual(row["newline_count"], 2)
        self.assertNotIn("text", row)
        self.assertNotIn("Synthetic", repr(report))


if __name__ == "__main__":
    unittest.main()
