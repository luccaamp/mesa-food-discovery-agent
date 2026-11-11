"""Development comparison with silver name rules; not a human relevance benchmark."""

import argparse
from collections import defaultdict
import json
from importlib.metadata import version
from pathlib import Path
import platform
import re
import statistics
from time import perf_counter

from meal_discovery.benchmark import ranking_metrics
from meal_discovery.dataset import file_hash
from meal_discovery.semantic import SemanticSearch


def evaluate(index, model_dir, protocol):
    protocol_hash = file_hash(protocol)
    config = json.loads(protocol.read_text(encoding="utf-8"))
    if (config.get("protocol_version") != "retrieval-development-v1"
            or config.get("label_kind") != "silver_name_rules_not_human_judgments"
            or config.get("k") != 10 or config.get("modes") != ["lexical", "semantic", "hybrid"]):
        raise ValueError("Unsupported development evaluation")
    index_hash = file_hash(index)
    engine = SemanticSearch(index, model_dir)
    rows = []
    groups = defaultdict(list)
    # Warm up inference; cold model loading is outside reported request times.
    engine.search("warmup", mode="semantic", limit=1)
    for probe in config["queries"]:
        relevant = {(row["vendor_id"], row["product_id"]) for row in engine.rows
                    if all(re.search(pattern, row["name"], re.IGNORECASE) for pattern in probe["name_patterns"])}
        if not relevant:
            raise ValueError(f"No silver positives for {probe['id']}; do not silently exclude this query")
        result = {"id": probe["id"], "language": probe["language"], "query": probe["query"],
                  "silver_relevant_products": len(relevant), "models": {}}
        for mode in config["modes"]:
            started = perf_counter()
            ranking = engine.search(probe["query"], mode=mode, limit=config["k"])
            elapsed = (perf_counter() - started) * 1000
            keys = [(row["vendor_id"], row["product_id"]) for row in ranking["items"]]
            metrics = ranking_metrics(keys, relevant, config["k"])
            metrics["precision"] = len(set(keys) & relevant) / config["k"]
            metrics["returned"] = len(keys)
            metrics["local_elapsed_ms"] = elapsed
            result["models"][mode] = metrics
            groups[(mode, probe["language"])].append(metrics)
            groups[(mode, "all")].append(metrics)
        rows.append(result)
    summary = {}
    for (mode, language), values in groups.items():
        summary.setdefault(mode, {})[language] = {"queries": len(values),
            **{metric: statistics.fmean(row[metric] for row in values)
               for metric in ("recall", "ndcg", "precision", "hit_rate", "local_elapsed_ms")}}
    if file_hash(index) != index_hash or file_hash(protocol) != protocol_hash:
        raise ValueError("Index or evaluation protocol changed")
    return {"schema_version": 1, "kind": "development_silver_labels_not_human_relevance",
            "software_versions": {"python": platform.python_version(), **{name: version(name)
                                   for name in ("numpy", "onnxruntime", "tokenizers", "huggingface-hub")}},
            "protocol_sha256": protocol_hash, "protocol": config, "index_sha256": index_hash,
            "retrieval_manifest": engine.manifest, "queries": rows, "summary": summary,
            "implementation_sha256": {name: file_hash(Path(__file__).parents[1] / "src/meal_discovery" / name)
                                      for name in ("semantic.py", "embeddings.py", "catalog.py")},
            "evaluator_sha256": file_hash(Path(__file__)),
            "limitations": [config["limitations"], "Same frozen catalog subset for all modes, no official test orders.",
                            "Local warmed timings include lexical search and exact dense scoring; no load test.",
                            "Neural retrieval returns nearest neighbors even when none are relevant; no confidence threshold validated."]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, default=Path("models/e5-small-onnx-v1"))
    parser.add_argument("--protocol", type=Path, default=Path("configs/retrieval-development-v1.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.suffix != ".json":
        parser.error("Choose a new JSON report path")
    result = evaluate(args.index, args.model_dir, args.protocol)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(result["summary"], indent=2))
