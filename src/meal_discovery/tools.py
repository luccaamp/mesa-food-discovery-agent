"""Read-only catalog tools shared by the planner, the agent and the MCP server.

Each tool returns real catalog rows plus a trace entry and a grounded,
template-built answer. No tool writes data or accepts SQL, code or URLs.
"""

from dataclasses import dataclass, field
from time import perf_counter

from .api_models import AssistantContext, SearchParams
from .context_popularity import rank_by_local_demand
from .discovery import guarded_constraint
from .observability import tool_span

DISCLOSURE = ("Catálogo histórico. Preço em faixas ($, $$, $$$) dentro de cada culinária: a base não publica moeda. "
              "Sem garantia de estoque, entrega ou composição alimentar.")
VAGUE_QUERY = ("Preciso de um nome de prato ou bebida mais específico, "
               "sem prometer restrições que o catálogo não comprova.")
CLARIFY = "Qual prato ou bebida você gostaria de explorar? Posso também sugerir itens pela popularidade histórica."
RESULT_LIMIT = 6
LOCAL_POOL = 50


@dataclass
class ToolOutcome:
    items: list = field(default_factory=list)
    trace: dict | None = None
    answer: str = ""
    rejected: bool = False  # arguments violated a policy; nothing was executed


def search(reader, context: AssistantContext, query: str) -> ToolOutcome:
    query = (query or "").strip()
    if not query or guarded_constraint(query) or len(query.split()) > 8:
        return ToolOutcome(answer=VAGUE_QUERY, rejected=True)
    started = perf_counter()
    # With a known region, fetch a wider BM25 pool and let local demand decide the order (Experiment "agent").
    pool = LOCAL_POOL if context.region else RESULT_LIMIT
    params = SearchParams(query=query, cuisine=context.cuisine, min_price=context.min_price,
                          max_price=context.max_price, price_level=context.price_level, limit=pool)
    with tool_span("search_catalog", filtered=context.max_price is not None or context.price_level is not None) as span:
        try:
            result = reader.search(params)
        except ValueError:  # e.g. a model-generated query with no searchable terms
            span.set_attribute("error.type", "invalid_query")
            return ToolOutcome(answer=VAGUE_QUERY, rejected=True)
        span.set_attribute("mesa.result_count", len(result["items"]))
    context.last_query = query
    items = result["items"]
    ranking = "bm25"
    if context.region:
        items = rank_by_local_demand(items, context.region)[:RESULT_LIMIT]
        ranking = "local_demand"
    trace = {"name": "search_catalog", "arguments": {**params.model_dump(), "ranking": ranking},
             "duration_ms": (perf_counter() - started) * 1000, "result_count": len(items)}
    if items:
        answer = (f"Busquei “{query}” no catálogo real e encontrei {result['total_matches']:,} correspondências. "
                  + ("Mostro primeiro as dos restaurantes mais pedidos na sua região neste horário."
                     if ranking == "local_demand" else "Os cards abaixo preservam os nomes originais."))
    else:
        answer = (f"Não encontrei correspondências para “{query}” com esses filtros. "
                  "Tente um nome mais simples ou amplie a faixa de preço.")
    return ToolOutcome(items=items, trace=trace, answer=answer)


def recommend(recommender, context: AssistantContext) -> ToolOutcome:
    started = perf_counter()
    args = {"seeds": [item.model_dump() for item in context.selected_items], "cuisine": context.cuisine,
            "min_price": context.min_price, "max_price": context.max_price, "price_level": context.price_level,
            "limit": RESULT_LIMIT}
    if context.region:
        args["region"] = context.region
    with tool_span("recommend_items", seeds=len(context.selected_items)) as span:
        result = recommender(args)
        span.set_attribute("mesa.result_count", len(result["items"]))
    items = result["items"]
    trace = {"name": "recommend_items", "arguments": args,
             "duration_ms": (perf_counter() - started) * 1000, "result_count": len(items)}
    if not items:
        answer = ("Não encontrei sugestões com esses filtros. "
                  "Amplie a faixa de preço ou escolha outra culinária.")
    elif items[0].get("reason") == "popular_here":
        here = result.get("context") or {}
        place = f"em {here['region']['name']}" if here.get("region") else "em Singapura"
        answer = (f"Sem itens selecionados, estes são os mais pedidos {place} "
                  f"{here.get('slot_label', 'neste horário')}, segundo pedidos reais.")
    elif any(item.get("reason") == "basket_association" for item in items):
        answer = ("Estas sugestões usam associações de compra dos itens que você selecionou, "
                  "com complemento por popularidade histórica.")
    elif context.selected_items:
        answer = ("Não encontrei associações para os itens selecionados com esses filtros. "
                  "As opções disponíveis seguem a popularidade histórica dos pedidos de treino.")
    else:
        answer = "Sem itens selecionados, estas sugestões seguem a popularidade histórica dos pedidos de treino."
    return ToolOutcome(items=items, trace=trace, answer=answer)
