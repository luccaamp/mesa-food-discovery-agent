import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import os

try:
    import fastapi
    import httpx2
except ImportError as error:
    raise unittest.SkipTest("Install .[api,test] to run API tests") from error

from fastapi.testclient import TestClient

from meal_discovery.api import CatalogReader, create_app, get_reader
from meal_discovery.catalog import build_catalog
from meal_discovery.singapore import prepare_singapore
from test_singapore import source_fixture


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        source_fixture(self.root / "raw")
        database = self.root / "dataset.sqlite"
        prepare_singapore(self.root / "raw", database, allow_test_data=True)
        self.index = self.root / "catalog.sqlite"
        build_catalog(database, self.index, allow_test_data=True)
        self.application = create_app(self.index)
        # Test-only dependency replacement; production app never accepts a synthetic flag.
        self.application.dependency_overrides[get_reader] = lambda: CatalogReader(self.index, allow_test_data=True)
        self.client = TestClient(self.application)
        self.addCleanup(self.client.close)

    def test_search_details_cuisines_and_provenance_form_one_contract(self):
        before = hashlib.sha256(self.index.read_bytes()).hexdigest()
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
        self.assertEqual(self.client.get("/ready").status_code, 200)
        result = self.client.get("/v1/catalog/search", params={"query": "Test", "min_price": 2, "max_price": 2, "cuisine": "category"})
        self.assertEqual(result.status_code, 200, result.text)
        payload = result.json()
        self.assertEqual(payload["total_matches"], 1)
        item = payload["items"][0]
        detail = self.client.get(f"/v1/catalog/items/{item['vendor_id']}/{item['product_id']}").json()
        self.assertEqual(detail["item"]["name"], item["name"])

        self.assertEqual(detail["provenance"], payload["provenance"])
        self.assertTrue(payload["provenance"]["historical_catalog"])
        self.assertEqual(payload["provenance"]["price_unit"], "dataset_normalized_unit")
        cuisines = self.client.get("/v1/catalog/cuisines").json()
        self.assertEqual(cuisines["cuisines"], [{"name": "category", "products": 2}])
        self.assertEqual(self.client.get("/v1/catalog/meta").json()["products"], 2)
        self.assertEqual(before, hashlib.sha256(self.index.read_bytes()).hexdigest())

    def test_system_reports_only_valid_public_commit_provenance(self):
        with patch.dict(os.environ, {"RENDER_GIT_COMMIT": "a" * 40, "LLM_PROVIDER": "disabled"}):
            self.assertEqual(self.client.get("/v1/system").json()["deployment_commit"], "a" * 40)
        with patch.dict(os.environ, {"RENDER_GIT_COMMIT": "invalid-do-not-echo", "LLM_PROVIDER": "disabled"}):
            self.assertIsNone(self.client.get("/v1/system").json()["deployment_commit"])

    def test_latest_relevance_decision_replaces_prior_failed_judge(self):
        reports = self.root / "reports"
        reports.mkdir()
        old = {"judge_admitted": False, "controls_correct": 28, "controls_total": 40}
        new = {"judge_admitted": True, "controls_correct": 32, "controls_total": 32}
        (reports / "relevance-decision-v1.json").write_text(json.dumps(old), encoding="utf-8")
        with patch.dict(os.environ, {"MEAL_EVALUATIONS_DIR": str(reports)}):
            self.assertEqual(self.client.get("/v1/evaluations").json()["relevance_evaluation"], old)
            (reports / "relevance-decision-v2.json").write_text(json.dumps(new), encoding="utf-8")
            self.assertEqual(self.client.get("/v1/evaluations").json()["relevance_evaluation"], new)

    def test_empty_unknown_and_injection_queries_never_fabricate_items(self):
        for query in ("absent", "Test OR absent", "'; DROP TABLE items;--"):
            response = self.client.get("/v1/catalog/search", params={"query": query})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["items"], [])
        response = self.client.get("/v1/catalog/items/v1/unknown")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "not_found")

    def test_evaluations_exposes_recorded_local_contracts_without_claiming_gemini(self):
        directory = Path(__file__).parents[1] / "evaluations/results"
        with patch.dict(os.environ, {"MEAL_EVALUATIONS_DIR": str(directory)}):
            payload = self.client.get("/v1/evaluations").json()
        self.assertEqual(len(payload["reports"]), 2)
        recorded = payload["assistant_evaluation"]
        self.assertEqual(recorded["passed"], 13)
        self.assertEqual(recorded["catalog_items_checked"], 48)
        self.assertFalse(recorded["live_gemini_tested"])
        self.assertIn("Qwen", recorded["model"])
        conversation = payload["conversation_evaluation"]
        self.assertEqual(conversation["episodes"], 120)
        self.assertEqual(conversation["catalog_items_checked"], 702)
        self.assertEqual(payload["ai_evaluation"]["simulator_requested"], 8)
        self.assertEqual(payload["ai_evaluation"]["judge_controls_passed"], 32)
        latest_public = json.loads((directory / "public-assistant-summary-v3.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["public_assistant_evaluation"], latest_public)
        with patch.dict(os.environ, {"MEAL_EVALUATIONS_DIR": str(self.root)}):
            payload = self.client.get("/v1/evaluations").json()
        self.assertEqual(payload["reports"], [])
        self.assertIsNone(payload["assistant_evaluation"])
        self.assertIsNone(payload["conversation_evaluation"])
        self.assertIsNone(payload["ai_evaluation"])
        self.assertIsNone(payload["public_assistant_evaluation"])

    def test_invalid_queries_have_consistent_errors_and_request_ids(self):
        for params in ({}, {"query": " "}, {"query": "---"}, {"query": "x" * 201},
                       {"query": "Test", "limit": 51}, {"query": "Test", "limit": "true"},
                       {"query": "Test", "min_price": "nan"}, {"query": "Test", "max_price": "inf"},
                       {"query": "Test", "min_price": -1}, {"query": "Test", "min_price": 3, "max_price": 2},
                       {"query": "Test", "allow_test_data": "true"}):
            with self.subTest(params=params):
                response = self.client.get("/v1/catalog/search", params=params)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(response.json()["error"]["code"], "invalid_request")
                self.assertEqual(response.json()["error"]["request_id"], response.headers["x-request-id"])
                self.assertIn("server-timing", response.headers)

    def test_missing_invalid_and_synthetic_indexes_return_503_without_paths(self):
        missing = self.root / "private-index.sqlite"
        corrupt = self.root / "corrupt.sqlite"
        corrupt.write_text("not a sqlite database", encoding="utf-8")
        for index in (missing, corrupt, self.index):
            with TestClient(create_app(index)) as client:
                self.assertEqual(client.get("/health").status_code, 200)
                for route in ("/ready", "/v1/catalog/meta", "/v1/catalog/cuisines",
                              "/v1/catalog/search?query=Test", "/v1/catalog/items/v1/p1"):
                    response = client.get(route)
                    self.assertEqual(response.status_code, 503, response.text)
                    self.assertEqual(response.json()["error"]["code"], "catalog_unavailable")
                    self.assertNotIn(str(index), response.text)
        self.assertFalse(missing.exists())

    def test_invalid_metadata_is_an_operational_error(self):
        connection = sqlite3.connect(self.index)
        try:
            connection.execute("UPDATE metadata SET value=?", (json.dumps([]),))
            connection.commit()
        finally:
            connection.close()
        self.assertEqual(self.client.get("/ready").status_code, 503)

    def test_openapi_describes_responses_and_write_methods_are_unavailable(self):
        spec = self.client.get("/openapi.json").json()
        exported = Path(__file__).parents[1] / "apps/api/openapi.json"
        saved_spec = json.loads(exported.read_text(encoding="utf-8"))
        self.assertEqual(spec, saved_spec)
        search = spec["paths"]["/v1/catalog/search"]["get"]
        self.assertIn("503", search["responses"])
        self.assertIn("422", search["responses"])
        self.assertEqual(self.client.get("/docs").status_code, 200)
        response = self.client.post("/v1/catalog/search", json={"query": "Test"})
        self.assertEqual(response.status_code, 405)

    def test_logs_do_not_include_search_text(self):
        with self.assertLogs("meal_discovery.api", level="INFO") as captured:
            self.client.get("/v1/catalog/search", params={"query": "PRIVATE_SEARCH_TERM"})
        self.assertNotIn("PRIVATE_SEARCH_TERM", "\n".join(captured.output))
        self.assertIn("/v1/catalog/search", "\n".join(captured.output))
