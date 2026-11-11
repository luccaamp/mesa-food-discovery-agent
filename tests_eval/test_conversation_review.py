"""Advisory grader parser and non-scoring policy contracts."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evaluations"))
from inspect_conversation_review import advisory_review, parse_review, review_input


class AdvisoryReviewTests(unittest.TestCase):
    def test_review_includes_task_and_initial_context_but_hides_model_and_oracle(self):
        # Explicit unit fixture; no inference evidence is created here.
        row = {"turns": [{"message": "até 0", "response": {"answer": "test", "items": [],
                "warnings": [], "planner": "hidden-model", "usage": {"total_tokens": 99}}, "errors": ["hidden-oracle"]}]}
        case = {"context": {"last_query": "chicken rice"}, "turns": [{"tool": "search_catalog", "context_equals": {"max_price": 0}}]}
        payload = review_input(row, case)
        self.assertEqual(payload["initial_context"]["last_query"], "chicken rice")
        self.assertEqual(payload["task_contract"][0]["context_equals"], {"max_price": 0})
        self.assertNotIn("hidden-model", json.dumps(payload))
        self.assertNotIn("hidden-oracle", json.dumps(payload))
    def test_rubric_rejects_missing_out_of_range_and_boolean_scores(self):
        value = {"goal_completion": 2, "clarity": 3, "evidence_alignment": 3, "reason": "Unit-test reason"}
        self.assertEqual(parse_review(json.dumps(value)), value)
        for bad in ({**value, "clarity": True}, {**value, "clarity": 4}, {**value, "reason": ""},
                    {**value, "clarity": "3"}, {**value, "extra": 1}):
            with self.assertRaises(ValueError):
                parse_review(json.dumps(bad))

    def test_invalid_verdict_remains_unscored_instead_of_zero_or_pass(self):
        state = SimpleNamespace(output=SimpleNamespace(completion="{}"))
        score = asyncio.run(advisory_review()(state, None))
        self.assertFalse(score.metadata["valid"])
        self.assertEqual(score.reason, "invalid_response_format")


if __name__ == "__main__":
    unittest.main()
