"""Does the LLM agent help a new customer find what they really ordered? Same question as Experiment 004.

Protocol: configs/agent-discovery-v1.json, frozen before running. For each new customer of the official
DHRD test file, a code-generated Portuguese message states the cuisine of their real order (and "barato"
when the order was in the cheapest price band). The message never contains an item or restaurant name.
Five arms show 5 items each; a hit means the real restaurant (or item) is among them.

Run (needs GROQ_API_KEY for the LLM arms; --no-llm runs only the deterministic arms):
  python analysis/agent_experiment.py
"""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from time import perf_counter, sleep
from unittest.mock import patch

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))
from discovery_experiment import SLOT_EDGES, SLOT_NAMES, TEST_FILE, bootstrap  # noqa: E402

CONFIG = ROOT / "configs/agent-discovery-v1.json"
CATALOG = ROOT / "data/processed/singapore-catalog-v1.sqlite"
DATABASE = ROOT / "data/processed/singapore-official-v1.sqlite"
SHOWN = 5
# How a person would say each cuisine in Portuguese; dishes keep their usual name.
CUISINE_PT = {
    "chinese": "comida chinesa", "noodles": "macarrão oriental", "bubble tea": "bubble tea", "indian": "comida indiana",
    "western": "comida ocidental", "dessert": "uma sobremesa", "japanese": "comida japonesa", "coffee": "um café",
    "pizza": "pizza", "rice dishes": "um prato com arroz", "singaporean": "comida de Singapura", "chicken": "frango",
    "thai": "comida tailandesa", "sandwiches": "um sanduíche", "cakes": "bolo", "soups": "uma sopa",
    "fried chicken": "frango frito", "burgers": "hambúrguer", "beverages": "uma bebida", "chicken rice": "arroz com frango",
    "mala xiang guo": "mala xiang guo", "seafood": "frutos do mar", "sushi": "sushi", "korean": "comida coreana",
    "dim sum": "dim sum", "american": "comida americana", "bakery": "algo de padaria", "fried rice": "arroz frito",
    "pasta": "massa", "healthy": "algo saudável", "ramen": "ramen", "snacks": "um lanche", "vegetarian": "comida vegetariana",
    "nasi lemak": "nasi lemak", "malaysian": "comida malaia", "asian": "comida asiática", "mexican": "comida mexicana",
    "ayam penyet": "ayam penyet", "italian": "comida italiana", "indonesian": "comida indonésia", "curry": "curry",
    "yong tau foo": "yong tau foo", "roti prata": "roti prata", "vietnamese": "comida vietnamita", "porridge": "mingau de arroz",
    "grill": "grelhados", "bak kut teh": "bak kut teh", "international": "comida internacional", "tea": "chá", "pho": "pho",
    "fries": "batata frita", "fish soup": "sopa de peixe", "acai bowl": "açaí", "wraps": "um wrap", "salads": "salada",
    "donut": "donut", "pancakes and waffles": "panqueca ou waffle", "laksa": "laksa", "filipino": "comida filipina",
    "hokkien mee": "hokkien mee", "ban mian": "ban mian", "satay": "satay", "mediterranean": "comida mediterrânea",
    "german": "comida alemã", "french": "comida francesa", "turkish": "comida turca", "chicken wings": "asinhas de frango",
    "middle eastern": "comida do Oriente Médio", "kaya toast": "kaya toast", "spanish": "comida espanhola",
    "mala soups": "sopa mala", "ice cream": "sorvete", "greek": "comida grega", "grain bowl": "um bowl de grãos",
    "fast food": "fast food", "shawarma": "shawarma", "lebanese": "comida libanesa", "halal": "comida halal",
}


def slot_name(hour):
    return next(name for name, last in zip(SLOT_NAMES, SLOT_EDGES[1:]) if hour <= last)


def message_for(cuisine, cheap):
    return f"Estou com vontade de {CUISINE_PT.get(cuisine, cuisine)}" + (", algo barato" if cheap else "")


def load_cases():
    """New customers of the official test file, their first order, region, slot and generated message."""
    from meal_discovery.pricing import price_band
    connection = sqlite3.connect(DATABASE.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        known = {row[0] for row in connection.execute("SELECT DISTINCT customer_id FROM orders")}
        vendors = dict(connection.execute("SELECT vendor_id, primary_cuisine FROM vendors"))
        prices = {}
        for vendor, product, price in connection.execute("SELECT vendor_id, product_id, unit_price FROM products"):
            prices[(vendor, product)] = price
        popularity = Counter()
        rows = connection.execute("""SELECT c.geohash, CAST(substr(o.order_time,1,2) AS INTEGER), i.vendor_id
                                     FROM orders o JOIN order_context c USING(order_id)
                                     JOIN (SELECT DISTINCT order_id, vendor_id FROM order_items) i USING(order_id)""")
        for geohash, hour, vendor in rows:
            popularity[(geohash, slot_name(hour), vendor)] += 1
    finally:
        connection.close()
    raw = pd.read_csv(TEST_FILE, usecols=["customer_id", "geohash", "order_id", "vendor_id", "product_id", "order_time",
                                          "order_day"], dtype=str)
    raw["day"] = raw.order_day.str.extract(r"(\d+)")[0].astype(int)
    raw = raw.sort_values(["day", "order_time", "order_id"], kind="stable")
    first = raw.drop_duplicates("customer_id")[["customer_id", "order_id", "geohash", "vendor_id", "order_time"]]
    first = first[~first.customer_id.isin(known)]
    basket = raw[raw.order_id.isin(first.order_id)].groupby("order_id").product_id.apply(set)
    cases = []
    for row in first.itertuples():
        items = {(row.vendor_id, product) for product in basket[row.order_id]}
        cuisine = vendors.get(row.vendor_id)
        if cuisine is None:
            continue
        levels = [price_band(prices.get(item), cuisine)["level"] for item in items]
        levels = [level for level in levels if level]
        cheap = bool(levels) and max(levels) == 1
        slot = slot_name(int(row.order_time[:2]))
        cases.append({"customer": row.customer_id, "region": row.geohash, "slot": slot, "vendor": row.vendor_id,
                      "cuisine": cuisine, "items": items, "message": message_for(cuisine, cheap), "cheap": cheap})
    return cases, popularity


def score(shown, case):
    shown = shown[:SHOWN]
    return {"restaurant_hit": any(item["vendor_id"] == case["vendor"] for item in shown),
            "item_hit": any((item["vendor_id"], item["product_id"]) in case["items"] for item in shown),
            "cuisine_match": (sum(item["primary_cuisine"] == case["cuisine"] for item in shown) / len(shown)) if shown else 0.0,
            "empty": not shown}


class Arms:
    def __init__(self, popularity):
        from meal_discovery.api import CatalogReader
        self.reader = CatalogReader(CATALOG)
        self.popularity = popularity
        self.cache = {}

    def home(self, case):
        from meal_discovery.context_popularity import recommend_here
        key = ("home", case["region"], case["slot"])
        if key not in self.cache:
            self.cache[key] = recommend_here(CATALOG, region=case["region"], slot=case["slot"], limit=SHOWN)["items"]
        return self.cache[key]

    def candidates(self, query, price_level=None):
        """BM25 top 50 for a query exactly as the product search runs it (glossary, guarded constraints)."""
        from meal_discovery.discovery import discover
        key = ("search", query, price_level)
        if key not in self.cache:
            try:
                result = discover(CATALOG, query, price_level=price_level, limit=50)
                self.cache[key] = (result["result"] or {}).get("items", [])
            except ValueError:
                self.cache[key] = []
        return self.cache[key]

    def local(self, items, case):
        """Reorder candidates by how often their restaurant is ordered in this region and time slot."""
        weight = lambda item: self.popularity[(case["region"], case["slot"], item["vendor_id"])]  # noqa: E731
        return sorted(items, key=lambda item: -weight(item))  # stable: BM25 order breaks ties


def run_agent_arm(case, client):
    from meal_discovery.context_popularity import SLOT_LABELS
    assert case["slot"] in SLOT_LABELS
    with patch("meal_discovery.context_popularity.slot_at", return_value=case["slot"]):
        started = perf_counter()
        response = client.post("/v1/agent", json={"message": case["message"], "context": {"region": case["region"]}})
        elapsed = perf_counter() - started
    body = response.json()
    search = next((tool["arguments"] for tool in reversed(body.get("tools", [])) if tool["name"] == "search_catalog"), None)
    return body, search, elapsed


def summarize(rows, rng):
    result = {}
    for metric in ("restaurant_hit", "item_hit", "cuisine_match", "empty"):
        values = np.array([float(row[metric]) for row in rows])
        result[metric] = {"mean": round(float(values.mean()), 5), "ci95": bootstrap(values, rng)}
    result["cases"] = len(rows)
    return result


def paired(first, second, metric, rng):
    delta = np.array([float(a[metric]) - float(b[metric]) for a, b in zip(first, second)])
    return {"difference": round(float(delta.mean()), 5), "ci95": bootstrap(delta, rng)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--pause", type=float, default=4.0, help="Seconds between agent calls (provider rate limit)")
    args = parser.parse_args()
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    cases, popularity = load_cases()
    arms = Arms(popularity)
    rng = np.random.default_rng(config["llm_sample"]["seed"])
    full = defaultdict(list)
    def searches(case):
        level = 1 if case["cheap"] else None
        portuguese = arms.candidates(CUISINE_PT.get(case["cuisine"], case["cuisine"]), level)
        english = arms.candidates(case["cuisine"], level)
        return {"search_pt": portuguese, "search_pt_local": arms.local(portuguese, case),
                "search_en": english, "search_en_local": arms.local(english, case)}

    for case in cases:
        full["home"].append(score(arms.home(case), case))
        for arm, shown in searches(case).items():
            full[arm].append(score(shown, case))
    print(json.dumps({arm: summarize(rows, rng)["restaurant_hit"] for arm, rows in full.items()}), flush=True)
    sample_index = sorted(np.random.default_rng(config["llm_sample"]["seed"]).choice(len(cases), config["llm_sample"]["size"],
                                                                                      replace=False))
    sample = defaultdict(list)
    llm = {"calls": 0, "tokens": 0, "seconds": [], "fallbacks": 0, "tools": Counter()}
    if not args.no_llm:
        from fastapi.testclient import TestClient
        from meal_discovery.api import create_app
        client = TestClient(create_app(CATALOG))
        for number, index in enumerate(sample_index, start=1):
            case = cases[index]
            body, search, elapsed = run_agent_arm(case, client)
            items = body.get("items", [])
            local = arms.local(arms.candidates(search["query"], search.get("price_level")), case) if search else items
            for arm, rows in (("home", arms.home(case)), *searches(case).items(), ("agent", items), ("agent_local", local)):
                sample[arm].append(score(rows, case))
            llm["calls"] += body.get("usage", {}).get("provider_attempts", 0) or 0
            llm["tokens"] += body.get("usage", {}).get("total_tokens", 0) or 0
            llm["seconds"].append(elapsed)
            llm["fallbacks"] += bool(body.get("fallback_reason"))
            llm["tools"].update(tool["name"] for tool in body.get("tools", []))
            print(f"{number}/{len(sample_index)} {body.get('planner')} tools={[t['name'] for t in body.get('tools', [])]}",
                  flush=True)
            sleep(args.pause)
    result = {"schema_version": 1, "protocol_version": config["protocol_version"],
              "protocol_sha256": hashlib.sha256(CONFIG.read_bytes()).hexdigest(),
              "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "provider": os.environ.get("LLM_PROVIDER"), "model": os.environ.get("GROQ_MODEL") or os.environ.get("LLM_MODEL"),
              "cases": {"new_customers": len(cases), "llm_sample": len(sample_index) if sample else 0},
              "arms": {"all_new_customers": {arm: summarize(rows, rng) for arm, rows in full.items()},
                       "llm_sample": {arm: summarize(rows, rng) for arm, rows in sample.items()}},
              "paired_on_llm_sample": {f"{a}_vs_{b}": {m: paired(sample[a], sample[b], m, rng)
                                                       for m in ("restaurant_hit", "cuisine_match", "empty")}
                                       for a, b in (("agent", "search_pt"), ("agent", "search_en"), ("agent_local", "home"),
                                                    ("agent_local", "agent"), ("search_en_local", "search_en"))}
                                       if sample else {},
              "llm_usage": {"provider_attempts": llm["calls"], "tokens": llm["tokens"], "fallbacks": llm["fallbacks"],
                            "tools": dict(llm["tools"]),
                            "latency_seconds_p50": round(float(np.median(llm["seconds"])), 2) if llm["seconds"] else None},
              "messages_example": sorted({case["message"] for case in cases})[:8],
              "limitations": config["limitations"]}
    output = ROOT / "evaluations/results/agent-discovery-v1.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("cases", "arms", "paired_on_llm_sample", "llm_usage")}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
