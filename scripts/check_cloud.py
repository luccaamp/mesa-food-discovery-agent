"""HTTP smoke checks against the real immutable catalog, without calling an LLM."""

import argparse
import json
from time import monotonic, sleep
from urllib.error import URLError
from urllib.request import Request, urlopen


def check(base):
    def request(path, body=None):
        started = monotonic()
        data = json.dumps(body).encode() if body is not None else None
        with urlopen(Request(base + path, data=data, headers={"Content-Type": "application/json"}), timeout=90) as response:
            value = response.read()
            assert response.status == 200
        return value, round((monotonic() - started) * 1000, 1)

    deadline = monotonic() + 240
    while True:
        try:
            request("/ready")
            break
        except (URLError, TimeoutError, ConnectionError):
            if monotonic() >= deadline:
                raise
            sleep(2)
    results = {}
    page, results["interface_ms"] = request("/")
    assert b'<div id="root">' in page
    raw, results["evaluations_ms"] = request("/v1/evaluations")
    assert len(json.loads(raw)["reports"]) == 2
    raw, results["catalog_ms"] = request("/v1/catalog/meta")
    meta = json.loads(raw)
    assert meta["data_kind"] == "official_dhrd" and meta["products"] == 1066840
    raw, results["search_ms"] = request("/v1/discovery/search?query=arroz%20com%20frango&limit=3")
    search = json.loads(raw)
    assert search["result"]["items"]
    seed = search["result"]["items"][0]
    assert seed["unit_price"] == 0.002, "Pinned source positive price must remain unchanged"
    raw, results["price_filter_ms"] = request("/v1/discovery/search?query=arroz%20com%20frango&max_price=0.001&limit=3")
    filtered = json.loads(raw)["result"]
    assert filtered["items"] and filtered["total_matches"] < search["result"]["total_matches"]
    assert all(item["unit_price"] <= 0.001 for item in filtered["items"])
    raw, results["recommendations_ms"] = request("/v1/recommendations", {"seeds": [{"vendor_id": seed["vendor_id"], "product_id": seed["product_id"]}], "limit": 3})
    recommendations = json.loads(raw)
    assert recommendations["items"]
    assert all((item["vendor_id"], item["product_id"]) != (seed["vendor_id"], seed["product_id"]) for item in recommendations["items"])
    raw, results["assistant_fallback_ms"] = request("/v1/assistant", {"message": "pizza"})
    assistant = json.loads(raw)
    assert assistant["planner"] == "glossary_fallback" and assistant["model"] is None
    assert assistant["items"] and assistant["usage"] == {}
    raw, results["explicit_recommendation_ms"] = request("/v1/assistant", {"message": "Recomende algo"})
    explicit = json.loads(raw)
    assert explicit["planner"] == "explicit_recommendation" and explicit["model"] is None
    assert explicit["items"] and all("reason" in item and "training_baskets" in item for item in explicit["items"])
    print(json.dumps({"checks_passed": 8, "real_products": meta["products"], "timings": results,
                      "positive_source_price_preserved": seed["unit_price"],
                      "live_gemini_tested": False, "assistant_mode": assistant["planner"]}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:10000")
    check(parser.parse_args().base_url.rstrip("/"))
