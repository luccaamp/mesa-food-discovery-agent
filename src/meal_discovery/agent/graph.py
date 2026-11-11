"""Multi-step tool-calling agent built as a LangGraph state machine.

    guard ──(policy answered)──────────────────────────────► END
      │
      ▼
    agent ──(tool calls, step budget left)──► tools ──► agent
      │
      ├──(final text or step budget exhausted)──► respond ──► END
      └──(provider unavailable)───────────────► fallback ─► END

The model decides which read-only tool to call and with which arguments, and
may search once more after an empty result. Items always come from tools; the
model's closing sentence is accepted only if it passes a grounding check,
otherwise a template answer built from the tool result is used.
"""

from importlib.resources import files
import json
from time import perf_counter
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .. import policies, tools
from ..api_models import AssistantContext, AssistantRequest
from ..assistant import (GLOSSARY_WARNING, MODEL_UNAVAILABLE, PRIVACY_WARNING, cooldown_seconds, fallback_reason,
                         log_unavailable)
from ..discovery import expand_query
from ..llm import ProviderUnavailable, ToolSpec, from_environment
from .grounding import grounded_reply

MAX_MODEL_CALLS = 3
MAX_TOOL_CALLS = 2

TOOL_SPECS = [
    ToolSpec("search_catalog",
             "Search the real historical food catalog. Returns matching dishes or drinks with normalized prices.",
             {"type": "object", "properties": {
                 "query": {"type": "string", "description": "1-5 concise English dish or drink keywords"},
                 "max_price": {"type": ["number", "null"],
                               "description": "Maximum normalized price only if the user states one; otherwise null"}},
              "required": ["query"]}),
    ToolSpec("recommend_items",
             "Suggest items frequently bought together with the user's selected items, "
             "or historically popular items when nothing is selected.",
             {"type": "object", "properties": {}}),
]


def prompt_text():
    return files("meal_discovery").joinpath("prompts/agent_v1.txt").read_text(encoding="utf-8")


class AgentState(TypedDict, total=False):
    message: str
    context: AssistantContext
    messages: list[dict]
    outcome: tools.ToolOutcome | None
    traces: list[dict]
    model_calls: int
    usage: dict
    provider: str | None
    model: str | None
    answer: str | None
    status: str | None
    planner: str | None
    warnings: list[str]
    fallback_reason: str | None
    retry_after_seconds: int | None
    provider_error: dict | None


def _deps(config):
    return config["configurable"]


def guard(state: AgentState, config) -> dict:
    outcome = policies.apply(state["message"], state["context"])
    update: dict[str, Any] = {"context": outcome.context}
    if outcome.redacted:
        update["warnings"] = [PRIVACY_WARNING.format(kinds=", ".join(outcome.redacted))]
    if outcome.answer:
        return {**update, "answer": outcome.answer, "status": "needs_clarification", "planner": "policy"}
    if outcome.plan is not None:
        # Explicit refinements and recommendation requests need no model.
        deps = _deps(config)
        if outcome.plan.action == "recommend_items":
            result = tools.recommend(deps["recommender"], outcome.context)
        else:
            result = tools.search(deps["reader"], outcome.context, outcome.plan.query)
        return {**update, "outcome": result, "traces": [result.trace], "planner": outcome.planner,
                "answer": result.answer, "status": "ok" if result.items else "no_results"}
    summary = {"message": outcome.planning_message, "context": {
        "previous_search": outcome.context.last_query, "max_price": outcome.context.max_price,
        "min_price": outcome.context.min_price, "cuisine": outcome.context.cuisine,
        "selected_items": len(outcome.context.selected_items),
        "price_filter_changed_this_turn": outcome.context.max_price != state["context"].max_price}}
    # The deterministic PT->EN glossary is the catalog's own vocabulary; offering it as a hint keeps the
    # model's keywords aligned with item names (e.g. "macarrão" -> "noodles", not "pasta").
    expanded, changed = expand_query(outcome.planning_message[:200])
    if changed:
        summary["glossary_terms"] = expanded.split()
    return {**update, "messages": [{"role": "system", "content": prompt_text()},
                                   {"role": "user", "content": json.dumps(summary, ensure_ascii=False)}]}


def agent(state: AgentState, config) -> dict:
    chat_model = _deps(config)["chat_model"]
    budget_left = MAX_TOOL_CALLS - len(state.get("traces", []))
    try:
        if chat_model is None:
            raise ProviderUnavailable("provider_disabled", provider="disabled")
        result = chat_model.chat(state["messages"], tools=TOOL_SPECS if budget_left > 0 else None,
                                 max_tokens=512, temperature=0.0)
    except ProviderUnavailable as error:
        configured = getattr(chat_model, "provider", "disabled")
        return {"status": "provider_unavailable", "fallback_reason": fallback_reason(error),
                "retry_after_seconds": cooldown_seconds(error, configured)
                if error.reason == "provider_cooldown" else None,
                "usage": _merge_usage(state.get("usage", {}), {"failed_provider_attempts": error.attempts}),
                "provider_error": {"reason": error.reason, "provider": error.provider, "attempts": error.attempts}}
    calls = result.tool_calls[:max(budget_left, 0)]
    message = {"role": "assistant", "content": result.content, "tool_calls": calls}
    return {"messages": [*state["messages"], message], "model_calls": state.get("model_calls", 0) + 1,
            "usage": _merge_usage(state.get("usage", {}), result.usage),
            "provider": result.provider, "model": result.model,
            "answer": result.content if not calls else None}


def run_tools(state: AgentState, config) -> dict:
    deps = _deps(config)
    context = state["context"]
    messages = list(state["messages"])
    traces = list(state.get("traces", []))
    outcome = state.get("outcome")
    for call in messages[-1]["tool_calls"]:
        if call.name == "search_catalog":
            bound = call.arguments.get("max_price")
            if isinstance(bound, (int, float)) and not isinstance(bound, bool) and 0 <= bound < 1e6:
                context.max_price = float(bound)
            result = tools.search(deps["reader"], context, str(call.arguments.get("query", ""))[:200])
        elif call.name == "recommend_items":
            result = tools.recommend(deps["recommender"], context)
        else:
            result = tools.ToolOutcome(answer="Ferramenta desconhecida.", rejected=True)
        if result.trace:
            traces.append(result.trace)
        if not result.rejected:
            outcome = result
        payload = {"rejected": True, "reason": result.answer} if result.rejected else {
            "result_count": len(result.items), "summary": result.answer,
            "items": [{"name": item["name"], "cuisine": item["primary_cuisine"]} for item in result.items]}
        messages.append({"role": "tool", "tool_call_id": call.id, "name": call.name,
                         "content": json.dumps(payload, ensure_ascii=False)})
    return {"messages": messages, "traces": traces, "outcome": outcome, "context": context}


def respond(state: AgentState, config) -> dict:
    outcome = state.get("outcome")
    planner = f"{state['provider']}_agent"
    if outcome is None:
        reply = grounded_reply(state.get("answer"), [], state["context"])
        return {"answer": reply or tools.CLARIFY, "status": "needs_clarification", "planner": planner}
    reply = grounded_reply(state.get("answer"), outcome.items, state["context"])
    return {"answer": reply or outcome.answer, "status": "ok" if outcome.items else "no_results",
            "planner": planner}


def fallback(state: AgentState, config) -> dict:
    """Provider unavailable: same explicit glossary path as the planner mode."""
    error = ProviderUnavailable(**state["provider_error"])
    deps = _deps(config)
    provider = log_unavailable(error, getattr(deps["chat_model"], "provider", "disabled"))
    outcome = state.get("outcome")
    warnings = [*state.get("warnings", []), GLOSSARY_WARNING]
    if outcome is not None:  # a tool already ran; keep its grounded result
        return {"answer": outcome.answer, "status": "ok" if outcome.items else "no_results",
                "planner": f"{state.get('provider') or provider}_agent", "warnings": warnings}
    query, changed = expand_query(policies.apply(state["message"], state["context"]).planning_message[:200])
    if not changed:
        return {"answer": MODEL_UNAVAILABLE, "status": "needs_clarification", "planner": "glossary_fallback",
                "warnings": warnings}
    result = tools.search(deps["reader"], state["context"], query)
    if result.rejected:
        return {"answer": result.answer, "status": "needs_clarification", "planner": "glossary_fallback",
                "warnings": warnings}
    return {"outcome": result, "traces": [*state.get("traces", []), result.trace], "answer": result.answer,
            "status": "ok" if result.items else "no_results", "planner": "glossary_fallback", "warnings": warnings}


def _after_guard(state):
    return END if state.get("status") else "agent"


def _after_agent(state):
    if state.get("status") == "provider_unavailable":
        return "fallback"
    last = state["messages"][-1]
    if last.get("tool_calls") and state.get("model_calls", 0) < MAX_MODEL_CALLS:
        return "tools"
    return "respond"


def _merge_usage(total, usage):
    merged = dict(total)
    for key, value in usage.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            merged[key] = merged.get(key, 0) + value
    merged["llm_calls"] = total.get("llm_calls", 0) + (0 if "failed_provider_attempts" in usage else 1)
    if "fallback_from" in usage:
        merged["fallback_from"] = [*total.get("fallback_from", []), *usage["fallback_from"]]
    return merged


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("guard", guard)
    graph.add_node("agent", agent)
    graph.add_node("tools", run_tools)
    graph.add_node("respond", respond)
    graph.add_node("fallback", fallback)
    graph.add_edge(START, "guard")
    graph.add_conditional_edges("guard", _after_guard, ["agent", END])
    graph.add_conditional_edges("agent", _after_agent, ["tools", "respond", "fallback"])
    graph.add_edge("tools", "agent")
    graph.add_edge("respond", END)
    graph.add_edge("fallback", END)
    return graph.compile()


GRAPH = build_graph()


def _initial(request: AssistantRequest):
    return {"message": request.message, "context": request.context.model_copy(deep=True), "traces": [],
            "usage": {}, "warnings": [], "model_calls": 0}


def _config(reader, recommender, chat_model):
    return {"configurable": {"reader": reader, "recommender": recommender, "chat_model": chat_model},
            "recursion_limit": 12}


def to_response(state, started):
    outcome = state.get("outcome")
    return {"status": state["status"], "answer": state["answer"],
            "items": outcome.items if outcome and state["status"] != "needs_clarification" else [],
            "context": state["context"].model_dump(), "tools": state.get("traces", []),
            "planner": state.get("planner") or "policy", "model": state.get("model"),
            "usage": state.get("usage", {}), "elapsed_ms": round((perf_counter() - started) * 1000, 2),
            "warnings": [tools.DISCLOSURE, *state.get("warnings", [])],
            "fallback_reason": state.get("fallback_reason"), "retry_after_seconds": state.get("retry_after_seconds")}


def run_agent(request: AssistantRequest, reader, recommender, *, chat_model=None):
    started = perf_counter()
    chat_model = chat_model if chat_model is not None else from_environment()
    state = GRAPH.invoke(_initial(request), _config(reader, recommender, chat_model))
    return to_response(state, started)


def stream_agent(request: AssistantRequest, reader, recommender, *, chat_model=None):
    """Yield public step events, then the final response. No hidden reasoning is exposed."""
    started = perf_counter()
    chat_model = chat_model if chat_model is not None else from_environment()
    state = _initial(request)
    for update in GRAPH.stream(state, _config(reader, recommender, chat_model), stream_mode="updates"):
        for node, change in update.items():
            change = change or {}
            seen = len(state.get("traces", []))
            state.update(change)
            if node == "fallback":
                yield {"type": "fallback", "reason": state.get("fallback_reason")}
            for trace in change.get("traces", [])[seen:]:
                yield {"type": "tool", "name": trace["name"], "arguments": trace["arguments"],
                       "result_count": trace["result_count"], "duration_ms": round(trace["duration_ms"], 2)}
            if node == "agent" and change.get("status") != "provider_unavailable":
                calls = change["messages"][-1].get("tool_calls") or []
                yield {"type": "plan", "provider": change.get("provider"), "model": change.get("model"),
                       "tools": [call.name for call in calls]}
    yield {"type": "result", "response": to_response(state, started)}
