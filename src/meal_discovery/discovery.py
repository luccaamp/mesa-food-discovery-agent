"""Explicit bounded bilingual lexical expansion; no dietary or ingredient inference."""

import re
import unicodedata

from .catalog import search_catalog

GLOSSARY_VERSION = "pt-en-menu-glossary-v2"
WORDS = {
    "arroz": "rice", "frango": "chicken", "galinha": "chicken", "carne": "beef", "bovina": "beef",
    "macarrao": "noodles", "massa": "pasta", "queijo": "cheese", "cha": "tea", "leite": "milk",
    "cafe": "coffee", "gelado": "iced", "gelada": "iced", "hamburguer": "burger",
    "peixe": "fish", "camarao": "prawn", "ovo": "egg", "ovos": "egg", "porco": "pork",
    "sopa": "soup", "salada": "salad", "batata": "potato", "fritas": "fries",
    "chocolate": "chocolate", "morango": "strawberry", "manga": "mango", "suco": "juice",
    "agua": "water", "coco": "coconut", "frito": "fried", "frita": "fried", "assado": "roasted",
    "grelhado": "grilled", "picante": "spicy", "sorvete": "ice cream", "sobremesa": "dessert",
    "sanduiche": "sandwich", "pizza": "pizza", "sushi": "sushi", "bacon": "bacon",
}
STOPWORDS = {"de", "do", "da", "com", "um", "uma", "e", "o", "a", "os", "as", "quero", "gostaria", "por", "favor", "procuro", "buscar",
             "algo", "comer", "beber", "tomar", "prato", "bebida", "bebidas", "opcao", "opcoes", "please"}


def fold(text):
    return "".join(char for char in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(char))


def guarded_constraint(message):
    text = fold(message)
    if re.search(r"alerg|allerg|intoler|celiac|coeliac|sem\s+(gluten|lactose|amendoim)|vegano|vegan|vegetarian|sem\s+carne|without|free\s+of|\b(?:gluten|lactose|dairy|egg|nut|peanut)[-\s]+free\b|\bno\s+(?:nuts?|peanuts?|dairy|eggs?|gluten|lactose)\b", text):
        return "O catálogo não informa ingredientes completos nem certificações alimentares. Não consigo garantir essa restrição. Posso buscar pelo nome de um prato, mas a composição precisa ser confirmada com o estabelecimento."
    if re.search(r"r\$|\breais\b|\breal\b|\bdolares\b|\bdollars\b", text):
        return "Os preços desta base são normalizados e não têm moeda. Não posso converter um orçamento em reais. Use os filtros de preço normalizado para comparar itens do catálogo."
    if re.search(r"\bsem\b|\bnao\b|\bmenos\b", text):
        return "Essa preferência envolve excluir algo. O catálogo não permite confirmar ingredientes ausentes. Diga o nome do prato que deseja explorar; mantenho essa limitação explícita."
    return None


def expand_query(query):
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 200:
        raise ValueError("Query must contain 1 to 200 characters")
    normalized = fold(query)
    # Only a leading conversational switch is removable, never a negation or
    # arbitrary unknown menu token. Keep the glossary deterministic and bounded.
    normalized = re.sub(r"^\s*agora\s+(?:eu\s+)?(?:quero|prefiro|procuro)\s+", "", normalized)
    # Strip only anchored search framing; unknown food terms stay in the query.
    normalized = re.sub(r"^\s*(?:(?:eu\s+)?gostaria\s+de\s+|quero\s+)?(?:encontrar|buscar|procurar)\s+", "", normalized)
    normalized = re.sub(r"\s+no\s+catalogo[.!?]*\s*$", "", normalized)
    tokens = re.findall(r"[^\W_]+", normalized)
    if any(token in {"sem", "nao", "without", "except"} for token in tokens):
        return query, False
    if not any(token in WORDS for token in tokens):
        return query, False
    expanded = []
    for token in tokens:
        if token not in STOPWORDS:
            expanded.extend(WORDS.get(token, token).split())
    return " ".join(dict.fromkeys(expanded)) or query, True


def discover(index, query, *, cuisine=None, min_price=None, max_price=None, limit=10, allow_test_data=False):
    warning = guarded_constraint(query)
    if warning:
        # Constraints are not silently stripped to force a match.
        return {"status": "needs_clarification", "message": warning, "query": query, "resolved_query": None,
                "expansion_version": GLOSSARY_VERSION, "result": None}
    resolved, changed = expand_query(query)
    result = search_catalog(index, resolved, cuisine=cuisine, min_price=min_price, max_price=max_price,
                            limit=limit, allow_test_data=allow_test_data)
    return {"status": "ok", "message": "Busca por termos do catálogo, com expansão explícita de vocabulário." if changed else "Busca textual no catálogo.",
            "query": query, "resolved_query": resolved, "expansion_version": GLOSSARY_VERSION, "result": result}
