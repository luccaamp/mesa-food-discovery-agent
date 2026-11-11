"""Unit-only transport fixtures audit the evaluator's quota and stopping behavior."""
from contextlib import redirect_stdout
from io import BytesIO, StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_public_assistant as acceptance


class PublicAcceptanceRunnerTests(unittest.TestCase):
    def test_transport_failure_preserves_incomplete_sanitized_evidence(self):
        provenance = {"data_kind": "official_dhrd", "source_database_sha256": "UNIT-FIXTURE-ONLY"}
        class Response(BytesIO):
            headers = {}
        replies = [Response(json.dumps({"assistant": {"provider": "gemini", "configured": True, "model": "UNIT-ONLY"}}).encode()),
                   Response(json.dumps(provenance).encode()), OSError("private-url-and-secret")]
        with tempfile.TemporaryDirectory() as directory, patch.object(acceptance, "catalog_metadata", return_value=provenance), patch.object(acceptance, "urlopen", side_effect=replies):
            output = Path(directory) / "unit-only.json"
            report = acceptance.run(output)
            saved = output.read_text(encoding="utf-8")
        self.assertFalse(report["complete"])
        self.assertEqual(report["stop_reason"], "transport_unavailable")
        self.assertEqual(report["failed_case_id"], "fish-search")
        self.assertEqual(report["summary"]["cases_executed"], 0)
        self.assertNotIn("private-url-and-secret", saved)

    def test_policy_turn_cannot_hide_consecutive_model_failures_or_skip_pacing(self):
        # All objects below are labelled unit fixtures, not public evaluation evidence.
        provenance = {"data_kind": "official_dhrd", "source_database_sha256": "UNIT-FIXTURE-ONLY"}
        item = {"vendor_id": "unit-v", "product_id": "unit-p", "name": "UNIT TEST ITEM",
                "unit_price": 0.001, "primary_cuisine": "unit"}
        clock, posts, waits = [0.0], [], []

        class Response(BytesIO):
            headers = {"X-Request-ID": "unit-only"}

        def response(value):
            return Response(json.dumps(value).encode())

        def transport(request, **kwargs):
            if request.full_url.endswith("/v1/system"):
                return response({"assistant": {"provider": "gemini", "configured": True, "model": "UNIT-ONLY"}})
            if request.full_url.endswith("/v1/catalog/meta"):
                return response(provenance)
            body = json.loads(request.data)
            posts.append(body)
            refinement = len(posts) == 2
            query = "milk tea" if len(posts) == 3 else "fish soup"
            context = {**body["context"], "last_query": query}
            if refinement:
                context["max_price"] = 0.004
            return response({"status": "ok", "items": [item], "context": context,
                "tools": [{"name": "search_catalog", "arguments": {"query": query}}],
                "warnings": ["Catálogo histórico. Preços normalizados."],
                "planner": "explicit_filter_refinement" if refinement else "glossary_fallback",
                "usage": {} if refinement else {"provider_attempts": 2}})

        def pause(seconds):
            waits.append(seconds)
            clock[0] += seconds

        with redirect_stdout(StringIO()), tempfile.TemporaryDirectory() as directory, patch.object(acceptance, "catalog_metadata", return_value=provenance), patch.object(
                acceptance, "catalog_item", return_value={"item": item}), patch.object(acceptance, "urlopen", side_effect=transport), patch.object(
                acceptance, "monotonic", side_effect=lambda: clock[0]), patch.object(acceptance, "sleep", side_effect=pause):
            report = acceptance.run(Path(directory) / "unit-only.json")
        self.assertFalse(report["complete"])
        self.assertEqual(report["stop_reason"], "consecutive_provider_failures")
        self.assertEqual(report["summary"]["provider_attempts"], 4)
        self.assertEqual(report["summary"]["gemini_inferences_completed"], 0)
        self.assertEqual(len(posts), 3)  # Two failed model requests, one domain-only refinement.
        self.assertGreaterEqual(sum(waits), 60)
        self.assertTrue(all(seconds <= 60 for seconds in waits))


if __name__ == "__main__":
    unittest.main()
