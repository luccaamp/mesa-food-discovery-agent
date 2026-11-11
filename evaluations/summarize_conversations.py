"""Derive the public compact summary from immutable full conversation reports."""
import argparse
import json
from pathlib import Path

from meal_discovery.dataset import file_hash


def summarize(report_path, baseline_path):
    report = json.loads(report_path.read_text(encoding="utf-8"))
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    if not report["complete"] or not baseline["complete"]:
        raise ValueError("Incomplete evaluations must not be presented as completed")
    if report["suite_sha256"] != baseline["suite_sha256"]:
        raise ValueError("Before/after comparison requires the same frozen cases")
    rows = report["episodes"]
    return {**report["summary"], "scenarios": len(report["suite"]["cases"]),
            "profiles": len({row["profile"] for row in rows}),
            "turns": sum(len(row["turns"]) for row in rows),
            "catalog_items_checked": sum(len(turn["response"]["items"]) for row in rows for turn in row["turns"]),
            "baseline_passed": baseline["summary"]["passed"], "baseline_episodes": baseline["summary"]["episodes"],
            "source_database_sha256": report["source_database_sha256"],
            "suite_sha256": report["suite_sha256"], "report_sha256": file_hash(report_path),
            "kind": report["kind"], "limitations": report["limitations"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = summarize(args.report, args.baseline)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
