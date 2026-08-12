"""Q2 production-boundary CI preflight + workflow gate regressions.

Privacy-safe synthetic fixtures only. Does not touch private B2 artifacts.
"""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml


REPO_ROOT = Path(__file__).resolve().parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "hal-case00-q1.yml"
FIXTURE_PATH = (
    REPO_ROOT / "testdata" / "q2_production_boundary_31629603939_fixture.json"
)
PREFLIGHT_PATH = REPO_ROOT / "scripts" / "q2_production_boundary_preflight.py"


def _load_preflight():
    spec = importlib.util.spec_from_file_location(
        "q2_production_boundary_preflight", PREFLIGHT_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    if str(REPO_ROOT) not in os.sys.path:
        os.sys.path.insert(0, str(REPO_ROOT))
    os.sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


PRE = _load_preflight()


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _load_workflow() -> dict:
    doc = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    if isinstance(doc, dict) and True in doc and "on" not in doc:
        doc["on"] = doc.pop(True)
    return doc


class FixtureShapeTests(unittest.TestCase):
    def test_fixture_file_is_privacy_safe_and_structured(self) -> None:
        self.assertTrue(FIXTURE_PATH.is_file())
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            fixture["schema_version"],
            "q2_production_boundary_preflight_fixture.v1",
        )
        self.assertEqual(fixture["diagnostic_run_correlation_id"], "31629603939")
        blob = FIXTURE_PATH.read_text(encoding="utf-8").lower()
        for banned in (
            "@",
            "attorney_review_packet",
            "gold_answer",
            "b2_application_key",
        ):
            self.assertNotIn(banned, blob)

    def test_fixture_matches_diagnostic_length_and_relief_shape(self) -> None:
        fixture = PRE.load_fixture(FIXTURE_PATH)
        packet = PRE.build_evidence_packet(fixture)
        PRE.assert_fixture_diagnostic_shape(fixture, packet)
        self.assertEqual(len(packet["retrieval_hits"]), 2)
        h25, h26 = packet["retrieval_hits"]
        self.assertIn("page_text", h25)
        self.assertNotIn("page_text", h26)


class PreflightEntrypointTests(unittest.TestCase):
    def test_run_preflight_passes_four_criteria_and_parity(self) -> None:
        payload = PRE.run_preflight(fixture_path=FIXTURE_PATH)
        self.assertTrue(payload["ok"], msg=payload)
        self.assertEqual(payload["phase"], PRE.PHASE)
        self.assertEqual(payload["stage"], "complete")
        self.assertTrue(payload["finalized"])
        self.assertTrue(payload["parity_ok"])
        self.assertEqual(
            payload["criterion_ids_passed"],
            list(PRE._REQUIRED_CRITERIA),
        )
        self.assertEqual(
            payload["no_defense_selection_reason_code"],
            "supported_needs_paraphrase",
        )
        self.assertEqual(
            payload["no_defense_page_id"],
            "nyscef-001-page-0025",
        )
        self.assertLess(payload["proposed_answer_char_length"], 1600)

    def test_cli_main_emits_machine_readable_json(self) -> None:
        code = PRE.main(["--fixture", str(FIXTURE_PATH)])
        self.assertEqual(code, 0)

    def test_failure_emits_privacy_safe_reason_code_and_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps({"schema_version": "nope"}), encoding="utf-8")
            payload = PRE.run_preflight(fixture_path=bad)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["phase"], PRE.PHASE)
        self.assertEqual(payload["reason_code"], "fixture_schema_mismatch")
        self.assertEqual(payload["stage"], "fixture_load")
        blob = json.dumps(payload)
        self.assertNotIn("proposed_answer", blob)
        self.assertNotIn("page_text", blob)

    def test_generation_failure_classifies_without_private_blocker_prose(self) -> None:
        def _boom(**_kwargs):
            raise PRE.gen.GenerationError(
                "Acceptance-contract validation failed; secret prose must not leak",
                finalized=False,
            )

        with mock.patch.object(PRE.gen, "run_generation", side_effect=_boom):
            payload = PRE.run_preflight(fixture_path=FIXTURE_PATH)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["reason_code"], "generation_entrypoint_failed")
        self.assertEqual(payload["stage"], "run_generation")
        blob = json.dumps(payload)
        self.assertNotIn("secret prose", blob)
        self.assertNotIn("Acceptance-contract validation failed", blob)


class WorkflowGateTests(unittest.TestCase):
    def test_preflight_step_is_after_acceptance_and_before_generation(self) -> None:
        text = _workflow_text()
        accept_idx = text.index("Resolve and verify acceptance contract")
        preflight_idx = text.index("Q2 production-boundary preflight")
        generate_idx = text.index(
            "Generate requested question and publish four verified artifacts to B2"
        )
        self.assertLess(accept_idx, preflight_idx)
        self.assertLess(preflight_idx, generate_idx)
        self.assertIn("scripts/q2_production_boundary_preflight.py", text)
        self.assertIn(
            "testdata/q2_production_boundary_31629603939_fixture.json",
            text,
        )
        self.assertIn('id: q2-preflight', text)
        self.assertIn("| tee \"$RESULT_JSON\"", text)

    def test_generation_step_gated_on_preflight_success(self) -> None:
        text = _workflow_text()
        gen_block = text.split(
            "Generate requested question and publish four verified artifacts to B2",
            1,
        )[1].split("Upload machine-readable run result", 1)[0]
        self.assertIn(
            "if: ${{ success() && steps.q2-preflight.outputs.ok == 'true' }}",
            gen_block,
        )
        self.assertIn("scripts/run_case00_b2_q1.py", gen_block)

    def test_artifact_upload_remains_always_and_never_uploads_b2_on_preflight(
        self,
    ) -> None:
        text = _workflow_text()
        self.assertIn(
            "if: ${{ always() && env.RESULT_JSON != '' && hashFiles(env.RESULT_JSON) != '' }}",
            text,
        )
        preflight_block = text.split("Q2 production-boundary preflight", 1)[1].split(
            "Generate requested question", 1
        )[0]
        self.assertNotIn("upload_file", preflight_block)
        self.assertNotIn("boto3", preflight_block)
        self.assertNotIn("--b2-prefix", preflight_block)

    def test_workflow_yaml_parses_and_keeps_single_generate_job(self) -> None:
        doc = _load_workflow()
        self.assertIn("generate", doc["jobs"])
        steps = doc["jobs"]["generate"]["steps"]
        names = [s.get("name") for s in steps]
        self.assertIn("Q2 production-boundary preflight", names)
        self.assertIn(
            "Generate requested question and publish four verified artifacts to B2",
            names,
        )
        pre_i = names.index("Q2 production-boundary preflight")
        gen_i = names.index(
            "Generate requested question and publish four verified artifacts to B2"
        )
        accept_i = names.index("Resolve and verify acceptance contract")
        self.assertEqual(accept_i + 1, pre_i)
        self.assertEqual(pre_i + 1, gen_i)


if __name__ == "__main__":
    unittest.main()
