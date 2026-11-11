"""Personal data never reaches the language model."""

import unittest

from meal_discovery.agent import run_agent
from meal_discovery.api_models import AssistantRequest
from meal_discovery.assistant import run_assistant
from meal_discovery.privacy import redact
from test_agent import Catalog, ScriptedModel, call, recommender, text


class RedactionTests(unittest.TestCase):
    def test_identifiers_are_masked(self):
        cases = {
            "me liga no (11) 98765-4321": "[telefone]",
            "meu email é ana.souza+mesa@gmail.com": "[email]",
            "cpf 123.456.789-09": "[cpf]",
            "cartão 4111 1111 1111 1111": "[cartão]",
            "whatsapp +55 11 91234 5678": "[telefone]",
        }
        for message, label in cases.items():
            with self.subTest(message=message):
                masked, kinds = redact(message)
                self.assertIn(label, masked)
                self.assertEqual(kinds, [label.strip("[]")])

    def test_food_requests_and_prices_are_untouched(self):
        for message in ("quero arroz com frango até 0,005", "2 pizzas e 1 chá", "combo 3 por 0.0045", "laksa 2024"):
            with self.subTest(message=message):
                self.assertEqual(redact(message), (message, []))

    def test_agent_never_sends_personal_data_and_warns(self):
        model = ScriptedModel(call("search_catalog", query="chicken rice"), text("Encontrei opções."))
        request = AssistantRequest(message="arroz com frango, meu zap é 11 98765-4321")
        result = run_agent(request, Catalog(), recommender, chat_model=model)
        sent = " ".join(message["content"] or "" for message in model.calls[0]["messages"])
        self.assertNotIn("98765", sent)
        self.assertIn("[telefone]", sent)
        self.assertTrue(any("dados pessoais" in warning for warning in result["warnings"]))

    def test_planner_mode_masks_before_planning(self):
        seen = []

        class Planner:
            provider, model = "groq", "fixture"

            def plan(self, message, context):
                seen.append(message)
                from meal_discovery.api_models import IntentPlan
                return IntentPlan(action="clarify", query=None), {}

        result = run_assistant(AssistantRequest(message="contato ana@x.com"), Catalog(), recommender, planner=Planner())
        self.assertEqual(seen, ["contato [email]"])
        self.assertTrue(any("dados pessoais" in warning for warning in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
