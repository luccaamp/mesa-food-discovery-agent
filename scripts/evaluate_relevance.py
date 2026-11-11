"""Frozen additional bilingual queries; exhaustive name-evidence proxy on one corpus."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import statistics
from time import perf_counter

from meal_discovery.benchmark import ranking_metrics
from meal_discovery.dataset import file_hash
from meal_discovery.discovery import expand_query
from meal_discovery.semantic import SemanticSearch


def relevant_name(name, patterns):
    return all(re.search(pattern, name, re.IGNORECASE) for pattern in patterns)


def evaluate(index, model_dir, protocol, output):
    if output.exists():
        raise ValueError("Choose a new report; preserve failed runs")
    config = json.loads(protocol.read_text(encoding="utf-8"))
    hashes = {"protocol": file_hash(protocol), "index": file_hash(index)}
    engine = SemanticSearch(index, model_dir)
    report = {"kind": "additional_bilingual_name_evidence_proxy", "complete": False,
              "created_at": datetime.now(timezone.utc).isoformat(), "protocol": config,
              "hashes": hashes, "evaluator_sha256": file_hash(Path(__file__)),
              "implementation_sha256": {name: file_hash(Path(__file__).parents[1] / "src/meal_discovery" / name)
                                         for name in ("semantic.py", "embeddings.py", "discovery.py", "catalog.py", "benchmark.py")},
              "retrieval_manifest": engine.manifest, "official_test_orders_used": False,
              "rows": [], "summary": {}, "limitations": config["limitations"]}
    groups = defaultdict(list)
    output.parent.mkdir(parents=True, exist_ok=True)
    def save():
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        engine.search("warmup", limit=1)
        for concept in config["queries"]:
            positives = {(r["vendor_id"], r["product_id"]) for r in engine.rows
                         if relevant_name(r["name"], concept["patterns"])}
            if not positives:
                raise ValueError("No positives: " + concept["id"])
            for language in ("pt", "en"):
                for mode in config["modes"]:
                    query = concept[language]
                    resolved = expand_query(query)[0] if mode == "glossary_lexical" else query
                    started = perf_counter()
                    result = engine.search(resolved, mode="lexical" if mode == "glossary_lexical" else mode, limit=config["k"])
                    keys = [(r["vendor_id"], r["product_id"]) for r in result["items"]]
                    metrics = ranking_metrics(keys, positives, config["k"])
                    metrics["precision"] = len(set(keys) & positives) / config["k"]
                    row = {"id": concept["id"], "language": language, "mode": mode, "query": query,
                           "resolved_query": resolved, "relevant_in_corpus": len(positives),
                           "metrics": metrics, "elapsed_ms": round((perf_counter()-started)*1000, 2),
                           "items": [{**r, "name_evidence_relevant": (r["vendor_id"], r["product_id"]) in positives}
                                     for r in result["items"]]}
                    report["rows"].append(row)
                    groups[(mode, language)].append(metrics)
                    groups[(mode, "all")].append(metrics)
                save()
            print(concept["id"], flush=True)
        report["summary"] = {mode: {lang: {"queries": len(values), **{
            metric: statistics.fmean(v[metric] for v in values) for metric in ("precision", "recall", "ndcg", "hit_rate")}}
            for (m, lang), values in groups.items() if m == mode} for mode in config["modes"]}
        if hashes != {"protocol": file_hash(protocol), "index": file_hash(index)}:
            raise ValueError("Protocol or corpus changed during evaluation")
        report["complete"] = True
    finally:
        save()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=Path("data/processed/singapore-semantic-pilot-v1.sqlite"))
    parser.add_argument("--model-dir", type=Path, default=Path("models/e5-small-onnx-v1"))
    parser.add_argument("--protocol", type=Path, default=Path("configs/retrieval-additional-v1.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(evaluate(args.index, args.model_dir, args.protocol, args.output)["summary"], indent=2))
