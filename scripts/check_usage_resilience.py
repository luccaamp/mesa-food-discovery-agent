"""Real-catalog behavioral contracts under an explicitly injected provider timeout.

Direct domain integration, not HTTP, real Gemini inference or human usability.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evaluations"))
from conversation_suite import verify_turn, validate_suite
from meal_discovery.api import CatalogReader
from meal_discovery.api_models import AssistantRequest
from meal_discovery.assistant import PlannerUnavailable, run_assistant
from meal_discovery.catalog import catalog_item
from meal_discovery.dataset import file_hash
from meal_discovery.serving import recommend


class TimedOutPlanner:
    provider = "gemini"
    model = "injected-timeout-not-live-inference"

    def plan(self, message, context):
        raise PlannerUnavailable("provider_timeout", attempts=2)


def run(suite_path, output):
    if output.exists():
        raise ValueError("Preserve previous evidence")
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    cases = validate_suite(suite)
    index = ROOT / "data/processed/singapore-catalog-v1.sqlite"
    serving = ROOT / "data/processed/singapore-serving-v1.sqlite"
    reader = CatalogReader(index)
    report = {"kind": "real_catalog_injected_timeout_direct_domain_integration", "complete": False,
              "created_at": datetime.now(timezone.utc).isoformat(), "suite_sha256": file_hash(suite_path),
              "evaluator_sha256": file_hash(Path(__file__)), "suite": suite,
              "implementation_sha256": {name: file_hash(ROOT / "src/meal_discovery" / name)
                                         for name in ("assistant.py", "discovery.py", "catalog.py", "serving.py")},
              "source": reader.metadata(), "commercial_calls": 0, "episodes": [],
              "limitations": "Scripted direct integration with real catalog and injected timeout. No HTTP, live model, independent human users or preference claims."}
    def recommendation(arguments):
        arguments = dict(arguments)
        seeds = [(r["vendor_id"], r["product_id"]) for r in arguments.pop("seeds")]
        return recommend(serving, seeds, **arguments)
    def oracle(vendor, product):
        found = catalog_item(index, vendor, product)
        return found["item"] if found else None
    try:
        for case in cases:
            previous = case.get("context", {})
            turns = []
            for turn in case["turns"]:
                result = run_assistant(AssistantRequest(message=turn["message"], context=previous),
                                       reader, recommendation, planner=TimedOutPlanner())
                errors = verify_turn(turn, result, previous, oracle)
                if result["planner"] == "glossary_fallback" and not any("sem inferência" in w for w in result["warnings"]):
                    errors.append("missing_fallback_disclosure")
                turns.append({"message": turn["message"], "response": result, "errors": errors})
                previous = result["context"]
            report["episodes"].append({"id": case["id"], "turns": turns, "passed": all(not t["errors"] for t in turns)})
        report["complete"] = True
    finally:
        report["summary"] = {"episodes": len(report["episodes"]), "passed": sum(e["passed"] for e in report["episodes"]),
                             "turns": sum(len(e["turns"]) for e in report["episodes"]),
                             "verified_item_occurrences": sum(len(t["response"]["items"]) for e in report["episodes"] for t in e["turns"])}
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=Path("configs/conversation-development-v1.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.suite, args.output)
    print(json.dumps(report["summary"]))
    raise SystemExit(0 if all(e["passed"] for e in report["episodes"]) else 1)
