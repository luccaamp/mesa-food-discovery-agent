"""Metrics (Prometheus) and traces (OpenTelemetry) for the API, agent and LLM calls.

Metrics are always on and served at /metrics. Traces are exported only when
OTEL_EXPORTER_OTLP_ENDPOINT points at a collector (Jaeger, Grafana Tempo,
Langfuse, Honeycomb...); otherwise spans are no-ops. Span attributes follow the
OpenTelemetry GenAI semantic conventions. No message text, phone number or
API key is ever recorded in a metric label or span attribute.
"""

from contextlib import contextmanager
import os
from time import perf_counter

from opentelemetry import trace
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram, generate_latest

REGISTRY = CollectorRegistry()
LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30)

HTTP = Histogram("mesa_http_request_seconds", "HTTP request latency", ["route", "method", "status"],
                 buckets=LATENCY_BUCKETS, registry=REGISTRY)
LLM_CALLS = Counter("mesa_llm_calls_total", "Language model calls", ["provider", "model", "outcome"], registry=REGISTRY)
LLM_LATENCY = Histogram("mesa_llm_call_seconds", "Language model call latency", ["provider"],
                        buckets=LATENCY_BUCKETS, registry=REGISTRY)
LLM_TOKENS = Counter("mesa_llm_tokens_total", "Tokens in successful responses", ["provider", "direction"],
                     registry=REGISTRY)
TOOLS = Histogram("mesa_tool_seconds", "Catalog tool latency", ["tool"], buckets=LATENCY_BUCKETS, registry=REGISTRY)
TURNS = Counter("mesa_assistant_turns_total", "Assistant turns", ["mode", "planner", "status"], registry=REGISTRY)
FALLBACKS = Counter("mesa_assistant_fallbacks_total", "Turns answered without a model", ["reason"], registry=REGISTRY)

tracer = trace.get_tracer("mesa")
_configured = False


def setup_tracing():
    """Install an OTLP exporter once, if a collector endpoint is configured."""
    global _configured
    if _configured or not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return False
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    provider = TracerProvider(resource=Resource.create({"service.name": os.environ.get("OTEL_SERVICE_NAME", "mesa-api")}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    _configured = True
    return True


def metrics_payload():
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


class InstrumentedChatModel:
    """Decorator around any ChatModel: one span, latency, outcome and token metrics per call."""

    def __init__(self, inner):
        self.inner = inner
        self.provider, self.model = inner.provider, inner.model

    @property
    def configured(self):
        return self.inner.configured

    def __getattr__(self, name):  # endpoint, base_url... of the wrapped adapter
        return getattr(self.inner, name)

    def chat(self, messages, **options):
        started = perf_counter()
        with tracer.start_as_current_span(f"chat {self.model}") as span:
            span.set_attribute("gen_ai.operation.name", "chat")
            span.set_attribute("gen_ai.system", self.provider)
            span.set_attribute("gen_ai.request.model", self.model)
            span.set_attribute("gen_ai.request.max_tokens", options.get("max_tokens", 0))
            span.set_attribute("mesa.tools_offered", len(options.get("tools") or []))
            try:
                result = self.inner.chat(messages, **options)
            except Exception as error:
                reason = getattr(error, "reason", type(error).__name__)
                span.set_attribute("error.type", reason)
                span.set_status(trace.Status(trace.StatusCode.ERROR))
                LLM_CALLS.labels(self.provider, self.model, reason).inc()
                LLM_LATENCY.labels(self.provider).observe(perf_counter() - started)
                raise
            usage = result.usage or {}
            span.set_attribute("gen_ai.usage.input_tokens", usage.get("prompt_tokens", 0))
            span.set_attribute("gen_ai.usage.output_tokens", usage.get("completion_tokens", 0))
            span.set_attribute("mesa.tool_calls", len(result.tool_calls))
            LLM_CALLS.labels(self.provider, self.model, "ok").inc()
            LLM_LATENCY.labels(self.provider).observe(perf_counter() - started)
            LLM_TOKENS.labels(self.provider, "input").inc(usage.get("prompt_tokens", 0) or 0)
            LLM_TOKENS.labels(self.provider, "output").inc(usage.get("completion_tokens", 0) or 0)
            return result


@contextmanager
def tool_span(name, **attributes):
    started = perf_counter()
    with tracer.start_as_current_span(f"execute_tool {name}") as span:
        span.set_attribute("gen_ai.tool.name", name)
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(f"mesa.{key}", value)
        try:
            yield span
        finally:
            TOOLS.labels(name).observe(perf_counter() - started)


def record_turn(mode, response):
    planner = response.get("planner") or "unknown"
    # Collapse provider-specific planner names to keep label cardinality small.
    planner = "model" if planner.endswith(("_llm", "_agent")) else planner
    TURNS.labels(mode, planner, response.get("status", "unknown")).inc()
    if response.get("fallback_reason"):
        FALLBACKS.labels(response["fallback_reason"]).inc()
