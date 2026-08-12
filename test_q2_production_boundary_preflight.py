"""Q2 production-boundary CI preflight + live sanitized replay gate.

Injects unmistakable secrets upstream; proves they are absent from replay,
logs, and result JSON. Proves live-derived supported_needs_paraphrase for
no-defense survives acceptance and JSON/Markdown parity. Demotes the
hand-built fixture so it cannot satisfy the workflow gate.
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

from engines import drafting_engine as de
from engines import q2_production_evidence_diagnostics as q2diag


REPO_ROOT = Path(__file__).resolve().parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "hal-case00-q1.yml"
DEMOTED_FIXTURE_PATH = (
    REPO_ROOT / "testdata" / "q2_production_boundary_31629603939_fixture.json"
)
PREFLIGHT_PATH = REPO_ROOT / "scripts" / "q2_production_boundary_preflight.py"

_SECRET_EXCERPT = "SECRET_EXCERPT_LEAK_TOKEN_q2replay_9f3a2c1b_NEVER_EMIT"
_SECRET_PAGE = (
    "SECRET_PAGE_TEXT_LEAK_TOKEN_q2replay_7c88ee01 Alice Example "
    "alice.example@private.test password=hunter2-private "
    "Bearer sk-live-PRIVATE- creds=ENV_SECRET_VALUE"
)
_SECRET_NAME = "TriboroughPrivatePartyNameXYZ_q2replay"
_SECRET_EMAIL = "counsel.secret.q2replay@example-private.invalid"
_SECRET_PROPOSED = (
    "SECRET_PROPOSED_ANSWER_q2replay_should_never_appear_in_replay_or_result"
)


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


def _live_shaped_packet_with_secrets() -> dict:
    """Upstream packet mirroring production OCR/length shape, with secrets."""
    page = (
        f"25\n\n"
        f"184. On the basis of the material misrepresentations the Insurer is "
        f"entitled to void the Policies ab initio and for rescission of the same. "
        f"{_SECRET_PAGE} {_SECRET_NAME} {_SECRET_EMAIL}\n"
        f"COUNT II Have No Obligations to Provide Defense or Indemnification to "
        f"Named Insured or Any Other Entity Void Ab Initio 186. Declaring that "
        f"there is no duty to defend or indemni fy Def en dants under the Policies.\n"
        f"187. WHEREFORE the Insurer demands judgment for such other and further "
        f"relief as the Court deems just and proper."
    )
    excerpt = (
        f"184. On the basis of the material misrepresentations the Insurer is "
        f"entitled to void the Policies ab initio and for rescission of the same. "
        f"{_SECRET_EXCERPT}"
    )
    return {
        "question": (
            "What relief does the complaint request in the WHEREFORE / "
            "requested-relief section?"
        ),
        "retrieval_hit_count": 2,
        "retrieval_hits": [
            {
                "result_id": "hit-secret-replay-p25",
                "page_id": "nyscef-001-page-0025",
                "nyscef_document_number": 1,
                "pdf_page": 25,
                "document_type": "complaint",
                "excerpt": excerpt,
                "page_text": page,
                "classifications": ["legal_position"],
                "score": 0.91,
            },
            {
                "result_id": "hit-secret-replay-p26",
                "page_id": "nyscef-001-page-0026",
                "nyscef_document_number": 1,
                "pdf_page": 26,
                "document_type": "complaint",
                "excerpt": (
                    "and for such other and further relief as the Court deems "
                    f"just and proper. {_SECRET_EXCERPT}"
                ),
                "classifications": ["legal_position"],
                "score": 0.85,
            },
        ],
    }


def _forbidden_substrings() -> tuple[str, ...]:
    return (
        _SECRET_EXCERPT,
        _SECRET_PAGE,
        _SECRET_NAME,
        _SECRET_EMAIL,
        _SECRET_PROPOSED,
        "alice.example@private.test",
        "hunter2-private",
        "sk-live-PRIVATE",
        "ENV_SECRET_VALUE",
        "password=",
        "Bearer ",
    )


class LiveSanitizedReplayPrivacyTests(unittest.TestCase):
    def test_replay_from_secret_packet_omits_all_sensitive_text(self) -> None:
        packet = _live_shaped_packet_with_secrets()
        # Ensure upstream extraction actually sees secrets.
        blob_upstream = json.dumps(packet)
        self.assertIn(_SECRET_EXCERPT, blob_upstream)
        self.assertIn(_SECRET_EMAIL, blob_upstream)

        replay = PRE.build_sanitized_replay_from_evidence_packet(packet)
        self.assertEqual(replay["schema_version"], PRE.REPLAY_SCHEMA_VERSION)
        blob = json.dumps(replay)
        for forbidden in _forbidden_substrings():
            self.assertNotIn(forbidden, blob)

        categories = replay["relief_synthesis"]["categories"]
        no_def = categories["no_defense_or_indemnity"]
        self.assertTrue(no_def["supported"])
        self.assertEqual(no_def["page_id"], "nyscef-001-page-0025")
        self.assertEqual(
            no_def["selection_reason_code"], "supported_needs_paraphrase"
        )
        self.assertTrue(categories["rescission_void_ab_initio"]["supported"])
        self.assertTrue(categories["catch_all_relief"]["supported"])

    def test_preflight_result_json_and_logs_omit_secrets(self) -> None:
        packet = _live_shaped_packet_with_secrets()
        replay = PRE.build_sanitized_replay_from_evidence_packet(packet)
        with tempfile.TemporaryDirectory() as tmp:
            replay_path = Path(tmp) / "replay.json"
            replay_path.write_text(
                json.dumps(replay, sort_keys=True), encoding="utf-8"
            )
            payload = PRE.run_preflight(replay_path=replay_path)
            self.assertTrue(payload["ok"], msg=payload)
            self.assertEqual(
                payload["no_defense_selection_reason_code"],
                "supported_needs_paraphrase",
            )
            self.assertTrue(payload["parity_ok"])
            result_blob = json.dumps(payload)
            for forbidden in _forbidden_substrings():
                self.assertNotIn(forbidden, result_blob)
            # Replay file itself remains free of secrets after preflight.
            replay_disk = replay_path.read_text(encoding="utf-8")
            for forbidden in _forbidden_substrings():
                self.assertNotIn(forbidden, replay_disk)

    def test_supported_needs_paraphrase_survives_acceptance_and_parity(
        self,
    ) -> None:
        packet = _live_shaped_packet_with_secrets()
        replay = PRE.build_sanitized_replay_from_evidence_packet(packet)
        PRE.assert_replay_gate_shape(replay)
        with tempfile.TemporaryDirectory() as tmp:
            replay_path = Path(tmp) / "replay.json"
            out_root = Path(tmp) / "out"
            replay_path.write_text(
                json.dumps(replay, sort_keys=True), encoding="utf-8"
            )
            payload = PRE.run_preflight(
                replay_path=replay_path,
                candidate_output_root=out_root,
            )
        self.assertTrue(payload["ok"], msg=payload)
        self.assertEqual(
            payload["no_defense_selection_reason_code"],
            "supported_needs_paraphrase",
        )
        self.assertEqual(payload["no_defense_page_id"], "nyscef-001-page-0025")
        self.assertEqual(
            payload["criterion_ids_passed"], list(PRE._REQUIRED_CRITERIA)
        )
        self.assertLess(payload["proposed_answer_char_length"], 1600)


class DemotedFixtureAndCliTests(unittest.TestCase):
    def test_hand_built_fixture_schema_is_rejected(self) -> None:
        self.assertTrue(DEMOTED_FIXTURE_PATH.is_file())
        payload = PRE.run_preflight(replay_path=DEMOTED_FIXTURE_PATH)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            payload["reason_code"], "demoted_hand_built_fixture_rejected"
        )
        self.assertEqual(payload["stage"], "replay_load")

    def test_cli_fixture_flag_is_rejected(self) -> None:
        code = PRE.main(["--fixture", str(DEMOTED_FIXTURE_PATH)])
        self.assertEqual(code, 1)

    def test_cli_main_emits_machine_readable_json_for_live_replay(self) -> None:
        packet = _live_shaped_packet_with_secrets()
        replay = PRE.build_sanitized_replay_from_evidence_packet(packet)
        with tempfile.TemporaryDirectory() as tmp:
            replay_path = Path(tmp) / "replay.json"
            replay_path.write_text(
                json.dumps(replay, sort_keys=True), encoding="utf-8"
            )
            code = PRE.main(["--replay", str(replay_path)])
        self.assertEqual(code, 0)

    def test_failure_emits_privacy_safe_reason_code_and_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps({"schema_version": "nope"}), encoding="utf-8")
            payload = PRE.run_preflight(replay_path=bad)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["phase"], PRE.PHASE)
        self.assertEqual(payload["reason_code"], "replay_schema_mismatch")
        self.assertEqual(payload["stage"], "replay_load")
        blob = json.dumps(payload)
        self.assertNotIn("proposed_answer", blob)
        self.assertNotIn("page_text", blob)

    def test_generation_failure_classifies_without_private_blocker_prose(
        self,
    ) -> None:
        packet = _live_shaped_packet_with_secrets()
        replay = PRE.build_sanitized_replay_from_evidence_packet(packet)
        with tempfile.TemporaryDirectory() as tmp:
            replay_path = Path(tmp) / "replay.json"
            replay_path.write_text(
                json.dumps(replay, sort_keys=True), encoding="utf-8"
            )

            def _boom(**_kwargs):
                raise PRE.gen.GenerationError(
                    "Acceptance-contract validation failed; secret prose must not leak",
                    finalized=False,
                )

            with mock.patch.object(PRE.gen, "run_generation", side_effect=_boom):
                payload = PRE.run_preflight(replay_path=replay_path)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["reason_code"], "generation_entrypoint_failed")
        self.assertEqual(payload["stage"], "run_generation")
        blob = json.dumps(payload)
        self.assertNotIn("secret prose", blob)
        self.assertNotIn("Acceptance-contract validation failed", blob)


class WorkflowGateTests(unittest.TestCase):
    def test_workflow_derives_replay_then_preflight_before_generation(
        self,
    ) -> None:
        text = _workflow_text()
        accept_idx = text.index("Resolve and verify acceptance contract")
        derive_idx = text.index(
            "Derive Q2 sanitized live-replay from restored evidence"
        )
        preflight_idx = text.index("Q2 production-boundary preflight")
        generate_idx = text.index(
            "Generate requested question and publish four verified artifacts to B2"
        )
        self.assertLess(accept_idx, derive_idx)
        self.assertLess(derive_idx, preflight_idx)
        self.assertLess(preflight_idx, generate_idx)
        self.assertIn("scripts/q2_production_boundary_preflight.py", text)
        self.assertIn("--derive-from-case-root", text)
        self.assertIn("--replay-out", text)
        self.assertIn('--replay "$REPLAY_JSON"', text)
        self.assertNotIn(
            "testdata/q2_production_boundary_31629603939_fixture.json",
            text,
        )
        self.assertNotIn("--fixture", text)
        self.assertIn('id: q2-replay', text)
        self.assertIn('id: q2-preflight', text)
        self.assertIn("| tee \"$RESULT_JSON\"", text)

    def test_generation_step_gated_on_replay_and_preflight_success(self) -> None:
        text = _workflow_text()
        gen_block = text.split(
            "Generate requested question and publish four verified artifacts to B2",
            1,
        )[1].split("Upload machine-readable run result", 1)[0]
        self.assertIn(
            "if: ${{ success() && steps.q2-replay.outputs.ok == 'true' && steps.q2-preflight.outputs.ok == 'true' }}",
            gen_block,
        )
        self.assertIn("scripts/run_case00_b2_q1.py", gen_block)
        self.assertIn(
            "if: ${{ success() && steps.q2-replay.outputs.ok == 'true' }}",
            text.split("Derive Q2 sanitized live-replay", 1)[1].split(
                "Generate requested question", 1
            )[0],
        )

    def test_artifact_upload_remains_always_and_never_uploads_b2_on_preflight(
        self,
    ) -> None:
        text = _workflow_text()
        self.assertIn(
            "if: ${{ always() && env.RESULT_JSON != '' && hashFiles(env.RESULT_JSON) != '' }}",
            text,
        )
        derive_block = text.split(
            "Derive Q2 sanitized live-replay from restored evidence", 1
        )[1].split("Q2 production-boundary preflight", 1)[0]
        preflight_block = text.split("Q2 production-boundary preflight", 1)[1].split(
            "Generate requested question", 1
        )[0]
        for block in (derive_block, preflight_block):
            self.assertNotIn("upload_file", block)
            self.assertNotIn("boto3", block)
            self.assertNotIn("--b2-prefix", block)

    def test_workflow_yaml_parses_and_keeps_ordered_gate_steps(self) -> None:
        doc = _load_workflow()
        self.assertIn("generate", doc["jobs"])
        steps = doc["jobs"]["generate"]["steps"]
        names = [s.get("name") for s in steps]
        self.assertIn(
            "Derive Q2 sanitized live-replay from restored evidence", names
        )
        self.assertIn("Q2 production-boundary preflight", names)
        self.assertIn(
            "Generate requested question and publish four verified artifacts to B2",
            names,
        )
        accept_i = names.index("Resolve and verify acceptance contract")
        derive_i = names.index(
            "Derive Q2 sanitized live-replay from restored evidence"
        )
        pre_i = names.index("Q2 production-boundary preflight")
        gen_i = names.index(
            "Generate requested question and publish four verified artifacts to B2"
        )
        self.assertEqual(accept_i + 1, derive_i)
        self.assertEqual(derive_i + 1, pre_i)
        self.assertEqual(pre_i + 1, gen_i)


class SanitizerReplayBuilderTests(unittest.TestCase):
    def test_diagnostics_helper_matches_preflight_builder(self) -> None:
        packet = _live_shaped_packet_with_secrets()
        via_diag = q2diag.build_sanitized_preflight_replay(packet)
        via_pre = PRE.build_sanitized_replay_from_evidence_packet(packet)
        self.assertEqual(via_diag["schema_version"], via_pre["schema_version"])
        self.assertEqual(
            via_diag["relief_synthesis"]["categories"]["no_defense_or_indemnity"][
                "selection_reason_code"
            ],
            "supported_needs_paraphrase",
        )
        # Production extract agrees with live-derived reason code.
        supported = de.extract_supported_complaint_relief(packet)
        self.assertTrue(supported["no_defense_or_indemnity"]["supported"])


if __name__ == "__main__":
    unittest.main()
