"""Metrics and traces: present, labeled with GenAI conventions, and free of user text."""

import unittest

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from meal_discovery import observability
from meal_discovery.agent import run_agent
from meal_discovery.api_models import AssistantRequest
from meal_discovery.llm import ProviderUnavailable
from meal_discovery.observability import InstrumentedChatModel, metrics_payload, record_turn
from test_agent import Catalog, ScriptedModel, call, recommender, text

EXPORTER = InMemorySpanExporter()
_provider = TracerProvider()
_provider.add_span_processor(SimpleSpanProcessor(EXPORTER))
trace.set_tracer_provider(_provider)
observability.tracer = trace.get_tracer("mesa-test")


class ObservabilityTests(unittest.TestCase):
    def setUp(self):
        EXPORTER.clear()

    def test_agent_turn_produces_llm_and_tool_spans_without_user_text(self):
        secret_message = "arroz com frango para a Maria"
        model = InstrumentedChatModel(ScriptedModel(call("search_catalog", query="chicken rice"), text("Achei.")))
        result = run_agent(AssistantRequest(message=secret_message), Catalog(), recommender, chat_model=model)
        record_turn("agent", result)
        spans = EXPORTER.get_finished_spans()
        names = [span.name for span in spans]
        self.assertEqual(names.count("chat scripted"), 2)
        self.assertIn("execute_tool search_catalog", names)
        chat = next(span for span in spans if span.name == "chat scripted")
        self.assertEqual(chat.attributes["gen_ai.system"], "groq")
        self.assertEqual(chat.attributes["gen_ai.request.model"], "scripted")
        self.assertEqual(chat.attributes["mesa.tools_offered"], 2)
        dumped = " ".join(str(dict(span.attributes)) for span in spans)
        self.assertNotIn("Maria", dumped)
        self.assertNotIn("frango", dumped)

    def test_failures_are_counted_and_marked_on_the_span(self):
        model = InstrumentedChatModel(ScriptedModel(ProviderUnavailable("provider_http_429", attempts=1)))
        run_agent(AssistantRequest(message="pizza"), Catalog(), recommender, chat_model=model)
        failed = next(span for span in EXPORTER.get_finished_spans() if span.name.startswith("chat"))
        self.assertEqual(failed.attributes["error.type"], "provider_http_429")
        body, content_type = metrics_payload()
        text_metrics = body.decode()
        self.assertIn('mesa_llm_calls_total{model="scripted",outcome="provider_http_429",provider="groq"}', text_metrics)
        self.assertIn("text/plain", content_type)

    def test_turn_metrics_use_low_cardinality_labels(self):
        record_turn("agent", {"planner": "gemini_agent", "status": "ok"})
        record_turn("agent", {"planner": "glossary_fallback", "status": "ok", "fallback_reason": "quota"})
        text_metrics = metrics_payload()[0].decode()
        self.assertIn('mesa_assistant_turns_total{mode="agent",planner="model",status="ok"}', text_metrics)
        self.assertIn('mesa_assistant_fallbacks_total{reason="quota"}', text_metrics)
        self.assertNotIn("gemini_agent", text_metrics)


if __name__ == "__main__":
    unittest.main()
