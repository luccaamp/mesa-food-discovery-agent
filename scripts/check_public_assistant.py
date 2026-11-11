"""Bounded public Gemini acceptance with independent official-catalog oracles.

No keys are read. A fallback can pass domain checks but cannot pass an inference
requirement. Stop after two model failures or quota admission failure; save partial
evidence, never redeploy/restart to obtain more quota.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from time import monotonic, sleep
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evaluations"))
from conversation_suite import validate_suite, verify_turn
from meal_discovery.catalog import catalog_item, catalog_metadata
from meal_discovery.dataset import file_hash


def run(output, base="https://mesa-meal-discovery.onrender.com", protocol_path=None):
    parsed = urlsplit(base)
    if (parsed.scheme != "https" or parsed.netloc != "mesa-meal-discovery.onrender.com"
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
        raise ValueError("This protocol targets only the known public demo without credentials")
    if output.exists():
        raise ValueError("Choose a new report path")
    path = protocol_path or ROOT / "configs/public-assistant-acceptance-v1.json"
    protocol = json.loads(path.read_text(encoding="utf-8"))
    validate_suite({"cases": [{**case, "turns": [case]} for case in protocol["cases"]]})
    index = ROOT / "data/processed/singapore-catalog-v1.sqlite"
    source = catalog_metadata(index)

    def request(route, body=None):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        with urlopen(Request(base.rstrip("/") + route, data=data, headers={"Content-Type": "application/json"}), timeout=90) as response:
            return json.load(response), response.headers.get("X-Request-ID")

    system, _ = request("/v1/system")
    meta, _ = request("/v1/catalog/meta")
    if system["assistant"]["provider"] != "gemini" or not system["assistant"]["configured"]:
        raise ValueError("Public Gemini configuration required")
    if meta["data_kind"] != "official_dhrd" or meta["source_database_sha256"] != source["source_database_sha256"]:
        raise ValueError("Independent official catalog and public source differ")
    report = {"kind": "public_gemini_bounded_deployment_acceptance", "created_at": datetime.now(timezone.utc).isoformat(),
              "complete": False, "protocol": protocol, "protocol_sha256": file_hash(path),
              "evaluator_sha256": file_hash(Path(__file__)), "source_database_sha256": source["source_database_sha256"],
              "deployment_commit": system.get("deployment_commit"), "reliability_policy": system["assistant"].get("reliability"),
              "model": system["assistant"]["model"], "rows": [], "stop_reason": None,
              "limitations": "Small deployment acceptance suite. No human preference, load, uptime guarantee or general conversational quality estimate. Tokens from failed attempts remain unknown."}
    output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        rows = report["rows"]
        report["summary"] = {"cases_executed": len(rows), "cases_planned": len(protocol["cases"]),
            "domain_passed": sum(not row["domain_errors"] for row in rows),
            "acceptance_passed": sum(row["passed"] for row in rows),
            "gemini_inferences_completed": sum(row["inference_completed"] for row in rows),
            "provider_attempts": sum(row["response"]["usage"].get("provider_attempts", 0) for row in rows),
            "successful_response_tokens": sum(row["response"]["usage"].get("total_tokens", 0) for row in rows)}
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def source_item(vendor, product):
        value = catalog_item(index, vendor, product)
        return value["item"] if value else None

    attempts = 0
    recent_attempts = []
    failures = 0
    context = {}
    observed = None
    try:
        for case in protocol["cases"]:
            requires_model = case.get("requires_gemini", False)
            if requires_model:
                if attempts + 2 > protocol["max_model_attempts"]:
                    report["stop_reason"] = "evaluation_attempt_budget"
                    break
                # Conservative pacing: count every attempt at response completion.
                recent_attempts = [stamp for stamp in recent_attempts if monotonic() - stamp < 60]
                while len(recent_attempts) + 2 > 3:
                    sleep(min(60, max(0.01, 60 - (monotonic() - recent_attempts[0]))))
                    recent_attempts = [stamp for stamp in recent_attempts if monotonic() - stamp < 60]
            previous = dict(context) if case.get("carry_context") else dict(case.get("context", {}))
            if case.get("select_observed_item"):
                if observed is None:
                    report["stop_reason"] = "no_verified_reference_item"
                    break
                previous["selected_items"] = [{key: observed[key] for key in ("vendor_id", "product_id")}]
            started = monotonic()
            result, request_id = request("/v1/assistant", {"message": case["message"], "context": previous})
            used = result["usage"].get("provider_attempts")
            if requires_model and (type(used) is not int or not 0 <= used <= 2):
                raise ValueError("Deployed code does not expose bounded attempt accounting")
            used = used or 0
            attempts += used
            recent_attempts.extend([monotonic()] * used)
            errors = verify_turn(case, result, previous, source_item)
            inferred = result["planner"] == "gemini_llm" and result["usage"].get("total_tokens", 0) > 0
            report["rows"].append({"id": case["id"], "request_id": request_id,
                "request": {"message": case["message"], "context": previous}, "response": result,
                "domain_errors": errors, "inference_completed": inferred,
                "passed": not errors and (not requires_model or inferred), "http_ms": round((monotonic() - started) * 1000, 2)})
            context = result["context"]
            if result["items"]:
                observed = result["items"][0]
            if requires_model:
                failures = 0 if inferred else failures + 1
            save()
            print(json.dumps({"id": case["id"], "passed": report["rows"][-1]["passed"], "planner": result["planner"], "provider_attempts": used}), flush=True)
            if requires_model and used == 0 and not inferred:
                report["stop_reason"] = "provider_admission_or_configuration_failure"
                break
            if failures >= protocol["max_consecutive_inference_failures"]:
                report["stop_reason"] = "consecutive_provider_failures"
                break
        else:
            report["complete"] = True
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        report["stop_reason"] = "http_" + str(error.code) if isinstance(error, HTTPError) else "transport_unavailable"
        report["failed_case_id"] = case["id"]
        # No URLs, keys, provider bodies or raw exception text in public evidence.
    finally:
        save()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--protocol", type=Path)
    args = parser.parse_args()
    report = run(args.output, protocol_path=args.protocol)
    print(json.dumps(report["summary"], indent=2))
    raise SystemExit(0 if report["complete"] and all(row["passed"] for row in report["rows"]) else 1)
