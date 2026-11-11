"""Compact public deployment evidence, derived from the complete recorded run."""
import json
from pathlib import Path
import statistics

from meal_discovery.dataset import file_hash

ROOT = Path(__file__).resolve().parents[1] / "evaluations/results"


def summarize(path):
    report = json.loads(path.read_text(encoding="utf-8"))
    rows = report["rows"]
    if not report["complete"] or len(rows) != len(report["protocol"]["cases"]):
        raise ValueError("Incomplete public acceptance is not completed model evidence")
    return {"kind": report["kind"], "verified_at": report["created_at"],
            "deployment_commit": report["deployment_commit"], "model": report["model"],
            "passed": sum(row["passed"] for row in rows), "total": len(rows),
            "gemini_inferences_completed": sum(row["inference_completed"] for row in rows),
            "provider_attempts": sum(row["response"]["usage"].get("provider_attempts", 0) for row in rows),
            "successful_response_tokens": sum(row["response"]["usage"].get("total_tokens", 0) for row in rows),
            "catalog_items_checked": sum(len(row["response"]["items"]) for row in rows),
            "http_latency_ms_median": statistics.median(row["http_ms"] for row in rows),
            "source_database_sha256": report["source_database_sha256"], "report_sha256": file_hash(path),
            "limitations": report["limitations"]}


if __name__ == "__main__":
    with (ROOT / "public-assistant-summary-v1.json").open("x", encoding="utf-8") as stream:
        json.dump(summarize(ROOT / "public-assistant-acceptance-v1.json"), stream, ensure_ascii=False, indent=2)
        stream.write("\n")
