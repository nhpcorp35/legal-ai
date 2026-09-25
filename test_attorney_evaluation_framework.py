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

    def test_framework_component_renders_without_generating_an_answer(self):
        with legalai.app.app_context():
            page = legalai.rennick_evaluation_set_html()
        self.assertIn("No-answer framework", page)
        self.assertIn("calls no model", page)
        self.assertIn("What does the NYSDEC permit or correspondence prove", page)


if __name__ == "__main__":
    unittest.main()
