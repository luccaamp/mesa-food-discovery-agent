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
from .privacy import redact

GREETING = re.compile(r"(?:oi|ola|bom dia|boa tarde|boa noite|hello|hi)[.!?\s]*")
INJECTION = re.compile(r"ignore.*(instruc|regra)|system prompt|execute.*(sql|python|codigo)|https?://")
PRICE_BOUND = re.compile(r"(?:ate|no maximo)\s*(\d+(?:[.,]\d+)?)")
PRICE_PHRASE = r"(?:ate|no maximo)\s*\d+(?:[.,]\d+)?(?:\s+unidades?(?:\s+normalizadas?)?)?"
# Price bands are relative to each cuisine ($ = cheapest third), so "barato" means something real.
MID_BAND = re.compile(r"\b(?:nao\s+(?:muito|tao)\s+car[oa]s?|preco\s+(?:medio|razoavel|justo)|not\s+too\s+expensive|mid[- ]range)\b")
LOW_BAND = re.compile(r"\b(?:(?:mais\s+)?barat(?:o|a|os|as|inho|inha|issimo|issima)|em\s+conta|economic[oa]s?|"
                      r"preco\s+baixo|menos\s+car[oa]s?|cheap(?:er|est)?|budget|affordable)\b")
ANY_BAND = re.compile(r"\b(?:qualquer\s+preco|pode\s+ser\s+car[oa]|sem\s+limite\s+de\s+preco|any\s+price)\b")
FILLER = {"algo", "alguma", "algum", "coisa", "opcao", "opcoes", "quero", "agora", "mais", "e", "um", "uma", "so", "mostre",
          "me", "tem", "outra", "outras", "something", "show", "options", "please", "por", "favor", "isso", "entao",
          "o", "que", "em", "alta", "aqui", "popular", "pedido", "pedem", "se", "pede", "what", "s", "here", "now"}
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
    redacted: list[str] | None = None  # kinds of personal data masked before any model call


def apply(message, context: AssistantContext) -> PolicyResult:
    message, redacted = redact(message)
    result = _apply(message, context)
    result.redacted = redacted or None
    return result


def price_band(text):
    """(level, text without the phrase): 1 for "barato", 2 for "não muito caro", 0 to clear, None if absent."""
    for pattern, level in ((ANY_BAND, 0), (MID_BAND, 2), (LOW_BAND, 1)):
        if pattern.search(text):
            return level, re.sub(r"\s+", " ", pattern.sub(" ", text)).strip()
    return None, text


def _region_aliases():
    from .context_popularity import REGION_NAMES
    aliases = {}
    for region, name in REGION_NAMES.items():
        for alias in name.split("/"):
            aliases[fold(alias.strip())] = region
    # Longest first, so "jurong west" wins over a shorter alias it contains.
    return sorted(aliases.items(), key=lambda pair: -len(pair[0]))


REGION_ALIASES = _region_aliases()


def region_mention(text):
    """(region, text without the phrase) for "estou em Tampines", "perto de Bedok", "in Woodlands"."""
    for alias, region in REGION_ALIASES:
        match = re.search(r"(?:\b(?:estou|to|i am|i'm)\s+)?(?:\b(?:em|no|na|perto\s+d[eoa]|near|in|at)\s+)?\b"
                          + re.escape(alias) + r"\b", text)
        if match:
            return region, re.sub(r"\s+", " ", text[:match.start()] + " " + text[match.end():]).strip(" ,.!?")
    return None, text


def _apply(message, context: AssistantContext) -> PolicyResult:
    context = context.model_copy(deep=True)
    region, without_region = region_mention(fold(message))
    if region:
        # The region the person names drives "em alta" and the local ranking of search results.
        message = without_region
        context.region = region
    level, without_band = price_band(fold(message))
    if level is not None:
        # "menos caro" and "não muito caro" are price requests, not exclusions of an ingredient.
        message = without_band
        context.price_level = level or None
        if level == 0:
            context.max_price = None
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
    only_price = level is not None and not set(re.findall(r"[^\W_]+", text)) - FILLER
    if only_price and context.last_query:
        return PolicyResult(context, planning_message=planning_message, planner="explicit_filter_refinement",
                            plan=IntentPlan(action="search_catalog", query=context.last_query))
    if only_price or (region and not set(re.findall(r"[^\W_]+", text)) - FILLER):
        return PolicyResult(context, planning_message=planning_message, planner="explicit_recommendation",
                            plan=IntentPlan(action="recommend_items", query=None))
    if EXPLICIT_RECOMMENDATION.fullmatch(text.strip()):
        return PolicyResult(context, planning_message=planning_message, planner="explicit_recommendation",
                            plan=IntentPlan(action="recommend_items", query=None))
    return PolicyResult(context, planning_message=planning_message)
