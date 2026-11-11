"""Assistant application service: policies first, one planning call, grounded tools.

Deterministic policies (dietary guarantees, injection, greetings, price
refinements) run before any model. The planner chooses a bounded action; the
answer and every item come from read-only catalog and recommendation tools.
"""

import logging
import math
import re
from time import perf_counter

from .api_models import AssistantRequest, IntentPlan, SearchParams
from .discovery import expand_query, fold, guarded_constraint
from .llm import ProviderUnavailable, resilience
from .planner import IntentPlanner

logger = logging.getLogger("meal_discovery.assistant")
SANITIZED_REASONS = {"local_quota", "provider_cooldown", "network_error", "provider_timeout", "invalid_response",
                     "incomplete_response", "invalid_model_configuration", "invalid_budget_configuration",
                     "not_configured", "provider_disabled", "local_endpoint_must_be_loopback"}
KNOWN_PROVIDERS = {"gemini", "groq", "openai", "local"}


def run_assistant(request: AssistantRequest, reader, recommender, *, planner=None):
    started = perf_counter()
    context = request.context.model_copy(deep=True)
    traces = []
    warnings = ["Catálogo histórico. Preços normalizados, sem moeda. Sem garantia de estoque, entrega ou composição alimentar."]
    planner_name = "policy"
    model_name = None
    usage = {}
    fallback_reason = None
    retry_after_seconds = None

    def finish(status, answer, items=None):
        return {"status": status, "answer": answer, "items": items or [], "context": context.model_dump(),
                "tools": traces, "planner": planner_name, "model": model_name, "usage": usage,
                "elapsed_ms": round((perf_counter() - started) * 1000, 2), "warnings": warnings,
                "fallback_reason": fallback_reason, "retry_after_seconds": retry_after_seconds}

    constraint = guarded_constraint(request.message)
    if constraint:
        return finish("needs_clarification", constraint)
    text = fold(request.message)
    if re.fullmatch(r"(?:oi|ola|bom dia|boa tarde|boa noite|hello|hi)[.!?\s]*", text.strip()):
        return finish("needs_clarification", "Olá! Qual prato ou bebida você gostaria de explorar? Também posso sugerir itens pela popularidade histórica.")
    if re.search(r"ignore.*(instruc|regra)|system prompt|execute.*(sql|python|codigo)|https?://", text):
        return finish("needs_clarification", "Posso explorar pratos e bebidas do catálogo. Diga o que você gostaria de buscar.")
    # A refinement changes only the explicit normalized bound and retains the last dish.
    bound = re.search(r"(?:ate|no maximo)\s*(\d+(?:[.,]\d+)?)", text)
    if bound:
        context.max_price = float(bound.group(1).replace(",", "."))
        if not math.isfinite(context.max_price):
            return finish("needs_clarification", "Use um limite finito de preço normalizado.")
        if context.min_price is not None and context.min_price > context.max_price:
            return finish("needs_clarification", "O preço máximo ficou abaixo do mínimo. Ajuste os limites de preço normalizado.")
    # Price is already represented structurally. Do not make it a required menu token
    # when a new dish and an explicit bound arrive in the same message.
    planning_message = request.message
    if bound:
        planning_message = re.sub(r"(?:ate|no maximo)\s*\d+(?:[.,]\d+)?(?:\s+unidades?(?:\s+normalizadas?)?)?", "", text).strip()
    price_only = re.fullmatch(r"(?:ate|no maximo)\s*\d+(?:[.,]\d+)?(?:\s+unidades?(?:\s+normalizadas?)?)?[.!?\s]*", text.strip())
    if bound and price_only and context.last_query:
        plan = IntentPlan(action="search_catalog", query=context.last_query)
        planner_name = "explicit_filter_refinement"
    elif re.fullmatch(r"(?:me )?(?:recomende|sugira|mostre)(?: me)? (?:algo|sugestoes|recomendacoes|opcoes)(?: (?:para mim|da minha selecao|com os itens selecionados))?[.!?]*", text.strip()):
        plan = IntentPlan(action="recommend_items", query=None)
        planner_name = "explicit_recommendation"
    else:
        planner = planner or IntentPlanner()
        try:
            plan, usage = planner.plan(planning_message, context)
            served_provider, model_name = getattr(planner, "last_served", None) or (planner.provider, planner.model)
            planner_name = served_provider + "_llm"
        except ProviderUnavailable as error:
            fallback_reason = (
                error.reason if error.reason in {"provider_timeout", "provider_cooldown"}
                else "quota" if error.reason in {"local_quota", "provider_http_429"}
                else "invalid_response" if error.reason in {"invalid_response", "incomplete_response"}
                else "provider_unavailable"
            )
            if error.reason == "provider_cooldown":
                paused = error.provider if error.provider in KNOWN_PROVIDERS else planner.provider
                retry_after_seconds = resilience.cooldown(paused).snapshot()["retry_after_seconds"]
            # Never log provider response bodies, exception URLs, messages or keys.
            reason = error.reason if error.reason in SANITIZED_REASONS or re.fullmatch(r"provider_http_[0-9]{3}", error.reason) else "unavailable"
            provider = planner.provider if planner.provider in KNOWN_PROVIDERS else "disabled"
            logger.warning("planner_unavailable provider=%s reason=%s attempts=%d", provider, reason, error.attempts)
            if provider in KNOWN_PROVIDERS - {"local"}:
                usage = {"provider_attempts": error.attempts, "failed_attempts_usage_unknown": error.attempts}
            query, changed = expand_query(planning_message[:200])
            if not changed:
                return finish("needs_clarification", "O modelo de linguagem está indisponível. Você pode usar a busca do catálogo ou pedir um prato com termos como arroz, frango, pizza ou café.")
            plan = IntentPlan(action="search_catalog", query=query)
            planner_name = "glossary_fallback"
            warnings.append("Modelo indisponível ou cota atingida: usei somente o glossário explícito, sem inferência de LLM.")
    if plan.action == "clarify" or plan.action == "search_catalog" and not plan.query:
        return finish("needs_clarification", "Qual prato ou bebida você gostaria de explorar? Posso também sugerir itens pela popularidade histórica.")
    tool_started = perf_counter()
    if plan.action == "recommend_items":
        args = {"seeds": [item.model_dump() for item in context.selected_items], "cuisine": context.cuisine,
                "min_price": context.min_price, "max_price": context.max_price, "limit": 6}
        result = recommender(args)
        items = result["items"]
        traces.append({"name": "recommend_items", "arguments": args, "duration_ms": (perf_counter() - tool_started) * 1000, "result_count": len(items)})
        if any(item.get("reason") == "basket_association" for item in items):
            answer = "Estas sugestões usam associações de compra dos itens que você selecionou, com complemento por popularidade histórica."
        elif context.selected_items:
            answer = "Não encontrei associações para os itens selecionados com esses filtros. As opções disponíveis seguem a popularidade histórica dos pedidos de treino."
        else:
            answer = "Sem itens selecionados, estas sugestões seguem a popularidade histórica dos pedidos de treino."
        if not items:
            answer = "Não encontrei sugestões com esses filtros. Amplie o intervalo de preço normalizado ou escolha outra culinária."
    else:
        query = plan.query.strip()
        if guarded_constraint(query) or len(query.split()) > 8:
            return finish("needs_clarification", "Preciso de um nome de prato ou bebida mais específico, sem prometer restrições que o catálogo não comprova.")
        params = SearchParams(query=query, cuisine=context.cuisine, min_price=context.min_price, max_price=context.max_price, limit=6)
        result = reader.search(params)
        context.last_query = query
        items = result["items"]
        traces.append({"name": "search_catalog", "arguments": params.model_dump(), "duration_ms": (perf_counter() - tool_started) * 1000, "result_count": len(items)})
        answer = f"Busquei “{query}” no catálogo real e encontrei {result['total_matches']:,} correspondências. Os cards abaixo preservam os nomes originais." if items else f"Não encontrei correspondências para “{query}” com esses filtros. Tente um nome mais simples ou amplie o limite de preço."
    return finish("ok" if items else "no_results", answer, items)
