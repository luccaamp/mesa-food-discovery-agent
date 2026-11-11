"""Compare assistant modes and LLM providers on the same objective contracts.

Runs the frozen development conversation suite in-process against the real
official catalog, for each (mode, provider) pair:

  mode      planner  one structured planning call, tools chosen by code
            agent    LangGraph agent, the model chooses tools (tool calling)
  provider  gemini | groq | local

Every turn is checked by `conversation_suite.verify_turn` (tool choice, dish
intent, filters, continuity, catalog identity of every item). The report adds
latency percentiles, model calls and tokens. Quota errors from free tiers are
waited out and retried; those retries are counted, never hidden.

Free tiers only: no paid endpoint is called.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import statistics
import sys
from time import perf_counter, sleep

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conversation_suite import validate_suite, verify_turn  # noqa: E402

from meal_discovery.agent import run_agent  # noqa: E402
from meal_discovery.api import CatalogReader  # noqa: E402
from meal_discovery.api_models import AssistantContext, AssistantRequest, RecommendationParams  # noqa: E402
from meal_discovery.assistant import run_assistant  # noqa: E402
from meal_discovery.catalog import catalog_item, catalog_metadata  # noqa: E402
from meal_discovery.dataset import file_hash  # noqa: E402
from meal_discovery.llm import build  # noqa: E402
from meal_discovery.planner import IntentPlanner  # noqa: E402
from meal_discovery.serving import recommend  # noqa: E402

MODELS = {"gemini": "gemini-3.1-flash-lite", "groq": "openai/gpt-oss-120b", "local": "meal-local"}


def percentile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def run_pair(mode, provider, cases, reader, recommender, source_item, quota_wait):
    chat_model = build(provider, MODELS[provider])
    rows, retries = [], 0
    for case in cases:
        context = AssistantContext(**case.get("context", {}))
        turns = []
        for turn in case["turns"]:
            request = AssistantRequest(message=turn["message"], context=context)
            for attempt in range(4):
                started = perf_counter()
                if mode == "agent":
                    result = run_agent(request, reader, recommender, chat_model=chat_model)
                else:
                    result = run_assistant(request, reader, recommender, planner=IntentPlanner(chat_model))
                elapsed = (perf_counter() - started) * 1000
                if result.get("fallback_reason") == "quota" and attempt < 3:
                    retries += 1
                    sleep(quota_wait)
                    continue
                break
            errors = verify_turn(turn, result, context.model_dump(), source_item)
            if result["planner"] == "glossary_fallback":
                errors.append("unexpected_model_fallback")
            usage = result.get("usage") or {}
            turns.append({"message": turn["message"], "errors": sorted(set(errors)), "planner": result["planner"],
                          "tools": [(t["name"], t["arguments"].get("query")) for t in result["tools"]],
                          "answer": result["answer"], "latency_ms": round(elapsed, 1),
                          "llm_calls": usage.get("llm_calls", 1 if result["planner"].endswith("_llm") else 0),
                          "total_tokens": usage.get("total_tokens", 0), "fallback_reason": result.get("fallback_reason")})
            context = AssistantContext(**result["context"])
        rows.append({"id": case["id"], "profile": case["profile"], "passed": not any(t["errors"] for t in turns),
                     "turns": turns})
        print(json.dumps({"mode": mode, "provider": provider, "id": case["id"], "passed": rows[-1]["passed"]}), flush=True)
    model_turns = [t for row in rows for t in row["turns"] if t["llm_calls"]]
    latencies = [t["latency_ms"] for t in model_turns]
    summary = {"mode": mode, "provider": provider, "model": MODELS[provider], "cases": len(rows),
               "passed": sum(row["passed"] for row in rows), "pass_rate": round(sum(row["passed"] for row in rows) / len(rows), 4),
               "turns": sum(len(row["turns"]) for row in rows), "model_turns": len(model_turns),
               "latency_ms_p50": percentile(latencies, 0.5), "latency_ms_p95": percentile(latencies, 0.95),
               "llm_calls": sum(t["llm_calls"] for t in model_turns),
               "tokens": sum(t["total_tokens"] for t in model_turns),
               "tokens_per_model_turn": round(statistics.mean([t["total_tokens"] for t in model_turns]), 1) if model_turns else None,
               "glossary_fallbacks": sum(t["planner"] == "glossary_fallback" for row in rows for t in row["turns"]),
               "quota_retries": retries,
               "failures_by_profile": dict(Counter(row["profile"] for row in rows if not row["passed"])),
               "failure_counts": dict(Counter(e for row in rows for t in row["turns"] for e in t["errors"]))}
    return summary, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--suite", type=Path, default=Path("configs/conversation-development-v1.json"))
    parser.add_argument("--index", type=Path, default=Path("data/processed/singapore-catalog-v1.sqlite"))
    parser.add_argument("--serving", type=Path, default=Path("data/processed/singapore-serving-v1.sqlite"))
    parser.add_argument("--pairs", default="planner:gemini,agent:gemini,planner:groq,agent:groq")
    parser.add_argument("--quota-wait", type=float, default=20)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Choose a new immutable report path")
    provenance = catalog_metadata(args.index)
    if provenance["data_kind"] != "official_dhrd":
        raise SystemExit("Official catalog required")
    suite = json.loads(args.suite.read_text(encoding="utf-8"))
    cases = validate_suite(suite)
    reader = CatalogReader(args.index)

    def recommender(arguments):
        params = RecommendationParams.model_validate(arguments)
        return recommend(args.serving, [(s.vendor_id, s.product_id) for s in params.seeds], cuisine=params.cuisine,
                         min_price=params.min_price, max_price=params.max_price, limit=params.limit)

    def source_item(vendor, product):
        found = catalog_item(args.index, vendor, product)
        return found["item"] if found else None

    report = {"schema_version": 1, "kind": "assistant_mode_and_provider_comparison",
              "created_at": datetime.now(timezone.utc).isoformat(), "suite": str(args.suite),
              "suite_sha256": file_hash(args.suite), "source_database_sha256": provenance["source_database_sha256"],
              "implementation_sha256": {name: file_hash(Path("src/meal_discovery") / name) for name in (
                  "agent/graph.py", "agent/grounding.py", "assistant.py", "planner.py", "policies.py", "tools.py",
                  "prompts/agent_v1.txt", "prompts/intent_v1.txt")},
              "paid_api_calls": 0, "official_test_orders_used": False,
              "limitations": ("Development suite authored before this comparison but not held out; one repetition per "
                              "pair; free-tier latency varies with provider load. Contracts check facts, tool choice and "
                              "continuity, not the quality of the closing sentence."),
              "summaries": [], "episodes": {}}
    for pair in args.pairs.split(","):
        mode, provider = pair.split(":")
        summary, rows = run_pair(mode, provider, cases, reader, recommender, source_item, args.quota_wait)
        report["summaries"].append(summary)
        report["episodes"][pair] = rows
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summaries"], indent=2))


if __name__ == "__main__":
    os.environ.setdefault("GEMINI_CALLS_PER_MINUTE", "12")
    os.environ.setdefault("GEMINI_CALLS_PER_DAY", "1000")
    os.environ.setdefault("GROQ_CALLS_PER_MINUTE", "25")
    os.environ.setdefault("GROQ_CALLS_PER_DAY", "1000")
    main()
