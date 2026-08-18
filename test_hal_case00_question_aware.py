"""Question-aware HAL Case-00 workflow and durable upload regression tests."""

from __future__ import annotations

import importlib.util
import hashlib
import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml


REPO_ROOT = Path(__file__).resolve().parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "hal-case00-q1.yml"
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_case00_b2_q1.py"
QUESTION_ID_RE = re.compile(r"^Q[1-9][0-9]*$")
REQUIRED_BENCHMARK = "Case-00-Triborough"
CANONICAL_PREFIX = (
    "Benchmarks/Case-00-Triborough/derived/attorney-feedback-eval/candidate-answers/"
)


def _load_cli():
    spec = importlib.util.spec_from_file_location("run_case00_b2_q1_qaware", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    if str(REPO_ROOT) not in os.sys.path:
        os.sys.path.insert(0, str(REPO_ROOT))
    os.sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


CLI = _load_cli()


def _load_workflow() -> dict:
    # PyYAML 1.1 coerces the bare key ``on:`` to boolean True.
    doc = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    if isinstance(doc, dict) and True in doc and "on" not in doc:
        doc["on"] = doc.pop(True)
    return doc


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _b2_env() -> dict[str, str]:
    return {
        "B2_KEY_ID": "key-id-secret-value",
        "B2_APPLICATION_KEY": "app-key-secret-value",
        "B2_BUCKET": "legalai-corpus",
        "B2_ENDPOINT": "https://s3.us-east-005.backblazeb2.com",
        "B2_REGION": "us-east-005",
    }


def _acceptance_env() -> dict[str, str]:
    return {
        CLI.ACCEPTANCE_CONTRACT_OBJECT_KEY_ENV: (
            "Contracts/synthetic/alpha/Q-SYNTH-01.acceptance_contract.json"
        ),
        CLI.ACCEPTANCE_CONTRACT_CONTENT_SHA256_ENV: "a" * 64,
        CLI.ACCEPTANCE_CONTRACT_BENCHMARK_ID_ENV: "synth-benchmark-alpha",
    }


def _wrapper_env() -> dict[str, str]:
    return {**_b2_env(), **_acceptance_env()}


def _seed_candidate_dir(path: Path, question_id: str = "Q1") -> dict[str, int]:
    path.mkdir(parents=True, exist_ok=True)
    sizes: dict[str, int] = {}
    for index, name in enumerate(CLI.candidate_artifact_names(question_id)):
        body = f"artifact-{name}-{index}\n".encode("utf-8")
        (path / name).write_bytes(body)
        sizes[name] = len(body)
    return sizes


class WorkflowSurfaceTests(unittest.TestCase):
    def test_workflow_filename_preserved(self) -> None:
        self.assertTrue(WORKFLOW_PATH.is_file())
        self.assertEqual(WORKFLOW_PATH.name, "hal-case00-q1.yml")

    def test_required_bridge_inputs_present(self) -> None:
        inputs = _load_workflow()["on"]["workflow_dispatch"]["inputs"]
        for name in (
            "mission_id",
            "legalai_ref",
            "authorization_confirmed",
            "benchmark_id",
            "question_id",
        ):
            with self.subTest(name=name):
                self.assertIn(name, inputs)
                self.assertTrue(inputs[name].get("required"))

    def test_authorization_confirmed_remains_boolean_fail_closed_default(self) -> None:
        auth = _load_workflow()["on"]["workflow_dispatch"]["inputs"][
            "authorization_confirmed"
        ]
        self.assertEqual(auth["type"], "boolean")
        self.assertIs(auth["default"], False)

    def test_benchmark_and_question_are_required_strings(self) -> None:
        inputs = _load_workflow()["on"]["workflow_dispatch"]["inputs"]
        self.assertEqual(inputs["benchmark_id"]["type"], "string")
        self.assertEqual(inputs["question_id"]["type"], "string")
        self.assertTrue(inputs["benchmark_id"]["required"])
        self.assertTrue(inputs["question_id"]["required"])

    def test_permissions_remain_contents_read(self) -> None:
        self.assertEqual(_load_workflow()["permissions"], {"contents": "read"})

    def test_job_env_exports_benchmark_and_question(self) -> None:
        env = _load_workflow()["jobs"]["generate"]["env"]
        self.assertEqual(env["BENCHMARK_ID"], "${{ inputs.benchmark_id }}")
        self.assertEqual(env["QUESTION_ID"], "${{ inputs.question_id }}")
        self.assertEqual(env["REQUIRED_COMMIT"], "${{ inputs.legalai_ref }}")

    def test_concurrency_and_run_name_are_question_aware(self) -> None:
        doc = _load_workflow()
        self.assertIn("${{ inputs.question_id }}", doc["run-name"])
        self.assertIn(
            "${{ inputs.question_id }}",
            doc["concurrency"]["group"],
        )

    def test_gate_requires_exact_benchmark_id(self) -> None:
        text = _workflow_text()
        self.assertIn('test "$BENCHMARK_ID" = "Case-00-Triborough"', text)

    def test_gate_requires_question_id_regex(self) -> None:
        text = _workflow_text()
        self.assertIn('[[ "$QUESTION_ID" =~ ^Q[1-9][0-9]*$ ]]', text)

    def test_gate_preserves_authorization_confirmed(self) -> None:
        text = _workflow_text()
        self.assertIn(
            'test "${{ inputs.authorization_confirmed }}" = "true"',
            text,
        )

    def test_gate_preserves_lowercase_40_char_sha_check(self) -> None:
        text = _workflow_text()
        self.assertIn("[0-9a-f][0-9a-f][0-9a-f][0-9a-f]", text)
        self.assertIn('test "${#REQUIRED_COMMIT}" -eq 40', text)

    def test_stage_step_uses_requested_question_id(self) -> None:
        text = _workflow_text()
        stage_block = text.split("Stage permitted question text", 1)[1].split(
            "Compute Case-00 derived cache key", 1
        )[0]
        self.assertIn('question_id = os.environ["QUESTION_ID"]', stage_block)
        self.assertIn("stage_question_from_canonical_b2_packet", stage_block)
        self.assertIn('question_id=question_id', stage_block)
        self.assertNotIn('== "Q1"', stage_block)
        self.assertNotIn("attorney_review_packet_02.json", stage_block)
        self.assertNotIn("checked-in permitted packet", stage_block)

    def test_generator_invoked_with_requested_question_id(self) -> None:
        text = _workflow_text()
        self.assertIn('--question-id "$QUESTION_ID"', text)
        self.assertIn("scripts/run_case00_b2_q1.py", text)
        self.assertIn("--authorization-confirmed", text)
        self.assertIn("--generation-only", text)
        self.assertIn("--reuse-derived", text)
        self.assertIn("--acceptance-contract-object-key", text)
        self.assertIn("--acceptance-contract-content-sha256", text)
        self.assertIn("--acceptance-contract-benchmark-id", text)
        self.assertIn(
            "${{ steps.acceptance-contract.outputs.object_key }}",
            text,
        )
        self.assertIn(
            "${{ steps.acceptance-contract.outputs.content_sha256 }}",
            text,
        )
        self.assertIn(
            "${{ steps.acceptance-contract.outputs.benchmark_id }}",
            text,
        )

    def test_acceptance_contract_resolve_step_is_question_aware(self) -> None:
        text = _workflow_text()
        self.assertIn("Resolve and verify acceptance contract", text)
        self.assertIn("resolve_and_verify_canonical_acceptance_contract", text)
        self.assertIn('benchmark_id=os.environ["BENCHMARK_ID"]', text)
        self.assertIn('question_id=os.environ["QUESTION_ID"]', text)
        self.assertIn("AcceptanceContractConfigError", text)
        # Pins are step outputs — not hardcoded private digests / body.
        self.assertNotIn("a" * 64, text)
        resolve_block = text.split(
            "Resolve and verify acceptance contract", 1
        )[1].split("Generate requested question", 1)[0]
        self.assertIn('"phase": "acceptance_contract"', resolve_block)
        self.assertIn("object_key=", resolve_block)
        self.assertIn("content_sha256=", resolve_block)
        self.assertNotIn("proposed_answer", resolve_block)
        self.assertNotIn("presence_phrases", resolve_block)

    def test_result_json_and_artifact_use_lowercase_question_id(self) -> None:
        text = _workflow_text()
        self.assertIn(
            'echo "RESULT_JSON=case00-${qid_lower}-result.json"',
            text,
        )
        self.assertIn(
            "name: hal-case00-${{ env.QUESTION_ID_LOWER }}-${{ inputs.mission_id }}",
            text,
        )
        self.assertIn("path: ${{ env.RESULT_JSON }}", text)

    def test_q1_result_and_artifact_names_remain_compatible(self) -> None:
        qid_lower = "Q1".lower()
        self.assertEqual(f"case00-{qid_lower}-result.json", "case00-q1-result.json")
        self.assertEqual(
            f"hal-case00-{qid_lower}-mission-1",
            "hal-case00-q1-mission-1",
        )

    def test_workflow_does_not_embed_private_benchmark_payload(self) -> None:
        text = _workflow_text()
        self.assertNotIn("proposed_answer", text)
        self.assertNotIn("gold_answer", text)
        self.assertNotIn("ACCEPTANCE_CONTRACT_CONTENT_SHA256", text)
        self.assertNotIn("What declarations, causes of action", text)
        stage_block = text.split("Stage permitted question text", 1)[1].split(
            "Compute Case-00 derived cache key", 1
        )[0]
        self.assertIn("stage_question_from_canonical_b2_packet", stage_block)
        self.assertIn("PacketStagingError", stage_block)
        self.assertNotIn("attorney_review_packet_02.json", text)
        self.assertNotIn("checked-in permitted packet", text)
        # Allowlisted key + digests live in the helper module, not as packet body.
        self.assertIn(
            "attorney_review_packet_02-original.md",
            CLI.CANONICAL_ATTORNEY_REVIEW_PACKET_OBJECT_KEY,
        )
        self.assertIn(
            "review-20260802-2122f82dafe3",
            CLI.CANONICAL_ATTORNEY_REVIEW_PACKET_OBJECT_KEY,
        )

    def test_b2_boundaries_unchanged(self) -> None:
        text = _workflow_text()
        self.assertIn(
            "Benchmarks/Case-00-Triborough/derived/runtime-cache/",
            text,
        )
        self.assertIn("B2_KEY_ID: ${{ secrets.B2_KEY_ID }}", text)
        self.assertIn("B2_APPLICATION_KEY: ${{ secrets.B2_APPLICATION_KEY }}", text)
        self.assertIn("B2_BUCKET: ${{ secrets.B2_BUCKET }}", text)
        self.assertEqual(
            CLI.CANONICAL_ATTORNEY_REVIEW_PACKET_OBJECT_KEY,
            (
                "Benchmarks/Case-00-Triborough/derived/attorney-feedback-eval/"
                "attorney-reviews/review-20260802-2122f82dafe3/"
                "attorney_review_packet_02-original.md"
            ),
        )
        self.assertEqual(CLI.CANONICAL_ATTORNEY_REVIEW_PACKET_SIZE, 57278)
        self.assertEqual(
            CLI.CANONICAL_ATTORNEY_REVIEW_PACKET_SHA256,
            "ce7e3a25b22ec23822aec4dcd317b1df38ce6c85b59f684f45f3bdb811316d86",
        )


class QuestionIdValidationTests(unittest.TestCase):
    def test_accepted_question_ids(self) -> None:
        for qid in ("Q1", "Q2", "Q9", "Q10", "Q99", "Q123"):
            with self.subTest(qid=qid):
                self.assertRegex(qid, QUESTION_ID_RE)

    def test_rejected_question_ids(self) -> None:
        for qid in ("", "Q", "Q0", "Q01", "q1", "1", "QQ1", "Q1a", " Q1", "Q1 "):
            with self.subTest(qid=qid):
                self.assertIsNone(QUESTION_ID_RE.fullmatch(qid))

    def test_required_benchmark_constant(self) -> None:
        self.assertEqual(REQUIRED_BENCHMARK, "Case-00-Triborough")
        self.assertNotEqual(REQUIRED_BENCHMARK, "case-00-triborough")


class CandidateArtifactNameTests(unittest.TestCase):
    def test_q1_preserves_historical_names(self) -> None:
        self.assertEqual(
            CLI.candidate_artifact_names("Q1"),
            (
                "Q1_candidate_answer.json",
                "Q1_candidate_answer.md",
                "generation_manifest.json",
                "model_input_audit.json",
                "case00_attorney_review_packet.md",
            ),
        )
        self.assertEqual(CLI.CANDIDATE_ARTIFACT_NAMES, CLI.candidate_artifact_names("Q1"))

    def test_q2_uses_question_aware_names(self) -> None:
        self.assertEqual(
            CLI.candidate_artifact_names("Q2"),
            (
                "Q2_candidate_answer.json",
                "Q2_candidate_answer.md",
                "generation_manifest.json",
                "model_input_audit.json",
                "case00_attorney_review_packet.md",
            ),
        )

    def test_q10_uses_question_aware_names(self) -> None:
        names = CLI.candidate_artifact_names("Q10")
        self.assertEqual(names[0], "Q10_candidate_answer.json")
        self.assertEqual(names[1], "Q10_candidate_answer.md")

    def test_empty_question_id_fails_closed(self) -> None:
        with self.assertRaises(CLI.DurableUploadError):
            CLI.candidate_artifact_names("")
        with self.assertRaises(CLI.DurableUploadError):
            CLI.candidate_artifact_names("   ")


class QuestionAwareUploadTests(unittest.TestCase):
    def test_upload_q1_keeps_historical_object_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = Path(tmp) / "q1-candidate-20260811T000000Z"
            sizes = _seed_candidate_dir(candidate, "Q1")
            client = MagicMock()

            def fake_head(*, Bucket, Key):
                name = Key.rsplit("/", 1)[-1]
                return {"ContentLength": sizes[name], "ETag": f'"{name}-etag"'}

            client.upload_file.return_value = None
            client.head_object.side_effect = fake_head
            config = CLI.rebuild_cli.B2Config.from_env(_b2_env())
            durable = CLI.upload_candidate_artifacts_to_b2(
                candidate,
                prefix=CANONICAL_PREFIX,
                client=client,
                config=config,
                question_id="Q1",
            )
            expected = [
                f"{CANONICAL_PREFIX}{candidate.name}/{name}"
                for name in CLI.candidate_artifact_names("Q1")
            ]
            self.assertEqual(durable["object_keys"], expected)
            self.assertEqual(durable["question_id"], "Q1")

    def test_upload_q2_uses_dynamic_object_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = Path(tmp) / "q2-candidate-20260811T000000Z"
            sizes = _seed_candidate_dir(candidate, "Q2")
            client = MagicMock()

            def fake_head(*, Bucket, Key):
                name = Key.rsplit("/", 1)[-1]
                return {"ContentLength": sizes[name], "ETag": '"ok"'}

            client.upload_file.return_value = None
            client.head_object.side_effect = fake_head
            config = CLI.rebuild_cli.B2Config.from_env(_b2_env())
            durable = CLI.upload_candidate_artifacts_to_b2(
                candidate,
                prefix=CANONICAL_PREFIX,
                client=client,
                config=config,
                question_id="Q2",
            )
            self.assertTrue(
                all("/Q2_candidate_answer." in key or key.endswith(
                    (
                        "generation_manifest.json",
                        "model_input_audit.json",
                        "case00_attorney_review_packet.md",
                    )
                )
                for key in durable["object_keys"])
            )
            self.assertEqual(durable["question_id"], "Q2")
            self.assertEqual(len(durable["object_keys"]), 5)

    def test_upload_rejects_unexpected_q2_filename(self) -> None:
        with self.assertRaises(CLI.DurableUploadError) as ctx:
            CLI.build_candidate_object_key(
                CANONICAL_PREFIX,
                "q2-candidate-x",
                "Q1_candidate_answer.json",
                question_id="Q2",
            )
        self.assertIn("unexpected candidate artifact name", ctx.exception.message)

    def test_default_upload_path_remains_q1_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = Path(tmp) / "q1-candidate-default"
            sizes = _seed_candidate_dir(candidate, "Q1")
            client = MagicMock()

            def fake_head(*, Bucket, Key):
                name = Key.rsplit("/", 1)[-1]
                return {"ContentLength": sizes[name], "ETag": '"ok"'}

            client.upload_file.return_value = None
            client.head_object.side_effect = fake_head
            config = CLI.rebuild_cli.B2Config.from_env(_b2_env())
            durable = CLI.upload_candidate_artifacts_to_b2(
                candidate,
                prefix=CANONICAL_PREFIX,
                client=client,
                config=config,
            )
            self.assertTrue(
                durable["object_keys"][0].endswith("/Q1_candidate_answer.json")
            )


class WrapperQuestionRoutingTests(unittest.TestCase):
    def _run_wrapper(self, question_id: str, candidate: Path, sizes: dict[str, int]):
        generation_payload = {
            "ok": True,
            "finalized": True,
            "candidate_directory": str(candidate),
        }
        rebuild_ok = MagicMock(returncode=0, stdout="{}\n", stderr="")
        generation_ok = MagicMock(
            returncode=0,
            stdout=json.dumps(generation_payload) + "\n",
            stderr="",
        )
        client = MagicMock()

        def fake_head(*, Bucket, Key):
            name = Key.rsplit("/", 1)[-1]
            return {"ContentLength": sizes[name], "ETag": f'"{name}"'}

        client.upload_file.return_value = None
        client.head_object.side_effect = fake_head
        run_calls: list[list[str]] = []

        def capture_run(argv, cwd):
            run_calls.append(list(argv))
            if len(run_calls) == 1:
                return rebuild_ok
            return generation_ok

        with patch.dict(os.environ, _wrapper_env(), clear=False):
            with patch.object(CLI, "_run", side_effect=capture_run):
                with patch.object(
                    CLI.rebuild_cli,
                    "create_b2_client",
                    return_value=client,
                ):
                    with patch.object(
                        CLI,
                        "render_candidate_review_packet",
                        return_value=candidate / "case00_attorney_review_packet.md",
                    ):
                        captured = io.StringIO()
                        with patch("sys.stdout", captured):
                            code = CLI.main(
                            [
                                "--case-root",
                                str(candidate.parent),
                                "--question-id",
                                question_id,
                                "--required-commit",
                                "c" * 40,
                                "--candidate-output-root",
                                str(candidate.parent),
                                "--authorization-confirmed",
                                "--generation-only",
                            ]
                        )
        return code, json.loads(captured.getvalue()), run_calls

    def test_wrapper_passes_q1_through_and_uploads_q1_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = Path(tmp) / "q1-candidate-wrap"
            sizes = _seed_candidate_dir(candidate, "Q1")
            code, payload, run_calls = self._run_wrapper("Q1", candidate, sizes)
            self.assertEqual(code, 0)
            self.assertTrue(payload["ok"])
            self.assertIn("Q1", run_calls[1])
            self.assertTrue(
                payload["durable_artifacts"]["object_keys"][0].endswith(
                    "/Q1_candidate_answer.json"
                )
            )

    def test_wrapper_passes_q2_through_and_uploads_q2_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = Path(tmp) / "q2-candidate-wrap"
            sizes = _seed_candidate_dir(candidate, "Q2")
            code, payload, run_calls = self._run_wrapper("Q2", candidate, sizes)
            self.assertEqual(code, 0)
            self.assertTrue(payload["ok"])
            self.assertIn("Q2", run_calls[1])
            keys = payload["durable_artifacts"]["object_keys"]
            self.assertTrue(any(key.endswith("/Q2_candidate_answer.json") for key in keys))
            self.assertTrue(any(key.endswith("/Q2_candidate_answer.md") for key in keys))

    def test_wrapper_q2_missing_local_artifact_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = Path(tmp) / "q2-candidate-missing"
            sizes = _seed_candidate_dir(candidate, "Q2")
            (candidate / "Q2_candidate_answer.json").unlink()
            generation_payload = {
                "ok": True,
                "finalized": True,
                "candidate_directory": str(candidate),
            }
            rebuild_ok = MagicMock(returncode=0, stdout="{}\n", stderr="")
            generation_ok = MagicMock(
                returncode=0,
                stdout=json.dumps(generation_payload) + "\n",
                stderr="",
            )
            client = MagicMock()
            with patch.dict(os.environ, _wrapper_env(), clear=False):
                with patch.object(
                    CLI, "_run", side_effect=[rebuild_ok, generation_ok]
                ):
                    with patch.object(
                        CLI.rebuild_cli,
                        "create_b2_client",
                        return_value=client,
                    ):
                        captured = io.StringIO()
                        with patch("sys.stdout", captured):
                            code = CLI.main(
                                [
                                    "--case-root",
                                    str(candidate.parent),
                                    "--question-id",
                                    "Q2",
                                    "--required-commit",
                                    "d" * 40,
                                    "--candidate-output-root",
                                    str(candidate.parent),
                                    "--authorization-confirmed",
                                    "--generation-only",
                                ]
                            )
            self.assertNotEqual(code, 0)
            payload = json.loads(captured.getvalue())
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["phase"], "durable_upload")
            client.upload_file.assert_not_called()
            self.assertEqual(sizes["Q2_candidate_answer.md"], (candidate / "Q2_candidate_answer.md").stat().st_size)

    def test_no_secret_leakage_for_q2_upload_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = Path(tmp) / "q2-candidate-secrets"
            _seed_candidate_dir(candidate, "Q2")
            client = MagicMock()
            client.upload_file.side_effect = RuntimeError(
                "boom key-id-secret-value app-key-secret-value"
            )
            config = CLI.rebuild_cli.B2Config.from_env(_b2_env())
            with self.assertRaises(CLI.DurableUploadError) as ctx:
                CLI.upload_candidate_artifacts_to_b2(
                    candidate,
                    prefix=CANONICAL_PREFIX,
                    client=client,
                    config=config,
                    question_id="Q2",
                )
            blob = ctx.exception.message + json.dumps(ctx.exception.details)
            self.assertNotIn("key-id-secret-value", blob)
            self.assertNotIn("app-key-secret-value", blob)


class StagingContractTests(unittest.TestCase):
    """Synthetic non-private fixtures for canonical packet question staging."""

    SYNTHETIC_MARKDOWN = (
        "# Synthetic attorney review packet\n\n"
        "## Q1. Who are the parties in the synthetic matter?\n\n"
        "Private-looking body for Q1 that must not be staged.\n\n"
        "## Q2. What relief does the synthetic complaint request?\n\n"
        "Private-looking body for Q2 that must not be staged.\n\n"
        "## Q10. How is venue alleged in the synthetic filing?\n\n"
        "Trailing notes.\n"
    )

    def _synthetic_bytes(self) -> bytes:
        return self.SYNTHETIC_MARKDOWN.encode("utf-8")

    def test_extract_q1_and_q2_headings(self) -> None:
        md = self.SYNTHETIC_MARKDOWN
        self.assertEqual(
            CLI.extract_question_heading_from_markdown(md, "Q1"),
            "Who are the parties in the synthetic matter?",
        )
        self.assertEqual(
            CLI.extract_question_heading_from_markdown(md, "Q2"),
            "What relief does the synthetic complaint request?",
        )
        self.assertEqual(
            CLI.extract_question_heading_from_markdown(md, "Q10"),
            "How is venue alleged in the synthetic filing?",
        )

    def test_extract_missing_question_fails_closed(self) -> None:
        with self.assertRaises(CLI.PacketStagingError) as ctx:
            CLI.extract_question_heading_from_markdown(self.SYNTHETIC_MARKDOWN, "Q3")
        self.assertIn("missing from canonical packet", ctx.exception.message)
        self.assertEqual(ctx.exception.details.get("question_id"), "Q3")
        blob = ctx.exception.message + json.dumps(ctx.exception.details)
        self.assertNotIn("synthetic complaint", blob)
        self.assertNotIn("Private-looking", blob)

    def test_verify_digest_mismatch_fails_closed(self) -> None:
        payload = self._synthetic_bytes()
        with self.assertRaises(CLI.PacketStagingError) as ctx:
            CLI.verify_canonical_packet_bytes(
                payload,
                expected_size=len(payload),
                expected_sha256="0" * 64,
            )
        self.assertIn("sha256 mismatch", ctx.exception.message)
        self.assertEqual(ctx.exception.details.get("expected_sha256"), "0" * 64)
        self.assertEqual(
            ctx.exception.details.get("actual_sha256"),
            hashlib.sha256(payload).hexdigest(),
        )

    def test_verify_size_mismatch_fails_closed(self) -> None:
        payload = self._synthetic_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        with self.assertRaises(CLI.PacketStagingError) as ctx:
            CLI.verify_canonical_packet_bytes(
                payload,
                expected_size=len(payload) + 1,
                expected_sha256=digest,
            )
        self.assertIn("size mismatch", ctx.exception.message)
        self.assertEqual(ctx.exception.details.get("expected_size"), len(payload) + 1)
        self.assertEqual(ctx.exception.details.get("actual_size"), len(payload))

    def test_stage_writes_requested_question_only(self) -> None:
        payload = self._synthetic_bytes()
        digest = hashlib.sha256(payload).hexdigest()

        class _Body:
            def __init__(self, data: bytes) -> None:
                self._data = data

            def read(self) -> bytes:
                return self._data

        client = MagicMock()
        client.get_object.return_value = {"Body": _Body(payload)}
        config = CLI.rebuild_cli.B2Config.from_env(_b2_env())

        with tempfile.TemporaryDirectory() as tmp:
            case_root = Path(tmp) / "case"
            for question_id, expected in (
                ("Q1", "Who are the parties in the synthetic matter?"),
                ("Q2", "What relief does the synthetic complaint request?"),
            ):
                result = CLI.stage_question_from_canonical_b2_packet(
                    case_root=case_root,
                    question_id=question_id,
                    client=client,
                    config=config,
                    expected_size=len(payload),
                    expected_sha256=digest,
                )
                self.assertTrue(result["ok"])
                self.assertEqual(result["question_id"], question_id)
                self.assertEqual(
                    result["object_key"],
                    CLI.CANONICAL_ATTORNEY_REVIEW_PACKET_OBJECT_KEY,
                )
                loaded = json.loads(
                    Path(result["questions_json"]).read_text(encoding="utf-8")
                )
                self.assertEqual(set(loaded), {question_id})
                self.assertEqual(loaded[question_id], expected)
                # Safe status payload must not include question text.
                status = json.dumps(
                    {k: v for k, v in result.items() if k != "questions_json"},
                    sort_keys=True,
                )
                self.assertNotIn(expected, status)

        client.get_object.assert_called()
        for call in client.get_object.call_args_list:
            key = call.kwargs.get("Key")
            if key is None and call.args:
                # boto3-style positional fallback is unused; require Key kwarg.
                key = call.args[1] if len(call.args) > 1 else None
            self.assertEqual(key, CLI.CANONICAL_ATTORNEY_REVIEW_PACKET_OBJECT_KEY)

    def test_stage_missing_question_fails_before_write(self) -> None:
        payload = self._synthetic_bytes()
        digest = hashlib.sha256(payload).hexdigest()

        class _Body:
            def read(self) -> bytes:
                return payload

        client = MagicMock()
        client.get_object.return_value = {"Body": _Body()}
        config = CLI.rebuild_cli.B2Config.from_env(_b2_env())
        with tempfile.TemporaryDirectory() as tmp:
            case_root = Path(tmp) / "case"
            with self.assertRaises(CLI.PacketStagingError) as ctx:
                CLI.stage_question_from_canonical_b2_packet(
                    case_root=case_root,
                    question_id="Q9",
                    client=client,
                    config=config,
                    expected_size=len(payload),
                    expected_sha256=digest,
                )
            self.assertIn("missing from canonical packet", ctx.exception.message)
            questions_path = (
                case_root / "derived" / "question-text" / "questions.json"
            )
            self.assertFalse(questions_path.exists())

    def test_refuse_non_allowlisted_object_key(self) -> None:
        client = MagicMock()
        config = CLI.rebuild_cli.B2Config.from_env(_b2_env())
        with self.assertRaises(CLI.PacketStagingError) as ctx:
            CLI.download_allowlisted_packet_bytes(
                client=client,
                config=config,
                object_key="Benchmarks/other/not-allowlisted.md",
            )
        self.assertIn("non-allowlisted", ctx.exception.message)
        client.get_object.assert_not_called()


class ResultNamingHelpersTests(unittest.TestCase):
    def test_result_json_naming(self) -> None:
        for qid, expected in (
            ("Q1", "case00-q1-result.json"),
            ("Q2", "case00-q2-result.json"),
            ("Q10", "case00-q10-result.json"),
        ):
            with self.subTest(qid=qid):
                self.assertEqual(
                    f"case00-{qid.lower()}-result.json",
                    expected,
                )

    def test_artifact_naming(self) -> None:
        for qid, mission, expected in (
            ("Q1", "m1", "hal-case00-q1-m1"),
            ("Q2", "bridge-9", "hal-case00-q2-bridge-9"),
            ("Q10", "x", "hal-case00-q10-x"),
        ):
            with self.subTest(qid=qid, mission=mission):
                self.assertEqual(
                    f"hal-case00-{qid.lower()}-{mission}",
                    expected,
                )


class PrefixSafetyRegressionTests(unittest.TestCase):
    def test_canonical_prefix_unchanged(self) -> None:
        self.assertEqual(CLI.DEFAULT_CANDIDATE_B2_PREFIX, CANONICAL_PREFIX)

    def test_q2_keys_remain_under_canonical_prefix(self) -> None:
        key = CLI.build_candidate_object_key(
            CANONICAL_PREFIX,
            "q2-candidate-safe",
            "Q2_candidate_answer.json",
            question_id="Q2",
        )
        CLI.assert_key_under_prefix(key, CANONICAL_PREFIX)
        self.assertTrue(key.startswith(CANONICAL_PREFIX))


class CanonicalAcceptanceContractResolveTests(unittest.TestCase):
    """Question-aware acceptance-contract resolution (synthetic fixtures only)."""

    Q2_PREFIX = (
        "Benchmarks/acceptance-contracts/case-00-triborough/Q2/"
        "case00-triborough-q2/"
    )
    Q2_OBJECT_KEY_V100 = Q2_PREFIX + "v1.0.0/acceptance_contract.json"
    Q2_OBJECT_KEY_V101 = Q2_PREFIX + "v1.0.1/acceptance_contract.json"
    # Historical alias used by older assertions.
    Q2_OBJECT_KEY = Q2_OBJECT_KEY_V100

    def _synth_doc(
        self,
        *,
        benchmark_id: str = REQUIRED_BENCHMARK,
        question_id: str = "Q2",
        object_key: str | None = None,
        version: str = "1.0.0",
        contract_id: str = "contract-synth-case00-q2",
        poison_phrase: str = "PRIVATE_CONTRACT_BODY_MUST_NOT_LEAK",
    ) -> dict:
        import acceptance_contract as ac

        key = object_key or self.Q2_OBJECT_KEY_V100
        doc = ac.build_synthetic_contract(
            contract_id=contract_id,
            version=version,
            benchmark_id=benchmark_id,
            question_id=question_id,
            object_key=key,
            required_criterion_ids=["crit-synth-a"],
        )
        # Inject a distinctive private-looking phrase into criterion prose so
        # redaction tests can assert it never appears in errors/status.
        doc["criteria"][0]["fallback_text"] = (
            f"Synthetic fallback containing {poison_phrase} for redaction checks."
        )
        doc["content_sha256"] = ac.compute_content_sha256(doc)
        return doc

    def _payload(self, doc: dict) -> bytes:
        return json.dumps(doc, sort_keys=True).encode("utf-8")

    def test_selects_highest_semver_from_unordered_listing(self) -> None:
        # Oldest-first listing must not control selection.
        listing = [
            {"key": self.Q2_OBJECT_KEY_V100, "size": 3463},
            {"key": self.Q2_OBJECT_KEY_V101, "size": 2709},
        ]
        spec = CLI.resolve_canonical_acceptance_contract_spec(
            benchmark_id=REQUIRED_BENCHMARK,
            question_id="Q2",
            object_keys=listing,
        )
        self.assertEqual(spec["object_key"], self.Q2_OBJECT_KEY_V101)
        self.assertEqual(spec["expected_size"], 2709)
        self.assertEqual(spec["version"], "v1.0.1")
        self.assertEqual(spec["contract_id"], "case00-triborough-q2")
        self.assertEqual(spec["benchmark_id"], REQUIRED_BENCHMARK)
        self.assertEqual(spec["question_id"], "Q2")
        self.assertEqual(
            CLI.build_canonical_acceptance_contract_object_key(
                REQUIRED_BENCHMARK, "Q2", version="v1.0.1"
            ),
            self.Q2_OBJECT_KEY_V101,
        )

    def test_unordered_listing_prefers_v101_over_v100(self) -> None:
        candidates = CLI.list_acceptance_contract_version_candidates(
            [
                {"key": self.Q2_OBJECT_KEY_V101, "size": 2709},
                {"key": self.Q2_OBJECT_KEY_V100, "size": 3463},
            ],
            prefix=self.Q2_PREFIX,
        )
        selected = CLI.select_highest_acceptance_contract_candidate(candidates)
        self.assertEqual(selected["version"], "v1.0.1")
        # Same result when listing order flips.
        candidates_rev = CLI.list_acceptance_contract_version_candidates(
            [
                {"key": self.Q2_OBJECT_KEY_V100, "size": 3463},
                {"key": self.Q2_OBJECT_KEY_V101, "size": 2709},
            ],
            prefix=self.Q2_PREFIX,
        )
        selected_rev = CLI.select_highest_acceptance_contract_candidate(candidates_rev)
        self.assertEqual(selected_rev["object_key"], self.Q2_OBJECT_KEY_V101)

    def test_corrupt_newest_fails_closed_without_fallback(self) -> None:
        good_v100 = self._synth_doc(
            object_key=self.Q2_OBJECT_KEY_V100,
            version="1.0.0",
        )
        bad_v101 = self._synth_doc(
            object_key=self.Q2_OBJECT_KEY_V101,
            version="1.0.1",
        )
        bad_v101["content_sha256"] = "0" * 64
        payloads = {
            self.Q2_OBJECT_KEY_V100: self._payload(good_v100),
            self.Q2_OBJECT_KEY_V101: self._payload(bad_v101),
        }
        listing = [
            {"key": self.Q2_OBJECT_KEY_V100, "size": len(payloads[self.Q2_OBJECT_KEY_V100])},
            {"key": self.Q2_OBJECT_KEY_V101, "size": len(payloads[self.Q2_OBJECT_KEY_V101])},
        ]

        class _Body:
            def __init__(self, data: bytes) -> None:
                self._data = data

            def read(self) -> bytes:
                return self._data

        client = MagicMock()

        def _get_object(**kwargs):
            key = kwargs.get("Key")
            return {"Body": _Body(payloads[key])}

        client.get_object.side_effect = _get_object
        config = CLI.rebuild_cli.B2Config.from_env(_b2_env())
        with self.assertRaises(CLI.AcceptanceContractConfigError) as ctx:
            CLI.resolve_and_verify_canonical_acceptance_contract(
                benchmark_id=REQUIRED_BENCHMARK,
                question_id="Q2",
                client=client,
                config=config,
                object_keys=listing,
            )
        self.assertIn("authentication failed", ctx.exception.message)
        # Newest key was attempted; must not silently return v1.0.0 pins.
        client.get_object.assert_called_once()
        self.assertEqual(
            client.get_object.call_args.kwargs.get("Key"),
            self.Q2_OBJECT_KEY_V101,
        )
        blob = ctx.exception.message + json.dumps(ctx.exception.details)
        self.assertNotIn("PRIVATE_CONTRACT_BODY_MUST_NOT_LEAK", blob)

    def test_normalized_benchmark_identity_in_resolution(self) -> None:
        import acceptance_contract as ac

        embedded = "case-00-triborough"
        self.assertEqual(
            ac.normalize_benchmark_id(REQUIRED_BENCHMARK),
            ac.normalize_benchmark_id(embedded),
        )
        doc = self._synth_doc(
            benchmark_id=embedded,
            object_key=self.Q2_OBJECT_KEY_V101,
            version="1.0.1",
        )
        payload = self._payload(doc)
        listing = [{"key": self.Q2_OBJECT_KEY_V101, "size": len(payload)}]
        client = MagicMock()

        class _Body:
            def read(self) -> bytes:
                return payload

        client.get_object.return_value = {"Body": _Body()}
        config = CLI.rebuild_cli.B2Config.from_env(_b2_env())
        result = CLI.resolve_and_verify_canonical_acceptance_contract(
            benchmark_id=REQUIRED_BENCHMARK,
            question_id="Q2",
            client=client,
            config=config,
            object_keys=listing,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["object_key"], self.Q2_OBJECT_KEY_V101)
        self.assertEqual(result["benchmark_id"], REQUIRED_BENCHMARK)
        self.assertEqual(result["content_sha256"], doc["content_sha256"])

    def test_missing_metadata_fails_closed(self) -> None:
        with self.assertRaises(CLI.AcceptanceContractConfigError) as ctx:
            CLI.resolve_canonical_acceptance_contract_spec(
                benchmark_id="",
                question_id="Q2",
                object_keys=[{"key": self.Q2_OBJECT_KEY_V101, "size": 2709}],
            )
        self.assertIn("benchmark_id", ctx.exception.details["missing"])

        with self.assertRaises(CLI.AcceptanceContractConfigError) as ctx:
            CLI.resolve_canonical_acceptance_contract_spec(
                benchmark_id=REQUIRED_BENCHMARK,
                question_id="",
                object_keys=[{"key": self.Q2_OBJECT_KEY_V101, "size": 2709}],
            )
        self.assertIn("question_id", ctx.exception.details["missing"])

        with self.assertRaises(CLI.AcceptanceContractConfigError) as ctx:
            CLI.resolve_canonical_acceptance_contract_spec(
                benchmark_id=REQUIRED_BENCHMARK,
                question_id="Q1",
                object_keys=[{"key": self.Q2_OBJECT_KEY_V101, "size": 2709}],
            )
        self.assertIn("no acceptance-contract version candidates", ctx.exception.message)
        self.assertEqual(ctx.exception.details.get("question_id"), "Q1")

    def test_verify_q2_success_returns_safe_pins(self) -> None:
        doc = self._synth_doc()
        payload = self._payload(doc)
        verified = CLI.verify_acceptance_contract_object_bytes(
            payload,
            object_key=self.Q2_OBJECT_KEY_V100,
            expected_size=len(payload),
            expected_benchmark_id=REQUIRED_BENCHMARK,
            expected_question_id="Q2",
            expected_version="v1.0.0",
        )
        self.assertEqual(verified["object_key"], self.Q2_OBJECT_KEY_V100)
        self.assertEqual(verified["benchmark_id"], REQUIRED_BENCHMARK)
        self.assertEqual(verified["question_id"], "Q2")
        self.assertEqual(verified["content_sha256"], doc["content_sha256"])
        self.assertEqual(verified["size"], len(payload))
        self.assertEqual(len(verified["object_sha256"]), 64)
        blob = json.dumps(verified, sort_keys=True)
        self.assertNotIn("PRIVATE_CONTRACT_BODY_MUST_NOT_LEAK", blob)
        self.assertNotIn("fallback_text", blob)
        self.assertNotIn("presence_phrases", blob)

    def test_hash_mismatch_fails_closed_and_redacts_body(self) -> None:
        doc = self._synth_doc()
        doc["content_sha256"] = "0" * 64
        payload = self._payload(doc)
        with self.assertRaises(CLI.AcceptanceContractConfigError) as ctx:
            CLI.verify_acceptance_contract_object_bytes(
                payload,
                object_key=self.Q2_OBJECT_KEY_V100,
                expected_size=len(payload),
                expected_benchmark_id=REQUIRED_BENCHMARK,
                expected_question_id="Q2",
            )
        self.assertIn("authentication failed", ctx.exception.message)
        self.assertEqual(
            ctx.exception.details.get("error_code"),
            "hash_mismatch",
        )
        blob = ctx.exception.message + json.dumps(ctx.exception.details)
        self.assertNotIn("PRIVATE_CONTRACT_BODY_MUST_NOT_LEAK", blob)
        self.assertNotIn("fallback_text", blob)

    def test_identity_mismatch_fails_closed_and_redacts_body(self) -> None:
        doc = self._synth_doc(question_id="Q2")
        payload = self._payload(doc)
        with self.assertRaises(CLI.AcceptanceContractConfigError) as ctx:
            CLI.verify_acceptance_contract_object_bytes(
                payload,
                object_key=self.Q2_OBJECT_KEY_V100,
                expected_size=len(payload),
                expected_benchmark_id=REQUIRED_BENCHMARK,
                expected_question_id="Q9",
            )
        self.assertIn("authentication failed", ctx.exception.message)
        self.assertEqual(
            ctx.exception.details.get("error_code"),
            "identity_mismatch",
        )
        blob = ctx.exception.message + json.dumps(ctx.exception.details)
        self.assertNotIn("PRIVATE_CONTRACT_BODY_MUST_NOT_LEAK", blob)

    def test_benchmark_id_case_equivalence_accepted_and_preserves_ids(self) -> None:
        """Display-case workflow ID matches lowercase embedded contract ID."""
        import acceptance_contract as ac

        embedded = "case-00-triborough"
        self.assertEqual(REQUIRED_BENCHMARK, "Case-00-Triborough")
        self.assertNotEqual(REQUIRED_BENCHMARK, embedded)
        self.assertEqual(
            ac.normalize_benchmark_id(REQUIRED_BENCHMARK),
            ac.normalize_benchmark_id(embedded),
        )

        doc = self._synth_doc(benchmark_id=embedded, question_id="Q2")
        raw = self._payload(doc)
        loaded = ac.load_acceptance_contract_from_bytes(
            raw,
            object_key=self.Q2_OBJECT_KEY_V100,
            expected_identity=ac.ContractIdentity(
                benchmark_id=REQUIRED_BENCHMARK,
                question_id="Q2",
            ),
            expected_content_sha256=doc["content_sha256"],
        )
        self.assertTrue(loaded.ok)
        assert loaded.metadata is not None
        # Archived/stored identity casing is preserved in metadata.
        self.assertEqual(loaded.metadata.benchmark_id, embedded)
        self.assertEqual(loaded.metadata.question_id, "Q2")

        verified = CLI.verify_acceptance_contract_object_bytes(
            raw,
            object_key=self.Q2_OBJECT_KEY_V100,
            expected_size=len(raw),
            expected_benchmark_id=REQUIRED_BENCHMARK,
            expected_question_id="Q2",
        )
        # Supplied workflow ID preserved in output pins.
        self.assertEqual(verified["benchmark_id"], REQUIRED_BENCHMARK)
        self.assertEqual(verified["question_id"], "Q2")
        self.assertEqual(verified["content_sha256"], doc["content_sha256"])
        blob = json.dumps(verified, sort_keys=True)
        self.assertNotIn("PRIVATE_CONTRACT_BODY_MUST_NOT_LEAK", blob)

    def test_different_benchmark_id_rejected_with_redaction(self) -> None:
        import acceptance_contract as ac

        doc = self._synth_doc(
            benchmark_id="case-00-triborough",
            question_id="Q2",
        )
        payload = self._payload(doc)
        other = "Case-00-Otherborough"
        self.assertNotEqual(
            ac.normalize_benchmark_id(other),
            ac.normalize_benchmark_id("case-00-triborough"),
        )
        loaded = ac.load_acceptance_contract_from_bytes(
            payload,
            object_key=self.Q2_OBJECT_KEY_V100,
            expected_identity=ac.ContractIdentity(
                benchmark_id=other,
                question_id="Q2",
            ),
        )
        self.assertFalse(loaded.ok)
        self.assertEqual(loaded.error_code, ac.ERROR_IDENTITY_MISMATCH)

        with self.assertRaises(CLI.AcceptanceContractConfigError) as ctx:
            CLI.verify_acceptance_contract_object_bytes(
                payload,
                object_key=self.Q2_OBJECT_KEY_V100,
                expected_size=len(payload),
                expected_benchmark_id=other,
                expected_question_id="Q2",
            )
        self.assertIn("authentication failed", ctx.exception.message)
        self.assertEqual(
            ctx.exception.details.get("error_code"),
            "identity_mismatch",
        )
        blob = ctx.exception.message + json.dumps(ctx.exception.details)
        self.assertNotIn("PRIVATE_CONTRACT_BODY_MUST_NOT_LEAK", blob)
        self.assertNotIn("fallback_text", blob)

    def test_size_mismatch_fails_closed(self) -> None:
        doc = self._synth_doc()
        payload = self._payload(doc)
        with self.assertRaises(CLI.AcceptanceContractConfigError) as ctx:
            CLI.verify_acceptance_contract_object_bytes(
                payload,
                object_key=self.Q2_OBJECT_KEY_V100,
                expected_size=len(payload) + 1,
                expected_benchmark_id=REQUIRED_BENCHMARK,
                expected_question_id="Q2",
            )
        self.assertIn("size mismatch", ctx.exception.message)
        self.assertEqual(ctx.exception.details.get("expected_size"), len(payload) + 1)
        self.assertEqual(ctx.exception.details.get("actual_size"), len(payload))

    def test_resolve_and_verify_downloads_highest_and_returns_pins(self) -> None:
        doc = self._synth_doc(
            object_key=self.Q2_OBJECT_KEY_V101,
            version="1.0.1",
        )
        payload = self._payload(doc)

        class _Body:
            def read(self) -> bytes:
                return payload

        client = MagicMock()
        client.get_object.return_value = {"Body": _Body()}
        config = CLI.rebuild_cli.B2Config.from_env(_b2_env())
        listing = [
            {"key": self.Q2_OBJECT_KEY_V100, "size": 3463},
            {"key": self.Q2_OBJECT_KEY_V101, "size": len(payload)},
        ]
        result = CLI.resolve_and_verify_canonical_acceptance_contract(
            benchmark_id=REQUIRED_BENCHMARK,
            question_id="Q2",
            client=client,
            config=config,
            object_keys=listing,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["object_key"], self.Q2_OBJECT_KEY_V101)
        self.assertEqual(result["content_sha256"], doc["content_sha256"])
        self.assertEqual(result["benchmark_id"], REQUIRED_BENCHMARK)
        self.assertEqual(result["question_id"], "Q2")
        self.assertEqual(result["size"], len(payload))
        client.get_object.assert_called_once()
        call_kwargs = client.get_object.call_args.kwargs
        self.assertEqual(call_kwargs.get("Key"), self.Q2_OBJECT_KEY_V101)
        status = json.dumps(result, sort_keys=True)
        self.assertNotIn("PRIVATE_CONTRACT_BODY_MUST_NOT_LEAK", status)

    def test_production_resolver_error_wording_is_not_q1_only(self) -> None:
        with self.assertRaises(CLI.AcceptanceContractConfigError) as ctx:
            CLI.resolve_production_acceptance_contract(
                question_id="Q2",
                environ={},
            )
        self.assertIn("Case-00", ctx.exception.message)
        self.assertNotIn("production Q1 requires", ctx.exception.message)

    def test_q1_explicit_pins_remain_compatible(self) -> None:
        resolved = CLI.resolve_production_acceptance_contract(
            question_id="Q1",
            environ=_acceptance_env(),
        )
        self.assertEqual(resolved["question_id"], "Q1")
        self.assertTrue(resolved["object_key"])
        self.assertTrue(resolved["content_sha256"])
        self.assertTrue(resolved["benchmark_id"])


if __name__ == "__main__":
    unittest.main()
