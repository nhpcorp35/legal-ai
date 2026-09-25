"""Guard the release controller\'s test-before-deploy contract."""

from pathlib import Path
import unittest


class ReleaseControllerContractTests(unittest.TestCase):
    def test_release_controller_requires_tests_before_deploy(self):
        workflow = (
            Path(__file__).parent
            / ".github"
            / "workflows"
            / "legalai-release-controller.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("python -m py_compile app.py scripts/run_verified_case_draft.py scripts/run_cross_case_retrieval_regression.py", workflow)
        self.assertIn("python -m unittest -v test_release_controller_contract test_release_smoke test_motion_answer_contract test_retrieval_audit_visibility test_pre_generation_gate test_cross_case_retrieval_regression", workflow)
        self.assertIn("needs: test", workflow)
        self.assertIn(
            "railway up --detach --project \"$RAILWAY_PROJECT_ID\" --environment production --service legal-ai-executor",
            workflow,
        )
        self.assertIn(
            "railway up --detach --project \"$RAILWAY_PROJECT_ID\" --environment production --service internal-draft-worker",
            workflow,
        )
        self.assertIn("group: legalai-production-release", workflow)
        self.assertIn("PUSHOVER_APP_TOKEN: ${{ secrets.PUSHOVER_APP_TOKEN }}", workflow)
        self.assertIn("PUSHOVER_USER_KEY: ${{ secrets.PUSHOVER_USER_KEY }}", workflow)
        self.assertIn("Replay Rennick verified-record retrieval without a model", workflow)
        self.assertIn("railway run --no-local --project \"$RAILWAY_PROJECT_ID\" --environment \"$RAILWAY_ENVIRONMENT_ID\" --service legal-ai-executor", workflow)
        self.assertIn("RENNICK_RETRIEVAL_PREFLIGHT_VERIFIED", workflow)
        self.assertIn("run_cross_case_retrieval_regression.py", workflow)
        self.assertIn('"model_called": False', workflow)
        self.assertIn('"b2_write": False', workflow)


if __name__ == "__main__":
    unittest.main()
