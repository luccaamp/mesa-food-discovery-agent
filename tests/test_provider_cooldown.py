"""Deterministic outage tests; no live provider calls."""
from io import BytesIO
import unittest
from unittest.mock import patch
from urllib.request import Request

from meal_discovery.llm import ProviderUnavailable
from meal_discovery.llm.resilience import RetryPolicy, send
from meal_discovery.cloud_limits import CallBudget, ProviderCooldown


class CooldownTests(unittest.TestCase):
    def test_old_inflight_requests_cannot_release_a_new_recovery_probe(self):
        now = [0.0]
        state = ProviderCooldown(clock=lambda: now[0])
        for _ in range(3):
            self.assertTrue(state.acquire())
        state.record("failure")
        state.record("failure")
        now[0] = 60
        self.assertFalse(state.acquire())
        state.record("neutral")
        self.assertTrue(state.acquire())
        self.assertFalse(state.acquire())
        state.record("success")
        self.assertTrue(state.acquire())

    def test_outage_pauses_then_allows_exactly_one_probe(self):
        now = [0.0]
        state = ProviderCooldown(clock=lambda: now[0])
        for _ in range(2):
            self.assertTrue(state.acquire())
            state.record("failure")
        self.assertFalse(state.acquire())
        self.assertEqual(state.snapshot()["retry_after_seconds"], 60)
        now[0] = 60
        self.assertTrue(state.acquire())
        self.assertFalse(state.acquire())
        state.record("failure")
        self.assertFalse(state.acquire())
        now[0] = 120
        self.assertTrue(state.acquire())
        state.record("success")
        self.assertEqual(state.snapshot()["consecutive_failures"], 0)
        self.assertTrue(state.acquire())

    def test_blocked_call_does_not_spend_quota_or_contact_provider(self):
        state, budget = ProviderCooldown(), CallBudget()
        request = Request("https://example.invalid", data=b"{}")
        with patch.dict("meal_discovery.llm.resilience.COOLDOWNS", {"gemini": state}), patch.dict("meal_discovery.llm.resilience.BUDGETS", {"gemini": budget}), patch(
                "meal_discovery.llm.resilience.urlopen", side_effect=TimeoutError()) as transport, patch(
                "meal_discovery.llm.resilience.sleep"):
            for _ in range(2):
                with self.assertRaises(ProviderUnavailable) as error:
                    send("gemini", request, RetryPolicy(per_minute=10, per_day=20))
                self.assertEqual(error.exception.attempts, 2)
            with self.assertRaises(ProviderUnavailable) as error:
                send("gemini", request, RetryPolicy(per_minute=10, per_day=20))
            self.assertEqual(error.exception.reason, "provider_cooldown")
            self.assertEqual(error.exception.attempts, 0)
            self.assertEqual(transport.call_count, 4)
            self.assertEqual(budget.day_calls, 4)

    def test_success_breaks_failure_streak_and_quota_denial_is_neutral(self):
        state = ProviderCooldown()
        state.record("failure")
        with patch.dict("meal_discovery.llm.resilience.COOLDOWNS", {"gemini": state}), patch.dict("meal_discovery.llm.resilience.BUDGETS", {"gemini": CallBudget()}), patch(
                "meal_discovery.llm.resilience.urlopen", return_value=BytesIO(b"{}")):
            send("gemini", Request("https://example.invalid"), RetryPolicy(per_minute=1, per_day=1))
            with self.assertRaises(ProviderUnavailable):
                send("gemini", Request("https://example.invalid"), RetryPolicy(per_minute=1, per_day=1))
        self.assertEqual(state.snapshot()["consecutive_failures"], 0)
        self.assertFalse(state.snapshot()["paused"])


if __name__ == "__main__":
    unittest.main()
