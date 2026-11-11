import unittest
from types import SimpleNamespace
from meal_discovery.api_models import AssistantRequest, AssistantResponse
from meal_discovery.assistant import PlannerUnavailable, run_assistant


class FallbackStatusTests(unittest.TestCase):
    def test_reason_is_sanitized_and_survives_response_validation(self):
        reader = SimpleNamespace(search=lambda params: {"items": [], "total_matches": 0})
        for reason, expected in [
            ("provider_timeout", "provider_timeout"), ("provider_cooldown", "provider_cooldown"),
            ("provider_http_429", "quota"), ("local_quota", "quota"),
            ("invalid_response", "invalid_response"), ("https://private.invalid?key=secret", "provider_unavailable"),
        ]:
            class Planner:
                provider = "gemini"
                model = "fixture"
                def plan(self, *args):
                    raise PlannerUnavailable(reason)
            with self.subTest(reason=reason):
                result = run_assistant(AssistantRequest(message="pizza"), reader, lambda args: {}, planner=Planner())
                parsed = AssistantResponse.model_validate(result)
                self.assertEqual(parsed.fallback_reason, expected)
                self.assertNotIn("secret", parsed.model_dump_json())
                self.assertEqual(parsed.planner, "glossary_fallback")
                if reason == "provider_cooldown":
                    self.assertGreaterEqual(parsed.retry_after_seconds, 0)


if __name__ == "__main__":
    unittest.main()
