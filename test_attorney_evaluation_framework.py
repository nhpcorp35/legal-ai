import unittest
from unittest.mock import patch

import app as legalai


CANONICAL_ID = "NY-Nassau-613561-2026-Desousa-v-Rennick"


class AttorneyEvaluationFrameworkTests(unittest.TestCase):
    def test_framework_has_twenty_five_record_centered_prompts(self):
        framework = legalai.RENNICK_ATTORNEY_EVALUATION_FRAMEWORK
        self.assertEqual(len(framework), 25)
        self.assertEqual(
            {category for category, _label, _prompt in framework},
            {"record", "evidence", "law", "strategy", "quality"},
        )
        self.assertTrue(all(isinstance(prompt, str) and prompt for _category, _label, prompt in framework))

    def test_framework_is_rendered_without_generating_an_answer(self):
        with patch.object(legalai, "basic_review_user", return_value="john"), patch.object(
            legalai,
            "load_exact_draft_request",
            return_value=None,
        ):
            response = legalai.app.test_client().get(
                f"/workspace/matters/{CANONICAL_ID}/review-packet"
            )
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("No-answer framework", page)
        self.assertIn("calls no model", page)
        self.assertIn("What does the NYSDEC permit or correspondence prove", page)


if __name__ == "__main__":
    unittest.main()
