"""Deterministic conversation policies that run before any language model.

They refuse guarantees the catalog cannot support (allergens, diets),
deflect instruction-injection attempts, answer greetings and apply explicit
price refinements. Every assistant mode (planner or agent) applies the same
policies, so a model never sees a message these rules already answered.
"""

from dataclasses import dataclass
import math
import re

from .api_models import AssistantContext, IntentPlan
from .discovery import fold, guarded_constraint

GREETING = re.compile(r"(?:oi|ola|bom dia|boa tarde|boa noite|hello|hi)[.!?\s]*")
INJECTION = re.compile(r"ignore.*(instruc|regra)|system prompt|execute.*(sql|python|codigo)|https?://")
PRICE_BOUND = re.compile(r"(?:ate|no maximo)\s*(\d+(?:[.,]\d+)?)")
PRICE_PHRASE = r"(?:ate|no maximo)\s*\d+(?:[.,]\d+)?(?:\s+unidades?(?:\s+normalizadas?)?)?"
EXPLICIT_RECOMMENDATION = re.compile(
    r"(?:me )?(?:recomende|sugira|mostre)(?: me)? (?:algo|sugestoes|recomendacoes|opcoes)"
    r"(?: (?:para mim|da minha selecao|com os itens selecionados))?[.!?]*")

GREETING_ANSWER = ("Olá! Qual prato ou bebida você gostaria de explorar? "
                   "Também posso sugerir itens pela popularidade histórica.")
INJECTION_ANSWER = "Posso explorar pratos e bebidas do catálogo. Diga o que você gostaria de buscar."


@dataclass
class PolicyResult:
    context: AssistantContext
    answer: str | None = None          # set when a policy fully answered the turn
    planning_message: str = ""         # message with structured parts (price) removed
    plan: IntentPlan | None = None     # set when the action is explicit, no model needed
    planner: str | None = None         # name of the deterministic rule that chose the plan


def apply(message, context: AssistantContext) -> PolicyResult:
    context = context.model_copy(deep=True)
    constraint = guarded_constraint(message)
    if constraint:
        return PolicyResult(context, answer=constraint)
    text = fold(message)
    if GREETING.fullmatch(text.strip()):
        return PolicyResult(context, answer=GREETING_ANSWER)
    if INJECTION.search(text):
        return PolicyResult(context, answer=INJECTION_ANSWER)
    # A refinement changes only the explicit normalized bound and retains the last dish.
    bound = PRICE_BOUND.search(text)
    if bound:
        context.max_price = float(bound.group(1).replace(",", "."))
        if not math.isfinite(context.max_price):
            return PolicyResult(context, answer="Use um limite finito de preço normalizado.")
        if context.min_price is not None and context.min_price > context.max_price:
            return PolicyResult(context, answer="O preço máximo ficou abaixo do mínimo. "
                                                "Ajuste os limites de preço normalizado.")
    # Price is already represented structurally. Do not make it a required menu token
    # when a new dish and an explicit bound arrive in the same message.
    planning_message = re.sub(PRICE_PHRASE, "", text).strip() if bound else message
    if bound and re.fullmatch(PRICE_PHRASE + r"[.!?\s]*", text.strip()) and context.last_query:
        return PolicyResult(context, planning_message=planning_message, planner="explicit_filter_refinement",
                            plan=IntentPlan(action="search_catalog", query=context.last_query))
    if EXPLICIT_RECOMMENDATION.fullmatch(text.strip()):
        return PolicyResult(context, planning_message=planning_message, planner="explicit_recommendation",
                            plan=IntentPlan(action="recommend_items", query=None))
    return PolicyResult(context, planning_message=planning_message)
