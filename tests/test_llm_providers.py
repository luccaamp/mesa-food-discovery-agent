"""Provider adapters and routing with mocked transport; no live provider calls."""

from io import BytesIO
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError

from meal_discovery.api_models import AssistantContext, AssistantRequest, AssistantResponse
from meal_discovery.assistant import run_assistant
from meal_discovery.cloud_limits import CallBudget, ProviderCooldown
from meal_discovery.llm import (ChatResult, FallbackChatModel, ProviderUnavailable, ToolCall, ToolSpec,
                                build, from_environment)
from meal_discovery.llm.gemini import GeminiChatModel
from meal_discovery.llm.openai_compatible import OpenAICompatibleChatModel
from meal_discovery.planner import IntentPlanner

SEARCH_TOOL = ToolSpec("search_catalog", "Search the catalog.",
                       {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]})
ENV = {"GEMINI_API_KEY": "gemini-test-only", "GROQ_API_KEY": "groq-test-only",
       "GEMINI_CALLS_PER_MINUTE": "4", "GEMINI_CALLS_PER_DAY": "20",
       "GROQ_CALLS_PER_MINUTE": "4", "GROQ_CALLS_PER_DAY": "20"}


def reply(payload):
    return BytesIO(json.dumps(payload).encode())


def groq_reply(content=None, tool_calls=None, finish="stop"):
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return reply({"choices": [{"finish_reason": finish, "message": message}],
                  "usage": {"prompt_tokens": 30, "completion_tokens": 7, "total_tokens": 37}})


class IsolatedState(unittest.TestCase):
    def setUp(self):
        for target, value in (("meal_discovery.llm.resilience.BUDGETS", {"gemini": CallBudget(), "groq": CallBudget()}),
                              ("meal_discovery.llm.resilience.COOLDOWNS", {"gemini": ProviderCooldown(), "groq": ProviderCooldown()})):
            patcher = patch.dict(target, value, clear=True)
            patcher.start()
            self.addCleanup(patcher.stop)
        environment = patch.dict(os.environ, ENV)
        environment.start()
        self.addCleanup(environment.stop)


class GroqAdapterTests(IsolatedState):
    def test_structured_output_payload_auth_and_usage(self):
        model = OpenAICompatibleChatModel("groq")
        with patch("meal_discovery.llm.resilience.urlopen", return_value=groq_reply('{"action":"clarify","query":null}')) as transport:
            result = model.chat([{"role": "system", "content": "rules"}, {"role": "user", "content": "oi"}],
                                json_schema={"type": "object"})
        request = transport.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, "https://api.groq.com/openai/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer groq-test-only")
        self.assertEqual(request.get_header("User-agent"), "mesa-food-discovery-agent/0.9")
        self.assertEqual(payload["model"], "openai/gpt-oss-120b")
        self.assertEqual(payload["response_format"]["type"], "json_schema")
        self.assertEqual(payload["reasoning_effort"], "low")
        self.assertFalse(payload["include_reasoning"])
        self.assertEqual(result.provider, "groq")
        self.assertEqual(result.usage["total_tokens"], 37)
        self.assertEqual(result.usage["provider_attempts"], 1)

    def test_tool_calls_round_trip(self):
        call = {"id": "call_1", "type": "function", "function": {"name": "search_catalog", "arguments": '{"query":"laksa"}'}}
        model = OpenAICompatibleChatModel("groq")
        with patch("meal_discovery.llm.resilience.urlopen", return_value=groq_reply(tool_calls=[call])):
            result = model.chat([{"role": "user", "content": "laksa"}], tools=[SEARCH_TOOL])
        self.assertEqual(result.tool_calls, [ToolCall("call_1", "search_catalog", {"query": "laksa"})])
        history = [{"role": "user", "content": "laksa"},
                   {"role": "assistant", "content": None, "tool_calls": result.tool_calls},
                   {"role": "tool", "tool_call_id": "call_1", "name": "search_catalog", "content": '{"items":[]}'}]
        with patch("meal_discovery.llm.resilience.urlopen", return_value=groq_reply("Nada encontrado.")) as transport:
            model.chat(history, tools=[SEARCH_TOOL])
        sent = json.loads(transport.call_args.args[0].data)
        self.assertEqual(sent["messages"][1]["tool_calls"][0]["function"]["arguments"], '{"query": "laksa"}')
        self.assertEqual(sent["messages"][2], {"role": "tool", "tool_call_id": "call_1", "content": '{"items":[]}'})
        self.assertEqual(sent["tools"][0]["function"]["name"], "search_catalog")
        self.assertFalse(sent["parallel_tool_calls"])

    def test_truncated_and_malformed_answers_fail_closed(self):
        model = OpenAICompatibleChatModel("groq")
        bad_call = {"id": "c", "type": "function", "function": {"name": "x", "arguments": "{not json"}}
        for response in (groq_reply("{", finish="length"), reply({"choices": []}), groq_reply(tool_calls=[bad_call])):
            with self.subTest(), patch("meal_discovery.llm.resilience.urlopen", return_value=response):
                with self.assertRaises(ProviderUnavailable):
                    model.chat([{"role": "user", "content": "pizza"}])

    def test_missing_key_and_bad_budget_never_send(self):
        with patch("meal_discovery.llm.resilience.urlopen") as transport:
            with patch.dict(os.environ, {"GROQ_API_KEY": ""}), self.assertRaises(ProviderUnavailable) as raised:
                OpenAICompatibleChatModel("groq").chat([{"role": "user", "content": "x"}])
            self.assertEqual(raised.exception.reason, "not_configured")
            with patch.dict(os.environ, {"GROQ_CALLS_PER_DAY": "0"}), self.assertRaises(ProviderUnavailable) as raised:
                OpenAICompatibleChatModel("groq").chat([{"role": "user", "content": "x"}])
            self.assertEqual(raised.exception.reason, "invalid_budget_configuration")
        transport.assert_not_called()

    def test_local_endpoint_must_stay_on_loopback(self):
        with patch.dict(os.environ, {"LOCAL_LLM_URL": "http://example.com:8081"}), \
                patch("meal_discovery.llm.resilience.urlopen") as transport:
            with self.assertRaises(ProviderUnavailable) as raised:
                OpenAICompatibleChatModel("local").chat([{"role": "user", "content": "x"}])
        self.assertEqual(raised.exception.reason, "local_endpoint_must_be_loopback")
        transport.assert_not_called()


class GeminiToolTests(IsolatedState):
    def test_function_declarations_and_thought_signature_echo(self):
        response = {"candidates": [{"finishReason": "STOP", "content": {"parts": [
            {"functionCall": {"name": "search_catalog", "args": {"query": "laksa"}}, "thoughtSignature": "sig-1"}]}}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 3, "totalTokenCount": 13}}
        model = GeminiChatModel(model="gemini-3.1-flash-lite")
        with patch("meal_discovery.llm.resilience.urlopen", return_value=reply(response)) as transport:
            result = model.chat([{"role": "system", "content": "rules"}, {"role": "user", "content": "laksa"}],
                                tools=[SEARCH_TOOL])
        payload = json.loads(transport.call_args.args[0].data)
        self.assertEqual(payload["tools"][0]["functionDeclarations"][0]["name"], "search_catalog")
        self.assertEqual(payload["systemInstruction"]["parts"][0]["text"], "rules")
        self.assertEqual(result.tool_calls[0].arguments, {"query": "laksa"})
        history = [{"role": "user", "content": "laksa"},
                   {"role": "assistant", "content": None, "tool_calls": result.tool_calls},
                   {"role": "tool", "tool_call_id": result.tool_calls[0].id, "name": "search_catalog", "content": "{}"}]
        final = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "ok"}]}}], "usageMetadata": {}}
        with patch("meal_discovery.llm.resilience.urlopen", return_value=reply(final)) as transport:
            model.chat(history, tools=[SEARCH_TOOL])
        contents = json.loads(transport.call_args.args[0].data)["contents"]
        self.assertEqual(contents[1]["role"], "model")
        self.assertEqual(contents[1]["parts"][0]["thoughtSignature"], "sig-1")
        self.assertEqual(contents[2]["parts"][0]["functionResponse"]["name"], "search_catalog")


class FallbackTests(IsolatedState):
    def plan_payloads(self):
        gemini_down = HTTPError("https://example.invalid", 429, "quota", {}, None)
        return [gemini_down, groq_reply('{"action":"search_catalog","query":"chicken rice"}')]

    def test_primary_quota_falls_back_to_groq_and_records_it(self):
        with patch.dict(os.environ, {"LLM_PROVIDER": "gemini", "LLM_MODEL": "gemini-3.1-flash-lite",
                                     "LLM_FALLBACK_PROVIDERS": "groq"}), \
                patch("meal_discovery.llm.resilience.urlopen", side_effect=self.plan_payloads()) as transport:
            planner = IntentPlanner()
            plan, usage = planner.plan("arroz com frango", AssistantContext())
        self.assertIsInstance(planner.chat_model, FallbackChatModel)
        self.assertEqual(plan.query, "chicken rice")
        self.assertEqual(planner.last_served, ("groq", "openai/gpt-oss-120b"))
        self.assertEqual(usage["fallback_from"], [{"provider": "gemini", "reason": "provider_http_429", "attempts": 1}])
        self.assertEqual(transport.call_count, 2)

    def test_assistant_reports_the_provider_that_actually_answered(self):
        reader = SimpleNamespace(search=lambda params: {"items": [], "total_matches": 0})
        with patch.dict(os.environ, {"LLM_PROVIDER": "gemini", "LLM_MODEL": "gemini-3.1-flash-lite",
                                     "LLM_FALLBACK_PROVIDERS": "groq"}), \
                patch("meal_discovery.llm.resilience.urlopen", side_effect=self.plan_payloads()):
            result = run_assistant(AssistantRequest(message="arroz com frango"), reader, lambda args: {})
        parsed = AssistantResponse.model_validate(result)
        self.assertEqual(parsed.planner, "groq_llm")
        self.assertEqual(parsed.model, "openai/gpt-oss-120b")
        self.assertIsNone(parsed.fallback_reason)

    def test_all_providers_failing_reports_primary_reason(self):
        failures = [HTTPError("https://example.invalid", 429, "q", {}, None),
                    HTTPError("https://example.invalid", 401, "auth", {}, None)]
        model = FallbackChatModel([build("gemini", "gemini-3.1-flash-lite"), build("groq")])
        with patch("meal_discovery.llm.resilience.urlopen", side_effect=failures):
            with self.assertRaises(ProviderUnavailable) as raised:
                model.chat([{"role": "user", "content": "pizza"}])
        self.assertEqual(raised.exception.reason, "provider_http_429")
        self.assertEqual(raised.exception.provider, "gemini")
        self.assertEqual(raised.exception.attempts, 2)

    def test_unconfigured_fallback_is_skipped_without_sending(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": ""}):
            model = FallbackChatModel([build("groq"), build("gemini", "gemini-3.1-flash-lite")])
            gemini = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "ok"}]}}], "usageMetadata": {}}
            with patch("meal_discovery.llm.resilience.urlopen", return_value=reply(gemini)) as transport:
                result = model.chat([{"role": "user", "content": "x"}])
        self.assertEqual(result.provider, "gemini")
        self.assertEqual(transport.call_count, 1)

    def test_environment_selection(self):
        with patch.dict(os.environ, {"LLM_PROVIDER": "disabled"}):
            self.assertIsNone(from_environment())
        with patch.dict(os.environ, {"LLM_PROVIDER": "groq", "LLM_FALLBACK_PROVIDERS": "groq, unknown"}):
            self.assertEqual(from_environment().provider, "groq")
            self.assertNotIsInstance(from_environment(), FallbackChatModel)

    def test_disabled_planner_falls_back_to_glossary(self):
        reader = SimpleNamespace(search=lambda params: {"items": [], "total_matches": 0})
        with patch.dict(os.environ, {"LLM_PROVIDER": "disabled"}):
            result = run_assistant(AssistantRequest(message="arroz com frango"), reader, lambda args: {})
        self.assertEqual(result["planner"], "glossary_fallback")
        self.assertEqual(result["fallback_reason"], "provider_unavailable")


if __name__ == "__main__":
    unittest.main()
