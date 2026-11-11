"""Prepare unjudged real results for manual relevance review, without invented labels."""

import argparse
import json
from pathlib import Path

from meal_discovery.dataset import file_hash
from meal_discovery.semantic import SemanticSearch


def prepare(index, model_dir, protocol):
    config = json.loads(protocol.read_text(encoding="utf-8"))
    engine = SemanticSearch(index, model_dir)
    cases = []
    for probe in config["queries"]:
        pool = {}
        for mode in config["modes"]:
            result = engine.search(probe["query"], mode=mode, limit=config["k"])
            for rank, item in enumerate(result["items"], 1):
                key = (item["vendor_id"], item["product_id"])
                if key not in pool:
                    pool[key] = {key: value for key, value in item.items() if key != "retrieval_score"}
                    pool[key].update(relevance=None, reviewer_note="", retrieved_by={})
                pool[key]["retrieved_by"][mode] = rank
        cases.append({"id": probe["id"], "language": probe["language"], "query": probe["query"],
                      "candidates": [pool[key] for key in sorted(pool)]})
    return {"schema_version": 1, "status": "pending_human_review", "reviewer": None,
            "index_sha256": file_hash(index), "protocol_sha256": file_hash(protocol),
            "scope": "Development query pool only; not held-out evaluation or complete relevance coverage.",
            "rubric": {"2": "Name clearly satisfies the requested dish or drink concept.",
                       "1": "Related or plausible alternative, with a meaningful difference.",
                       "0": "Does not satisfy the requested concept.",
                       "null": "Not judged or insufficient evidence. Never infer allergens or ingredients from cuisine alone."},
            "instructions": "Review candidates by their original catalog names. Fill reviewer and relevance, keep uncertainty null and explain it. Rankings are included for debugging; this is not blinded annotation. No judgments were supplied by the program.",
            "cases": cases}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, default=Path("models/e5-small-onnx-v1"))
    parser.add_argument("--protocol", type=Path, default=Path("configs/retrieval-development-v1.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.suffix != ".json":
        parser.error("Choose a new JSON review path")
    result = prepare(args.index, args.model_dir, args.protocol)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(f"Prepared {len(result['cases'])} query cases; all relevance judgments remain null.")
