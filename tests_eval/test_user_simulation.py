import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evaluations"))
from inspect_user_simulation import validate_messages
from summarize_ai_pipeline import summarize


class SimulatorAdherenceTests(unittest.TestCase):
    def test_published_ai_counts_are_reconstructed_from_recorded_runs(self):
        root = Path(__file__).resolve().parents[1] / "evaluations/results"
        expected = json.loads((root / "ai-pipeline-summary-v1.json").read_text(encoding="utf-8"))
        self.assertEqual(summarize(root), expected)

    def test_dish_changes_extra_ingredients_and_negation_are_rejected(self):
        case = {"profile": "direct", "turns": [{"tool": "search_catalog", "concepts": [["chicken"], ["rice"]]}]}
        self.assertEqual(validate_messages(case, json.dumps({"messages": ["Gostaria de arroz com frango, por favor"]})),
                         ["Gostaria de arroz com frango, por favor"])
        for message in ("Quero pizza", "Quero arroz com frango e queijo", "Quero arroz sem frango"):
            with self.assertRaises(ValueError):
                validate_messages(case, json.dumps({"messages": [message]}))

    def test_price_changes_and_turn_count_drift_are_rejected(self):
        case = {"profile": "budget", "turns": [{"tool": "search_catalog", "preserve_query": True,
                                                 "context_equals": {"max_price": 2}}]}
        validate_messages(case, json.dumps({"messages": ["até 2 unidades normalizadas"]}))
        for messages in (["até 3 unidades normalizadas"], [], ["até 2 unidades normalizadas", "mais algo"]):
            with self.assertRaises(ValueError):
                validate_messages(case, json.dumps({"messages": messages}))

    def test_recommendation_does_not_turn_into_search(self):
        case = {"profile": "seed_selection", "turns": [{"tool": "recommend_items"}]}
        validate_messages(case, json.dumps({"messages": ["Sugira opções"]}))
        with self.assertRaises(ValueError):
            validate_messages(case, json.dumps({"messages": ["Recomende pizza"]}))


if __name__ == "__main__":
    unittest.main()
