"""Bounded scripted user profiles, real HTTP turns and independent SQLite oracles.

This is an objective contract runner, not an LLM user simulator or opinion judge.
No commercial endpoint is accepted. Inspect is used separately for judge calibration.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics
from time import perf_counter
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from meal_discovery.catalog import catalog_item, catalog_metadata
from meal_discovery.dataset import file_hash
from meal_discovery.discovery import fold


def endpoint(value):
    parsed = urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password or parsed.path not in {"", "/"}
            or parsed.query or parsed.fragment):
        raise ValueError("This local protocol accepts only loopback HTTP without credentials")
    return value.rstrip("/")


def validate_suite(suite):
    cases = suite["cases"]
    if not cases or len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Scenario identifiers must be nonempty and unique")
    for case in cases:
        if not 1 <= len(case["turns"]) <= 4:
            raise ValueError("A scenario must have one to four bounded turns")
        for turn in case["turns"]:
            if not turn["message"].strip() or turn["tool"] not in {None, "search_catalog", "recommend_items"}:
                raise ValueError("Invalid scripted action")
            if turn["tool"] == "search_catalog" and not turn.get("concepts"):
                raise ValueError("Search needs independently declared intent concepts")
    return cases


def verify_turn(turn, result, previous, source_item):
    """Return named failures; no opinion score can cancel a factual failure."""
    errors = []
    tools = result["tools"]
    items = result["items"]
    expected = turn["tool"]
    if [tool["name"] for tool in tools] != ([expected] if expected else []):
        errors.append("expected_tool")
    if result["status"] != turn.get("status", "ok"):
        errors.append("expected_status")
    if expected and not items and turn.get("status", "ok") == "ok":
        errors.append("nonempty_results")
    if not expected and items:
        errors.append("clarification_without_items")
    if not result.get("warnings") or not any("normaliz" in fold(w) and "histor" in fold(w) for w in result["warnings"]):
        errors.append("source_and_price_disclosure")
    context = result["context"]
    if turn.get("preserve_query") and context["last_query"] != previous.get("last_query"):
        errors.append("query_continuity")
    for key, value in turn.get("context_equals", {}).items():
        if context.get(key) != value:
            errors.append("context_" + key)
    if expected == "search_catalog" and tools:
        query = fold(tools[0]["arguments"].get("query", ""))
        if not all(any(term in query.split() for term in alternatives) for alternatives in turn["concepts"]):
            errors.append("dish_intent")
        for term in turn.get("excluded_query_terms", []):
            if term in query.split():
                errors.append("stale_intent")
    seeds = {(item["vendor_id"], item["product_id"]) for item in previous.get("selected_items", [])}
    seen = set()
    for item in items:
        identity = (item["vendor_id"], item["product_id"])
        reference = source_item(*identity)
        if reference is None or any(item.get(key) != reference.get(key) for key in
                                    ("vendor_id", "product_id", "name", "unit_price", "primary_cuisine")):
            errors.append("catalog_identity_and_fields")
        if identity in seen:
            errors.append("duplicate_item")
        seen.add(identity)
        if expected == "recommend_items":
            if identity in seeds:
                errors.append("seed_exclusion")
            if item.get("reason") not in {"basket_association", "historical_popularity"}:
                errors.append("recommendation_evidence")
            if not isinstance(item.get("training_baskets"), int) or item["training_baskets"] < 1:
                errors.append("training_evidence")
        price = item.get("unit_price")
        for bound, relation in (("min_price", lambda p, b: p >= b), ("max_price", lambda p, b: p <= b)):
            if context.get(bound) is not None and (price is None or not relation(price, context[bound])):
                errors.append(bound)
        if context.get("cuisine") and item["primary_cuisine"] != context["cuisine"]:
            errors.append("cuisine_filter")
    return sorted(set(errors))


def reliability(rows, k):
    grouped = {}
    for row in rows:
        grouped.setdefault(row["id"], []).append(row["passed"])
    eligible = [values for values in grouped.values() if len(values) >= k]
    return (statistics.mean(math.comb(sum(values), k) / math.comb(len(values), k)
                            for values in eligible) if eligible else None)


def run(base, suite_path, index, repetitions, output):
    base = endpoint(base)
    if output.exists():
        raise ValueError("Choose a new immutable report path")
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    cases = validate_suite(suite)
    provenance = catalog_metadata(index)
    if provenance["data_kind"] != "official_dhrd":
        raise ValueError("Official source catalog required")

    def request(path, body=None):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        with urlopen(Request(base + path, data=data, headers={"Content-Type": "application/json"}), timeout=45) as response:
            return json.load(response)

    system = request("/v1/system")
    if system["assistant"]["provider"] != "local" or not system["assistant"]["available"]:
        raise ValueError("Healthy local model required; fallback is not inference evidence")
    remote_meta = request("/v1/catalog/meta")
    if remote_meta["source_database_sha256"] != provenance["source_database_sha256"]:
        raise ValueError("HTTP and oracle source databases differ")
    rows = []
    report = {"schema_version": 1, "kind": "scripted_behavioral_profiles_real_local_http",
              "created_at": datetime.now(timezone.utc).isoformat(), "complete": False,
              "suite_sha256": file_hash(suite_path), "suite": suite,
              "source_database_sha256": provenance["source_database_sha256"],
              "catalog_sha256": file_hash(index), "runner_sha256": file_hash(Path(__file__)),
              "implementation_sha256": {name: file_hash(Path("src/meal_discovery") / name)
                                          for name in ("assistant.py", "api.py", "serving.py", "discovery.py")},
              "prompt_sha256": file_hash(Path("src/meal_discovery/prompts/intent_v1.txt")),
              "model_configuration": json.loads(Path("configs/local-llm-v1.json").read_text(encoding="utf-8")),
              "official_test_orders_used": False, "commercial_api_calls": 0,
              "qualitative_judge": "unscored; no qualified judge", "episodes": rows,
              "limitations": "Scripted AI-authored behavioral contracts, not free-form LLM simulation, human preference or population estimates. Development cases are not held out."}
    output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        report["summary"] = {"episodes": len(rows), "passed": sum(row["passed"] for row in rows),
                             "pass_power_1": reliability(rows, 1), "pass_power_3": reliability(rows, 3),
                             "failure_counts": dict(Counter(error for row in rows for turn in row["turns"] for error in turn["errors"])),
                             "llm_calls": sum(turn["planner"] == "local_llm" for row in rows for turn in row["turns"]),
                             "fallback_turns": sum(turn["planner"] == "glossary_fallback" for row in rows for turn in row["turns"])}
        # Keep completed evidence even if a subsequent request fails.
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def source_item(vendor, product):
        found = catalog_item(index, vendor, product)
        return found["item"] if found else None

    try:
        for case in cases:
            for repetition in range(repetitions):
                context = dict(case.get("context", {}))
                turns = []
                for turn in case["turns"]:
                    started = perf_counter()
                    result = request("/v1/assistant", {"message": turn["message"], "context": context})
                    errors = verify_turn(turn, result, context, source_item)
                    if result["planner"] == "glossary_fallback":
                        errors.append("unexpected_model_fallback")
                    turns.append({"message": turn["message"], "errors": errors,
                                  "planner": result["planner"], "response": result,
                                  "http_ms": round((perf_counter() - started) * 1000, 2)})
                    context = result["context"]
                rows.append({"id": case["id"], "profile": case["profile"], "repetition": repetition,
                             "passed": not any(turn["errors"] for turn in turns), "turns": turns})
                save()
                print(json.dumps({"id": case["id"], "repetition": repetition, "passed": rows[-1]["passed"]}), flush=True)
        report["complete"] = True
    finally:
        save()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--suite", type=Path, default=Path("configs/conversation-development-v1.json"))
    parser.add_argument("--index", type=Path, default=Path("data/processed/singapore-catalog-v1.sqlite"))
    parser.add_argument("--repetitions", type=int, choices=(1, 3), default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.base_url, args.suite, args.index, args.repetitions, args.output)
    print(json.dumps(result["summary"], indent=2))
    raise SystemExit(0 if result["summary"]["passed"] == result["summary"]["episodes"] else 1)
