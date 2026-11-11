"""Read-only catalog tools shared by the planner, the agent and the MCP server.

Each tool returns real catalog rows plus a trace entry and a grounded,
template-built answer. No tool writes data or accepts SQL, code or URLs.
"""

from dataclasses import dataclass, field
from time import perf_counter

from .api_models import AssistantContext, SearchParams
from .discovery import guarded_constraint

DISCLOSURE = ("Catálogo histórico. Preços normalizados, sem moeda. "
              "Sem garantia de estoque, entrega ou composição alimentar.")
VAGUE_QUERY = ("Preciso de um nome de prato ou bebida mais específico, "
               "sem prometer restrições que o catálogo não comprova.")
CLARIFY = "Qual prato ou bebida você gostaria de explorar? Posso também sugerir itens pela popularidade histórica."
RESULT_LIMIT = 6


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
    params = SearchParams(query=query, cuisine=context.cuisine, min_price=context.min_price,
                          max_price=context.max_price, limit=RESULT_LIMIT)
    result = reader.search(params)
    context.last_query = query
    items = result["items"]
    trace = {"name": "search_catalog", "arguments": params.model_dump(),
             "duration_ms": (perf_counter() - started) * 1000, "result_count": len(items)}
    if items:
        answer = (f"Busquei “{query}” no catálogo real e encontrei {result['total_matches']:,} correspondências. "
                  "Os cards abaixo preservam os nomes originais.")
    else:
        answer = (f"Não encontrei correspondências para “{query}” com esses filtros. "
                  "Tente um nome mais simples ou amplie o limite de preço.")
    return ToolOutcome(items=items, trace=trace, answer=answer)


def recommend(recommender, context: AssistantContext) -> ToolOutcome:
    started = perf_counter()
    args = {"seeds": [item.model_dump() for item in context.selected_items], "cuisine": context.cuisine,
            "min_price": context.min_price, "max_price": context.max_price, "limit": RESULT_LIMIT}
    result = recommender(args)
    items = result["items"]
    trace = {"name": "recommend_items", "arguments": args,
             "duration_ms": (perf_counter() - started) * 1000, "result_count": len(items)}
    if not items:
        answer = ("Não encontrei sugestões com esses filtros. "
                  "Amplie o intervalo de preço normalizado ou escolha outra culinária.")
    elif any(item.get("reason") == "basket_association" for item in items):
        answer = ("Estas sugestões usam associações de compra dos itens que você selecionou, "
                  "com complemento por popularidade histórica.")
    elif context.selected_items:
        answer = ("Não encontrei associações para os itens selecionados com esses filtros. "
                  "As opções disponíveis seguem a popularidade histórica dos pedidos de treino.")
    else:
        answer = "Sem itens selecionados, estas sugestões seguem a popularidade histórica dos pedidos de treino."
    return ToolOutcome(items=items, trace=trace, answer=answer)
