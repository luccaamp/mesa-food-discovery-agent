"""Transport mocks test contracts, not live Gemini availability or quality."""

import asyncio
from io import BytesIO
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError

from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from meal_discovery.api_models import AssistantContext, AssistantRequest
from meal_discovery.assistant import HttpPlanner, PlannerUnavailable, retry_delay, run_assistant
from meal_discovery.cloud_limits import CallBudget, ProviderCooldown, PublicDemoGuard


class GeminiTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"LLM_PROVIDER": "gemini", "LLM_MODEL": "gemini-2.5-flash-lite",
            "GEMINI_API_KEY": "test-only-not-a-secret", "GEMINI_CALLS_PER_MINUTE": "4", "GEMINI_CALLS_PER_DAY": "20"})
        environment.start()
        self.addCleanup(environment.stop)
        budget = patch("meal_discovery.assistant.GEMINI_BUDGET", CallBudget())
        budget.start()
        self.addCleanup(budget.stop)
        cooldown = patch("meal_discovery.assistant.GEMINI_COOLDOWN", ProviderCooldown())
        cooldown.start()
        self.addCleanup(cooldown.stop)

    def result(self, **candidate):
        return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": '{"action":"search_catalog","query":"chicken rice"}'}]}, **candidate}],
                "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 8, "totalTokenCount": 20}}

    def test_key_in_header_bounded_schema_and_usage(self):
        with patch("meal_discovery.assistant.urlopen", return_value=BytesIO(json.dumps(self.result()).encode())) as transport:
            plan, usage = HttpPlanner().plan("arroz com frango", AssistantContext())
        self.assertEqual(plan.query, "chicken rice")
        self.assertEqual(usage["total_tokens"], 20)
        request = transport.call_args.args[0]
        self.assertNotIn("test-only", request.full_url)
        self.assertEqual(request.get_header("X-goog-api-key"), "test-only-not-a-secret")
        payload = json.loads(request.data)
        config = payload["generationConfig"]
        self.assertEqual(config["thinkingConfig"], {"thinkingBudget": 0})
        self.assertEqual(config["responseMimeType"], "application/json")
        self.assertFalse(config["responseJsonSchema"]["additionalProperties"])
        self.assertNotIn("selected_items", request.data.decode())

    def test_incomplete_invalid_and_blocked_responses_fail_closed(self):
        for result in (self.result(finishReason="MAX_TOKENS"), self.result(finishReason="SAFETY"),
                       {"candidates": []}, {"candidates": None}, self.result(content={"parts": [{"text": "invalid"}]})):
            with self.subTest(result=result), patch("meal_discovery.assistant.urlopen", return_value=BytesIO(json.dumps(result).encode())):
                with self.assertRaises(PlannerUnavailable):
                    HttpPlanner().plan("pizza", AssistantContext())

    def test_current_lite_model_does_not_receive_legacy_thinking_budget(self):
        with patch.dict(os.environ, {"LLM_MODEL": "gemini-3.1-flash-lite"}), patch("meal_discovery.assistant.urlopen", return_value=BytesIO(json.dumps(self.result()).encode())) as transport:
            plan, usage = HttpPlanner().plan("pizza", AssistantContext())
        request = transport.call_args.args[0]
        self.assertIn("gemini-3.1-flash-lite:generateContent", request.full_url)
        self.assertEqual(json.loads(request.data)["generationConfig"]["thinkingConfig"], {"thinkingLevel": "minimal"})
        self.assertEqual(plan.action, "search_catalog")
        self.assertEqual(usage["total_tokens"], 20)

    def test_provider_429_is_sanitized_and_no_secret_in_error(self):
        error = HTTPError("https://example.invalid", 429, "quota", {}, None)
        with patch("meal_discovery.assistant.urlopen", side_effect=error):
            with self.assertRaises(PlannerUnavailable) as raised:
                HttpPlanner().plan("pizza", AssistantContext())
        self.assertNotIn("test-only", str(raised.exception))
        self.assertEqual(raised.exception.reason, "provider_http_429")

    def test_transient_503_recovers_once_and_counts_both_attempts(self):
        error = HTTPError("https://example.invalid", 503, "unavailable", {}, None)
        response = BytesIO(json.dumps(self.result()).encode())
        with patch("meal_discovery.assistant.urlopen", side_effect=[error, response]) as transport, patch("meal_discovery.assistant.sleep") as pause:
            plan, usage = HttpPlanner().plan("arroz com frango", AssistantContext())
        self.assertEqual(plan.query, "chicken rice")
        self.assertEqual(transport.call_count, 2)
        self.assertEqual(usage["provider_attempts"], 2)
        self.assertEqual(usage["failed_attempts_usage_unknown"], 1)
        self.assertEqual(usage["total_tokens"], 20)  # Successful response only, not an invoice.
        pause.assert_called_once_with(1)

    def test_repeated_transient_error_stops_at_two_attempts(self):
        with patch("meal_discovery.assistant.urlopen", side_effect=HTTPError("https://example.invalid", 503, "unavailable", {}, None)) as transport, patch("meal_discovery.assistant.sleep"):
            with self.assertRaises(PlannerUnavailable) as raised:
                HttpPlanner().plan("pizza", AssistantContext())
        self.assertEqual(raised.exception.reason, "provider_http_503")
        self.assertEqual(raised.exception.attempts, 2)
        self.assertEqual(transport.call_count, 2)

    def test_retry_cannot_bypass_daily_budget(self):
        with patch.dict(os.environ, {"GEMINI_CALLS_PER_DAY": "1"}), patch("meal_discovery.assistant.urlopen", side_effect=HTTPError("https://example.invalid", 503, "unavailable", {}, None)) as transport, patch("meal_discovery.assistant.sleep"):
            with self.assertRaises(PlannerUnavailable) as raised:
                HttpPlanner().plan("pizza", AssistantContext())
        self.assertEqual(raised.exception.reason, "local_quota")
        self.assertEqual(raised.exception.attempts, 1)
        self.assertEqual(transport.call_count, 1)

    def test_quota_and_auth_failures_never_retry(self):
        for code in (400, 401, 403, 404, 429):
            with self.subTest(code=code), patch("meal_discovery.assistant.GEMINI_BUDGET", CallBudget()), patch("meal_discovery.assistant.urlopen", side_effect=HTTPError("https://example.invalid", code, "private body", {"Retry-After": "1"}, None)) as transport, patch("meal_discovery.assistant.sleep") as pause:
                with self.assertRaises(PlannerUnavailable) as raised:
                    HttpPlanner().plan("pizza", AssistantContext())
                self.assertEqual(raised.exception.attempts, 1)
                self.assertEqual(transport.call_count, 1)
                pause.assert_not_called()

    def test_retry_after_beyond_total_deadline_is_not_shortened(self):
        for header in ("120", "9" * 5000):
            with self.subTest(header=header[:10]), patch("meal_discovery.assistant.urlopen", side_effect=HTTPError("https://example.invalid", 503, "unavailable", {"Retry-After": header}, None)) as transport, patch("meal_discovery.assistant.sleep") as pause:
                with self.assertRaises(PlannerUnavailable):
                    HttpPlanner().plan("pizza", AssistantContext())
                self.assertEqual(transport.call_count, 1)
                pause.assert_not_called()

    def test_repeated_timeout_is_distinguished_and_bounded(self):
        from urllib.error import URLError
        with patch("meal_discovery.assistant.urlopen", side_effect=URLError(TimeoutError("private details"))) as transport, patch("meal_discovery.assistant.sleep"):
            with self.assertRaises(PlannerUnavailable) as raised:
                HttpPlanner().plan("pizza", AssistantContext())
        self.assertEqual(raised.exception.reason, "provider_timeout")
        self.assertEqual(raised.exception.attempts, 2)
        self.assertEqual(transport.call_count, 2)

    def test_timeout_recovers_and_preserves_unknown_usage(self):
        response = BytesIO(json.dumps(self.result()).encode())
        with patch("meal_discovery.assistant.urlopen", side_effect=[TimeoutError(), response]) as transport, patch("meal_discovery.assistant.sleep"):
            plan, usage = HttpPlanner().plan("pizza", AssistantContext())
        self.assertEqual(plan.action, "search_catalog")
        self.assertEqual(usage["provider_attempts"], 2)
        self.assertEqual(usage["failed_attempts_usage_unknown"], 1)
        self.assertEqual(transport.call_count, 2)

    def test_timeout_with_insufficient_remaining_budget_stops(self):
        now = [0.0]
        def stalled(*args, **kwargs):
            now[0] = 25.0
            raise TimeoutError()
        with patch("meal_discovery.assistant.monotonic", side_effect=lambda: now[0]), patch("meal_discovery.assistant.urlopen", side_effect=stalled) as transport:
            with self.assertRaises(PlannerUnavailable) as raised:
                HttpPlanner().plan("pizza", AssistantContext())
        self.assertEqual(raised.exception.attempts, 1)
        self.assertEqual(transport.call_count, 1)

    def test_retry_honors_date_header_and_remaining_time(self):
        with patch("meal_discovery.assistant.time", return_value=0):
            self.assertEqual(retry_delay({"Retry-After": "Thu, 01 Jan 1970 00:00:05 GMT"}), 5)
        now = [0.0]
        def first_failure(*args, **kwargs):
            now[0] = 44.5  # Almost all of the total request budget has elapsed.
            raise HTTPError("https://example.invalid", 503, "unavailable", {}, None)
        with patch("meal_discovery.assistant.monotonic", side_effect=lambda: now[0]), patch("meal_discovery.assistant.urlopen", side_effect=first_failure) as transport, patch("meal_discovery.assistant.sleep") as pause:
            with self.assertRaises(PlannerUnavailable):
                HttpPlanner().plan("pizza", AssistantContext())
        self.assertEqual(transport.call_count, 1)
        pause.assert_not_called()

    def test_fallback_logs_only_sanitized_failure_code(self):
        error = HTTPError("https://example.invalid?secret=test-only-not-a-secret", 404, "sensitive provider detail", {}, None)
        reader = SimpleNamespace(search=lambda params: {"items": [], "total_matches": 0})
        with patch("meal_discovery.assistant.urlopen", side_effect=error), self.assertLogs("meal_discovery.assistant", level="WARNING") as logs:
            result = run_assistant(AssistantRequest(message="pizza"), reader, lambda args: {})
        self.assertEqual(result["planner"], "glossary_fallback")
        self.assertIn("provider_http_404", " ".join(logs.output))
        self.assertNotIn("test-only", " ".join(logs.output))
        self.assertNotIn("https://", " ".join(logs.output))
        self.assertNotIn("sensitive provider detail", " ".join(logs.output))

    def test_missing_key_invalid_model_and_exhausted_budget_never_send(self):
        with patch("meal_discovery.assistant.urlopen") as transport:
            for values in ({"GEMINI_API_KEY": ""}, {"LLM_MODEL": "../../invalid"}, {"GEMINI_CALLS_PER_DAY": "0"}):
                with patch.dict(os.environ, values), self.assertRaises(PlannerUnavailable):
                    HttpPlanner().plan("pizza", AssistantContext())
            transport.assert_not_called()
        with patch.dict(os.environ, {"GEMINI_CALLS_PER_DAY": "1"}), patch("meal_discovery.assistant.urlopen", return_value=BytesIO(json.dumps(self.result()).encode())) as transport:
            HttpPlanner().plan("pizza", AssistantContext())
            with self.assertRaises(PlannerUnavailable) as raised:
                HttpPlanner().plan("pizza", AssistantContext())
            self.assertEqual(raised.exception.reason, "local_quota")
            self.assertEqual(transport.call_count, 1)


class LocalSchemaTests(unittest.TestCase):
    def test_local_schema_uses_wrapper_understood_by_pinned_runtime(self):
        response = {"choices": [{"message": {"content": '{"action":"clarify","query":null}'}}]}
        with patch.dict(os.environ, {"LLM_PROVIDER": "local", "LLM_MODEL": "meal-local"}), patch(
                "meal_discovery.assistant.urlopen", return_value=BytesIO(json.dumps(response).encode())) as transport:
            HttpPlanner().plan("oi", AssistantContext())
        payload = json.loads(transport.call_args.args[0].data)
        schema = payload["response_format"]["json_schema"]["schema"]
        self.assertEqual(schema["properties"]["action"]["enum"], ["search_catalog", "recommend_items", "clarify"])
        self.assertFalse(schema["additionalProperties"])


class AdmissionTests(unittest.TestCase):
    def test_budget_rolls_minute_and_utc_day(self):
        now, day = [100.0], [86400.0]
        budget = CallBudget(clock=lambda: now[0], wall_clock=lambda: day[0])
        self.assertTrue(budget.take(1, 2))
        self.assertFalse(budget.take(1, 2))
        now[0] += 60
        self.assertTrue(budget.take(1, 2))
        now[0] += 60
        self.assertFalse(budget.take(1, 2))
        day[0] += 86400
        self.assertTrue(budget.take(1, 2))

    def test_large_bodies_and_rate_exhaustion_reject_before_domain(self):
        calls = []

        async def endpoint(request):
            calls.append(await request.body())
            return JSONResponse({"ok": True})

        app = Starlette(routes=[Route("/v1/assistant", endpoint, methods=["POST"])])
        app.add_middleware(PublicDemoGuard, enabled=True, body_bytes=16, requests_per_minute=2)
        with TestClient(app) as client:
            self.assertEqual(client.post("/v1/assistant", content=b"x" * 17).status_code, 413)
            self.assertEqual(client.post("/v1/assistant", content=b"hello").status_code, 200)
            rejected = client.post("/v1/assistant", content=b"hello")
            self.assertEqual(rejected.status_code, 429)
            self.assertEqual(rejected.headers["Retry-After"], "60")
        self.assertEqual(calls, [b"hello"])


class ConcurrentAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_busy_rejection_releases_capacity_after_completion(self):
        started, release = asyncio.Event(), asyncio.Event()
        calls, statuses = [], []

        async def endpoint(scope, receive, send):
            calls.append(1)
            started.set()
            await release.wait()
            await JSONResponse({"ok": True})(scope, receive, send)

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(event):
            if event["type"] == "http.response.start":
                statuses.append(event["status"])

        app = PublicDemoGuard(endpoint, enabled=True, concurrency=1)
        scope = {"type": "http", "path": "/v1/catalog/search", "method": "GET"}
        first = asyncio.create_task(app(scope, receive, send))
        await started.wait()
        await app(scope, receive, send)
        self.assertEqual(statuses, [503])
        release.set()
        await first
        await app(scope, receive, send)
        self.assertEqual(statuses, [503, 200, 200])
        self.assertEqual(len(calls), 2)
