"""Planner-mode assistant: policies first, one planning call, grounded tools.

Deterministic policies (dietary guarantees, injection, greetings, price
refinements) run before any model. The planner chooses a bounded action; the
answer and every item come from read-only catalog and recommendation tools.
The multi-step agent (`agent/`) reuses the same policies and tools.
"""

import logging
import re
from time import perf_counter

from . import policies, tools
from .api_models import AssistantRequest, IntentPlan
from .discovery import expand_query
from .llm import ProviderUnavailable, resilience
from .planner import IntentPlanner

logger = logging.getLogger("meal_discovery.assistant")
SANITIZED_REASONS = {"local_quota", "provider_cooldown", "network_error", "provider_timeout", "invalid_response",
                     "incomplete_response", "invalid_model_configuration", "invalid_budget_configuration",
                     "not_configured", "provider_disabled", "local_endpoint_must_be_loopback"}
KNOWN_PROVIDERS = {"gemini", "groq", "openai", "local"}
MODEL_UNAVAILABLE = ("O modelo de linguagem está indisponível. Você pode usar a busca do catálogo ou pedir "
                     "um prato com termos como arroz, frango, pizza ou café.")
GLOSSARY_WARNING = "Modelo indisponível ou cota atingida: usei somente o glossário explícito, sem inferência de LLM."


def fallback_reason(error):
    """Map a provider failure to the small public vocabulary of the API."""
    if error.reason in {"provider_timeout", "provider_cooldown"}:
        return error.reason
    if error.reason in {"local_quota", "provider_http_429"}:
        return "quota"
    if error.reason in {"invalid_response", "incomplete_response"}:
        return "invalid_response"
    return "provider_unavailable"


def log_unavailable(error, configured_provider):
    # Never log provider response bodies, exception URLs, messages or keys.
    reason = (error.reason if error.reason in SANITIZED_REASONS or re.fullmatch(r"provider_http_[0-9]{3}", error.reason)
              else "unavailable")
    provider = configured_provider if configured_provider in KNOWN_PROVIDERS else "disabled"
    logger.warning("planner_unavailable provider=%s reason=%s attempts=%d", provider, reason, error.attempts)
    return provider


def cooldown_seconds(error, configured_provider):
    paused = error.provider if error.provider in KNOWN_PROVIDERS else configured_provider
    return resilience.cooldown(paused).snapshot()["retry_after_seconds"] if paused in KNOWN_PROVIDERS else 0


def run_assistant(request: AssistantRequest, reader, recommender, *, planner=None):
    started = perf_counter()
    traces = []
    warnings = [tools.DISCLOSURE]
    state = {"planner": "policy", "model": None, "usage": {}, "fallback_reason": None, "retry_after_seconds": None}
    outcome = policies.apply(request.message, request.context)
    context = outcome.context

    def finish(status, answer, items=None):
        return {"status": status, "answer": answer, "items": items or [], "context": context.model_dump(),
                "tools": traces, "planner": state["planner"], "model": state["model"], "usage": state["usage"],
                "elapsed_ms": round((perf_counter() - started) * 1000, 2), "warnings": warnings,
                "fallback_reason": state["fallback_reason"], "retry_after_seconds": state["retry_after_seconds"]}

    if outcome.answer:
        return finish("needs_clarification", outcome.answer)
    plan = outcome.plan
    if plan is not None:
        state["planner"] = outcome.planner
    else:
        planner = planner or IntentPlanner()
        try:
            plan, state["usage"] = planner.plan(outcome.planning_message, context)
            served_provider, state["model"] = getattr(planner, "last_served", None) or (planner.provider, planner.model)
            state["planner"] = served_provider + "_llm"
        except ProviderUnavailable as error:
            state["fallback_reason"] = fallback_reason(error)
            if error.reason == "provider_cooldown":
                state["retry_after_seconds"] = cooldown_seconds(error, planner.provider)
            provider = log_unavailable(error, planner.provider)
            if provider in KNOWN_PROVIDERS - {"local"}:
                state["usage"] = {"provider_attempts": error.attempts, "failed_attempts_usage_unknown": error.attempts}
            query, changed = expand_query(outcome.planning_message[:200])
            if not changed:
                return finish("needs_clarification", MODEL_UNAVAILABLE)
            plan = IntentPlan(action="search_catalog", query=query)
            state["planner"] = "glossary_fallback"
            warnings.append(GLOSSARY_WARNING)
    if plan.action == "clarify" or plan.action == "search_catalog" and not plan.query:
        return finish("needs_clarification", tools.CLARIFY)
    if plan.action == "recommend_items":
        result = tools.recommend(recommender, context)
    else:
        result = tools.search(reader, context, plan.query)
        if result.rejected:
            return finish("needs_clarification", result.answer)
    traces.append(result.trace)
    return finish("ok" if result.items else "no_results", result.answer, result.items)
