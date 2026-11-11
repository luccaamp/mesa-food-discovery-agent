"""Run mechanical contracts on real search, publishing counts rather than rows."""

import argparse
import json
from pathlib import Path
from time import perf_counter

from meal_discovery.catalog import search_catalog
from meal_discovery.dataset import file_hash


def check(index):
    checks = []
    provenance = None
    for query in ("chicken rice", "pizza", "milk tea"):
        started = perf_counter()
        result = search_catalog(index, query, limit=5)
        elapsed = (perf_counter() - started) * 1000
        if not result["items"]:
            raise ValueError(f"Expected real matches for contract probe: {query}")
        first = result["items"][0]
        filtered = search_catalog(index, query, cuisine=first["primary_cuisine"],
                                  min_price=first["unit_price"], max_price=first["unit_price"], limit=5)
        if not filtered["items"] or any(row["primary_cuisine"] != first["primary_cuisine"]
                or row["unit_price"] != first["unit_price"] for row in filtered["items"]):
            raise ValueError("Cuisine/price filter contract failed")
        checks.append({"query": query, "total_matches": result["total_matches"],
                       "returned": len(result["items"]), "local_elapsed_ms": elapsed,
                       "cuisine_and_price_filter_contract": "passed"})
        provenance = result["provenance"]
    return {"schema_version": 1, "kind": "mechanical_search_contracts_not_relevance_evaluation",
            "catalog": provenance, "checks": checks,
            "implementation_sha256": file_hash(Path(__file__).parents[1] / "src/meal_discovery/catalog.py"),
            "limitations": "Three English literal probes; no human relevance labels, semantic or multilingual evaluation. Local elapsed time includes opening and count query, not a load test."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.suffix != ".json":
        parser.error("Choose a new JSON output path")
    result = check(args.index)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(result["checks"], indent=2))
