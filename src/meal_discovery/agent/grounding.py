"""Accept the model's closing sentence only when it cannot mislead.

Items, names and prices are shown from tool results, so the reply must not
add facts of its own. This check is deliberately strict: when in doubt the
agent falls back to a template answer built from the tool result.
"""

import re

MAX_CHARS = 400
CURRENCY = re.compile(r"R\$|US\$|S\$|\$|€|£|\b(?:reais|real|d[oó]lar(?:es)?|dollars?|sgd|usd|brl)\b", re.IGNORECASE)
URL = re.compile(r"https?://|www\.", re.IGNORECASE)
NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
CLAIMS = re.compile(r"\b(?:sem (?:gl[uú]ten|lactose|al[eé]rg)|gluten[- ]free|allergen|al[eé]rgeno|vegan[oa]?|"
                    r"saud[aá]vel|healthy|em estoque|in stock|entrega|delivery)\b", re.IGNORECASE)


def grounded_reply(text, items, context):
    if not text:
        return None
    text = text.strip()
    if not text or len(text) > MAX_CHARS or CURRENCY.search(text) or URL.search(text) or CLAIMS.search(text):
        return None
    allowed = {f"{value:g}" for value in (context.max_price, context.min_price) if value is not None}
    allowed |= {f"{item['unit_price']:g}" for item in items if item.get("unit_price") is not None}
    for number in NUMBER.findall(text):
        normalized = number.replace(",", ".")
        if "." not in normalized and int(normalized) <= 10:
            continue  # small counts ("2 opções") are not catalog facts
        if f"{float(normalized):g}" not in allowed:
            return None
    return text
