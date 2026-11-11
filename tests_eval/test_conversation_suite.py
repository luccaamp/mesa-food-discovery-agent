"""Mutation tests: broken facts/filters/state must fail the objective scorer."""
from copy import deepcopy
import sys
import json
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evaluations"))
from conversation_suite import endpoint, reliability, validate_suite, verify_turn
from summarize_conversations import summarize
from summarize_public_acceptance import summarize as summarize_public


class ConversationOracleTests(unittest.TestCase):
    def setUp(self):
        # Explicit unit-only synthetic fixture. Never product or inference evidence.
        self.item = {"vendor_id": "test-v", "product_id": "test-p", "name": "TEST rice",
                     "unit_price": 1.0, "primary_cuisine": "TEST cuisine"}
        self.turn = {"message": "test", "tool": "search_catalog", "concepts": [["rice"]]}
        self.result = {"status": "ok", "items": [dict(self.item)],
                       "context": {"last_query": "rice", "max_price": 2},
                       "warnings": ["Catálogo histórico. Preços normalizados."],
                       "tools": [{"name": "search_catalog", "arguments": {"query": "rice"}}]}

    def check(self, result=None, turn=None, previous=None):
        return verify_turn(turn or self.turn, result or self.result, previous or {}, lambda *_: self.item)

    def test_source_fact_corruptions_cannot_pass(self):
        self.assertEqual(self.check(), [])
        for field, corrupt in (("name", "invented"), ("unit_price", 10), ("primary_cuisine", "wrong")):
            value = deepcopy(self.result)
            value["items"][0][field] = corrupt
            self.assertIn("catalog_identity_and_fields", self.check(value))

    def test_bounds_identity_and_context_are_independent_checks(self):
        value = deepcopy(self.result)
        value["context"]["max_price"] = 0.5
        self.assertIn("max_price", self.check(value))
        value["items"].append(dict(self.item))
        self.assertIn("duplicate_item", self.check(value))
        turn = {**self.turn, "preserve_query": True, "context_equals": {"max_price": 1}}
        self.assertIn("query_continuity", self.check(turn=turn, previous={"last_query": "tea"}))
        self.assertIn("context_max_price", self.check(turn=turn))

    def test_wrong_tool_or_stale_intent_cannot_pass(self):
        turn = {**self.turn, "concepts": [["tea"]], "excluded_query_terms": ["rice"]}
        self.assertIn("dish_intent", self.check(turn=turn))
        self.assertIn("stale_intent", self.check(turn=turn))
        self.assertIn("expected_tool", self.check(turn={**self.turn, "tool": None}))

    def test_seed_exclusion_and_missing_recommendation_evidence_fail(self):
        value = deepcopy(self.result)
        value["tools"][0]["name"] = "recommend_items"
        errors = self.check(value, {"tool": "recommend_items"}, {"selected_items": [self.item]})
        self.assertIn("seed_exclusion", errors)
        self.assertIn("recommendation_evidence", errors)
        self.assertIn("training_evidence", errors)

    def test_pass_power_k_requires_all_k_not_any_success(self):
        rows = [{"id": "a", "passed": passed} for passed in [True, True, False]]
        self.assertEqual(reliability(rows, 3), 0)
        self.assertAlmostEqual(reliability(rows, 1), 2 / 3)
        self.assertAlmostEqual(reliability(rows, 2), 1 / 3)
        self.assertIsNone(reliability(rows[:1], 3))

    def test_protocol_validation_and_no_remote_execution(self):
        for url in ("https://example.org", "http://key@localhost:8000", "http://localhost:8000/api"):
            with self.assertRaises(ValueError):
                endpoint(url)
        self.assertEqual(endpoint("http://localhost:8000/"), "http://localhost:8000")
        with self.assertRaises(ValueError):
            validate_suite({"cases": [{"id": "bad", "turns": [dict(self.turn, concepts=[])]}]})

    def test_published_summary_reconstructs_from_real_recorded_evidence(self):
        root = Path(__file__).resolve().parents[1] / "evaluations/results"
        actual = summarize(root / "conversation-development-v2.json", root / "conversation-development-v1.json")
        published = json.loads((root / "conversation-development-summary-v1.json").read_text(encoding="utf-8"))
        self.assertEqual(actual, published)
        latest = summarize(root / "conversation-development-v3.json", root / "conversation-development-v1.json")
        self.assertEqual(latest, json.loads((root / "conversation-development-summary-v2.json").read_text(encoding="utf-8")))

    def test_public_summary_reconstructs_real_inferences_without_counting_policy_as_ai(self):
        root = Path(__file__).resolve().parents[1] / "evaluations/results"
        result = summarize_public(root / "public-assistant-acceptance-v1.json")
        self.assertEqual(result, json.loads((root / "public-assistant-summary-v1.json").read_text(encoding="utf-8")))
        self.assertEqual(result["gemini_inferences_completed"], 3)
        self.assertEqual(result["total"], 6)


if __name__ == "__main__":
    unittest.main()
