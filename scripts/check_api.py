"""Verify the real catalog over HTTP; save aggregate contracts, never result rows."""

import argparse
import json
from pathlib import Path
from time import perf_counter
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import urlopen


def check(base_url):
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("Provide the HTTP base URL without a query or fragment")
    base_url = base_url.rstrip("/")

    def get(path, params=None, status=200):
        url = base_url + path + ("?" + urlencode(params) if params else "")
        started = perf_counter()
        try:
            response = urlopen(url, timeout=15)
        except HTTPError as error:
            response = error
        with response:
            body = json.load(response)
            if response.status != status:
                raise ValueError(f"Unexpected status for {path}: {response.status}")
            request_id = response.headers.get("X-Request-ID")
            if not request_id or not response.headers.get("Server-Timing"):
                raise ValueError("Missing request trace headers")
            if status >= 400 and body["error"]["request_id"] != request_id:
                raise ValueError("Error response trace mismatch")
        return body, (perf_counter() - started) * 1000

    get("/health")
    get("/ready")
    metadata, _ = get("/v1/catalog/meta")
    if metadata["data_kind"] != "official_dhrd" or not metadata["historical_catalog"]:
        raise ValueError("Only official historical real data can pass this check")
    cuisines, _ = get("/v1/catalog/cuisines")
    if sum(row["products"] for row in cuisines["cuisines"]) != metadata["products"]:
        raise ValueError("Cuisine count coverage mismatch")
    checks = []
    for query in ("chicken rice", "pizza", "milk tea"):
        result, elapsed = get("/v1/catalog/search", {"query": query, "limit": 5})
        if not result["items"] or result["provenance"] != metadata:
            raise ValueError("Search is empty or uses another source")
        first = result["items"][0]
        path = "/v1/catalog/items/" + quote(first["vendor_id"], safe="") + "/" + quote(first["product_id"], safe="")
        detail, _ = get(path)
        if detail["item"] != {key: value for key, value in first.items() if key != "lexical_score"}:
            raise ValueError("Item detail differs from the search result")
        filters = {"query": query, "cuisine": first["primary_cuisine"], "limit": 5}
        if first["unit_price"] is not None:
            filters.update(min_price=first["unit_price"], max_price=first["unit_price"])
        filtered, _ = get("/v1/catalog/search", filters)
        if not filtered["items"] or any(row["primary_cuisine"] != first["primary_cuisine"]
                or (first["unit_price"] is not None and row["unit_price"] != first["unit_price"])
                for row in filtered["items"]):
            raise ValueError("Combined filters failed")
        checks.append({"query": query, "total_matches": result["total_matches"],
                       "returned": len(result["items"]), "local_http_elapsed_ms": elapsed,
                       "detail_contract": "passed", "combined_filters": "passed"})
    for params in ({"query": "pizza", "limit": 51}, {"query": "pizza", "min_price": "nan"},
                   {"query": "pizza", "min_price": 3, "max_price": 2}, {"query": "---"}):
        get("/v1/catalog/search", params, status=422)
    get("/v1/catalog/items/nonexistent-vendor/nonexistent-item", status=404)
    empty, _ = get("/v1/catalog/search", {"query": "zznonexistentcatalogterm938231"})
    if empty["items"] or empty["total_matches"]:
        raise ValueError("Empty search unexpectedly produced results")
    spec, _ = get("/openapi.json")
    return {"schema_version": 1, "kind": "real_http_contracts_not_relevance_evaluation",
            "api_version": spec["info"]["version"], "catalog": metadata, "checks": checks,
            "invalid_parameters": "422 passed", "unknown_item": "404 passed",
            "empty_results": "no fallback passed", "trace_headers": "passed",
            "limitations": "Three English literal queries against local HTTP, no human relevance labels or load test. Official test orders are not used."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.suffix != ".json":
        parser.error("Choose a new JSON report path")
    result = check(args.base_url)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(result["checks"], indent=2))
