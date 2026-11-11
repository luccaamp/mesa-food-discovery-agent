from types import SimpleNamespace
import unittest
from meal_discovery.api_models import AssistantRequest
from meal_discovery.assistant import run_assistant
from meal_discovery.discovery import guarded_constraint


class DietaryLanguageTests(unittest.TestCase):
    def test_english_and_portuguese_safety_requests_never_reach_planner(self):
        def forbidden(*args, **kwargs):
            raise AssertionError("Dietary guarantee must not reach inference or catalog search")
        planner=SimpleNamespace(provider="gemini",model="fixture",plan=forbidden)
        reader=SimpleNamespace(search=forbidden)
        for query in ("safe for egg allergy", "guaranteed gluten-free noodles",
                      "safe for coeliac disease", "dairy free dessert", "no peanuts",
                      "seguro para alergia a ovo", "seguro para celíacos"):
            with self.subTest(query=query):
                result=run_assistant(AssistantRequest(message=query),reader,forbidden,planner=planner)
                self.assertEqual(result["status"],"needs_clarification")
                self.assertEqual(result["planner"],"policy")
                self.assertEqual(result["items"],[])
                self.assertEqual(result["usage"],{})

    def test_ordinary_food_names_remain_searchable(self):
        for query in ("egg sandwich","peanut butter","milk tea","Nutella pancake","macarrão com queijo"):
            self.assertIsNone(guarded_constraint(query),query)


if __name__=="__main__":
    unittest.main()
