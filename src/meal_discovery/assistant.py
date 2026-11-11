"""One bounded planning call and grounded read-only tools; no generated catalog facts."""

from importlib.resources import files
from email.utils import parsedate_to_datetime
import json
import logging
import os
import math
import re
from time import monotonic, perf_counter, sleep, time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from pydantic import ValidationError

from .api_models import AssistantContext, AssistantRequest, IntentPlan
from .discovery import expand_query, fold, guarded_constraint
from .cloud_limits import CallBudget, ProviderCooldown

GEMINI_BUDGET = CallBudget()
GEMINI_COOLDOWN = ProviderCooldown()
GEMINI_MAX_ATTEMPTS = 2
GEMINI_ATTEMPT_TIMEOUT = 20
GEMINI_TOTAL_TIMEOUT = 45
GEMINI_TRANSIENT_HTTP = {500, 502, 503, 504}
logger = logging.getLogger("meal_discovery.assistant")


class PlannerUnavailable(Exception):
    def __init__(self, reason="unavailable", *, attempts=0):
        self.reason = reason
        self.attempts = attempts
        super().__init__("Planner unavailable: " + reason)


def prompt_text():
    return files("meal_discovery").joinpath("prompts/intent_v1.txt").read_text(encoding="utf-8")


def retry_delay(headers):
    """Honor both Retry-After forms; never shorten a server-requested delay."""
    value = (headers or {}).get("Retry-After", "")
    if not isinstance(value, str):
        return 1
    value = value.strip()
    if value.isdigit():
        return max(1, int(value)) if len(value) <= 6 else float("inf")
    if value:
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is not None:
                return max(1, date.timestamp() - time())
        except (TypeError, ValueError, OverflowError):
            pass
    return 1


def network_failure_reason(error):
    cause = error.reason if isinstance(error, URLError) else error
    return "provider_timeout" if isinstance(cause, TimeoutError) else "network_error"


def request_gemini(request, per_minute, per_day):
    if not GEMINI_COOLDOWN.acquire():
        raise PlannerUnavailable("provider_cooldown")
    outcome = "neutral"
    started = perf_counter()
    try:
        result = _request_gemini(request, per_minute, per_day)
        outcome = "success"
        return result
    except PlannerUnavailable as error:
        if error.reason in {"provider_timeout", "network_error",
                            *(f"provider_http_{code}" for code in GEMINI_TRANSIENT_HTTP)}:
            outcome = "failure"
        logger.warning("planner_request provider=gemini reason=%s attempts=%d elapsed_ms=%d",
                       error.reason, error.attempts, round((perf_counter() - started) * 1000))
        raise
    finally:
        GEMINI_COOLDOWN.record(outcome)


def _request_gemini(request, per_minute, per_day):
    """At most two read-only generation attempts, each charged to our quota.

    Retry transient HTTP failures and one timeout within the shared time budget.
    Generation is read-only but a timed-out attempt may still be billed upstream;
    every attempt consumes quota and failed-attempt tokens remain unknown.
    """
    deadline = monotonic() + GEMINI_TOTAL_TIMEOUT
    attempts = 0
    for number in range(1, GEMINI_MAX_ATTEMPTS + 1):
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise PlannerUnavailable("provider_timeout", attempts=attempts)
        if not GEMINI_BUDGET.take(per_minute, per_day):
            raise PlannerUnavailable("local_quota", attempts=attempts)
        attempts = number
        try:
            with urlopen(request, timeout=min(GEMINI_ATTEMPT_TIMEOUT, remaining)) as response:
                return json.loads(response.read(256 * 1024)), attempts
        except HTTPError as error:
            delay = retry_delay(error.headers)
            code = error.code
            if error.fp is not None:
                error.close()
            if code not in GEMINI_TRANSIENT_HTTP or number == GEMINI_MAX_ATTEMPTS or delay >= deadline - monotonic():
                raise PlannerUnavailable(f"provider_http_{code}", attempts=attempts) from error
            logger.info("planner_retry provider=gemini attempt=%d reason=provider_http_%d delay_ms=%d",
                        number, code, round(delay * 1000))
            sleep(delay)
        except (URLError, TimeoutError, OSError) as error:
            reason = network_failure_reason(error)
            if (reason != "provider_timeout" or number == GEMINI_MAX_ATTEMPTS
                    or deadline - monotonic() < GEMINI_ATTEMPT_TIMEOUT + 1):
                raise PlannerUnavailable(reason, attempts=attempts) from error
            logger.info("planner_retry provider=gemini attempt=%d reason=provider_timeout delay_ms=1000", number)
            sleep(1)
        except (TypeError, ValueError) as error:
            raise PlannerUnavailable("invalid_response", attempts=attempts) from error
    raise AssertionError("Unreachable bounded retry state")


class HttpPlanner:
    def __init__(self):
        self.provider = os.environ.get("LLM_PROVIDER", "local")
        self.model = os.environ.get("LLM_MODEL", "meal-local" if self.provider == "local" else "")
        self.endpoint = os.environ.get("LOCAL_LLM_URL", "http://127.0.0.1:8081")
        self.key = os.environ.get("OPENAI_API_KEY")
        self.gemini_key = os.environ.get("GEMINI_API_KEY")

    @property
    def configured(self):
        if self.provider == "gemini":
            return bool(self.gemini_key and self.model)
        if self.provider == "openai":
            return bool(self.key and self.model)
        return self.provider == "local" and bool(self.model)

    def plan(self, message, context):
        user = json.dumps({"message": message, "previous_query": context.last_query}, ensure_ascii=False)
        schema = IntentPlan.model_json_schema()
        headers = {"Content-Type": "application/json"}
        if self.provider == "local":
            parsed = urlsplit(self.endpoint)
            if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
                raise PlannerUnavailable("Local model endpoint must use loopback HTTP")
            url = self.endpoint.rstrip("/") + "/v1/chat/completions"
            payload = {"model": self.model, "messages": [{"role": "system", "content": prompt_text()},
                        {"role": "user", "content": user}], "temperature": 0, "seed": 42,
                       "max_tokens": 160, "stream": False,
                       "response_format": {"type": "json_schema", "json_schema": {"name": "catalog_intent", "schema": schema}}}
        elif self.provider == "gemini" and self.gemini_key and self.model:
            if not re.fullmatch(r"gemini-[A-Za-z0-9._-]{1,100}", self.model):
                raise PlannerUnavailable("invalid_model_configuration")
            try:
                minute = int(os.environ.get("GEMINI_CALLS_PER_MINUTE", "4"))
                daily = int(os.environ.get("GEMINI_CALLS_PER_DAY", "20"))
                if not 1 <= minute <= 60 or not 1 <= daily <= 1000:
                    raise ValueError()
            except ValueError as error:
                raise PlannerUnavailable("invalid_budget_configuration") from error
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
            headers["x-goog-api-key"] = self.gemini_key
            payload = {
                "systemInstruction": {"parts": [{"text": prompt_text()}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"temperature": 0, "maxOutputTokens": 256,
                    "responseMimeType": "application/json",
                    "responseJsonSchema": {"type": "object", "properties": {
                        "action": {"type": "string", "enum": ["search_catalog", "recommend_items", "clarify"]},
                        "query": {"type": ["string", "null"]}},
                        "required": ["action", "query"], "additionalProperties": False}},
            }
            if self.model.startswith("gemini-2.5-flash"):
                payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}
            elif self.model in {"gemini-3.1-flash-lite", "gemini-3.1-flash-lite-preview"}:
                payload["generationConfig"]["thinkingConfig"] = {"thinkingLevel": "minimal"}
        elif self.provider == "openai" and self.key and self.model:
            url = "https://api.openai.com/v1/responses"
            headers["Authorization"] = "Bearer " + self.key
            payload = {"model": self.model, "instructions": prompt_text(), "input": user,
                       "store": False, "max_output_tokens": 256, "parallel_tool_calls": False,
                       "tools": [{"type": "function", "name": "plan_catalog_intent", "description": "Choose a bounded catalog action.",
                                  "parameters": schema, "strict": True}],
                       "tool_choice": {"type": "function", "name": "plan_catalog_intent"}}
        else:
            raise PlannerUnavailable("Planner provider not configured")
        attempts = 0
        try:
            request = Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
            if self.provider == "gemini":
                result, attempts = request_gemini(request, minute, daily)
            else:
                with urlopen(request, timeout=30) as response:
                    result = json.loads(response.read(256 * 1024))
            if self.provider == "local":
                content = result["choices"][0]["message"]["content"]
                usage = result.get("usage", {})
            elif self.provider == "gemini":
                candidate = result["candidates"][0]
                if candidate.get("finishReason") != "STOP":
                    raise PlannerUnavailable("incomplete_response", attempts=attempts)
                content = "".join(part.get("text", "") for part in candidate["content"]["parts"] if not part.get("thought"))
                raw_usage = result.get("usageMetadata", {})
                usage = {"prompt_tokens": raw_usage.get("promptTokenCount", 0),
                         "completion_tokens": raw_usage.get("candidatesTokenCount", 0),
                         "total_tokens": raw_usage.get("totalTokenCount", 0),
                         "thought_tokens": raw_usage.get("thoughtsTokenCount", 0),
                         "provider_attempts": attempts, "failed_attempts_usage_unknown": attempts - 1}
            else:
                calls = [item for item in result["output"] if item.get("type") == "function_call" and item.get("name") == "plan_catalog_intent"]
                if len(calls) != 1:
                    raise PlannerUnavailable("Expected exactly one bounded intent plan")
                content = calls[0]["arguments"]
                usage = result.get("usage", {})
            return IntentPlan.model_validate_json(content), usage
        except HTTPError as error:
            raise PlannerUnavailable(f"provider_http_{error.code}", attempts=attempts) from error
        except (URLError, TimeoutError, OSError) as error:
            raise PlannerUnavailable(network_failure_reason(error), attempts=attempts) from error
        except (KeyError, IndexError, TypeError, AttributeError, ValueError, ValidationError) as error:
            raise PlannerUnavailable("invalid_response", attempts=attempts) from error


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
        planner = planner or HttpPlanner()
        try:
            plan, usage = planner.plan(planning_message, context)
            planner_name = planner.provider + "_llm"
            model_name = planner.model
        except PlannerUnavailable as error:
            fallback_reason = (
                error.reason if error.reason in {"provider_timeout", "provider_cooldown"}
                else "quota" if error.reason in {"local_quota", "provider_http_429"}
                else "invalid_response" if error.reason in {"invalid_response", "incomplete_response"}
                else "provider_unavailable"
            )
            if error.reason == "provider_cooldown":
                retry_after_seconds = GEMINI_COOLDOWN.snapshot()["retry_after_seconds"]
            # Never log provider response bodies, exception URLs, messages or keys.
            reason = error.reason if error.reason in {"local_quota", "provider_cooldown", "network_error", "provider_timeout", "invalid_response", "incomplete_response", "invalid_model_configuration", "invalid_budget_configuration"} or re.fullmatch(r"provider_http_[0-9]{3}", error.reason) else "unavailable"
            provider = planner.provider if planner.provider in {"gemini", "openai", "local"} else "disabled"
            logger.warning("planner_unavailable provider=%s reason=%s attempts=%d", provider, reason, error.attempts)
            if provider == "gemini":
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
        from .api_models import SearchParams
        params = SearchParams(query=query, cuisine=context.cuisine, min_price=context.min_price, max_price=context.max_price, limit=6)
        result = reader.search(params)
        context.last_query = query
        items = result["items"]
        traces.append({"name": "search_catalog", "arguments": params.model_dump(), "duration_ms": (perf_counter() - tool_started) * 1000, "result_count": len(items)})
        answer = f"Busquei “{query}” no catálogo real e encontrei {result['total_matches']:,} correspondências. Os cards abaixo preservam os nomes originais." if items else f"Não encontrei correspondências para “{query}” com esses filtros. Tente um nome mais simples ou amplie o limite de preço."
    return finish("ok" if items else "no_results", answer, items)
