import json
import asyncio
from io import BytesIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evaluations"))
from inspect_judge_calibration import LocalJudgeAPI, controls, local_endpoint, parse_verdict, summarize_rows
from inspect_ai.model import ChatMessageUser, GenerateConfig


class JudgeCalibrationTests(unittest.TestCase):
    def test_schema_transport_and_evidence_order_are_explicit(self):
        # Transport unit fixture only; the real conflicting-prompt probe is recorded separately.
        response = {"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}], "usage": {}}
        model = LocalJudgeAPI("unit-test", evidence_first=True)
        with patch("inspect_judge_calibration.urlopen", return_value=BytesIO(json.dumps(response).encode())) as transport:
            asyncio.run(model.generate([ChatMessageUser(content="test")], [], "none", GenerateConfig(temperature=0.7, max_tokens=256)))
        payload = json.loads(transport.call_args.args[0].data)
        self.assertEqual(list(payload["response_format"]["json_schema"]["schema"]["properties"]),
                         ["evidence_field", "reason", "winner"])
        self.assertEqual(payload["temperature"], 0.7)

    def test_loopback_endpoint_rejects_remote_urls_and_credentials(self):
        self.assertEqual(local_endpoint("http://127.0.0.1:8081/"), "http://127.0.0.1:8081")
        for value in ("https://example.org", "http://127.0.0.1:8081/x", "http://key@localhost:8081", "http://localhost:8081?key=hidden"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                local_endpoint(value)

    def test_verdict_requires_explicit_allowed_label_and_evidence(self):
        valid = {"winner": "A", "evidence_field": "unit_price", "reason": "Matches the source value"}
        self.assertEqual(parse_verdict(json.dumps(valid)), valid)
        for value in ([], {**valid, "winner": "human_approved"}, {**valid, "reason": ""},
                      {**valid, "extra": True}, {**valid, "evidence_field": []}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_verdict(json.dumps(value))

    def test_control_pairs_hide_targets_and_reverse_the_correct_side(self):
        # Synthetic unit fixture only, not inference evidence or public menu data.
        item = {"vendor_id": "test-v", "product_id": "test-p", "name": "TEST Chicken Rice",
                "unit_price": 0.002, "primary_cuisine": "test"}
        provenance = {"price_unit": "dataset_normalized_unit", "source_database_sha256": "unit-test-only"}
        with patch("inspect_judge_calibration.catalog_metadata", return_value=provenance), patch("inspect_judge_calibration.search_catalog", return_value={"items": [item]}):
            samples, actual = controls(Path("test-only-index"))
        self.assertEqual(len(samples), 16)
        self.assertEqual(actual, provenance)
        for index in range(0, len(samples), 2):
            first, second = samples[index:index+2]
            self.assertNotEqual(first.target, second.target)
            first_payload = json.loads(first.input.rsplit('\n', 1)[-1])
            second_payload = json.loads(second.input.rsplit('\n', 1)[-1])
            self.assertEqual(first_payload["A"], second_payload["B"])
            self.assertEqual(first_payload["B"], second_payload["A"])
            self.assertNotIn("target", first_payload)
            self.assertEqual(first_payload["reference_facts"]["unit_price"], item["unit_price"])

    def test_missing_catalog_is_not_created_or_silently_mocked(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.sqlite"
            with self.assertRaises(ValueError):
                controls(missing)
            self.assertFalse(missing.exists())

    def test_pair_summary_is_independent_of_log_order(self):
        rows = [{"control": "test-a", "orientation": 0, "verdict": "A", "passed": True, "parse_valid": True},
                {"control": "test-b", "orientation": 1, "verdict": "B", "passed": True, "parse_valid": True},
                {"control": "test-a", "orientation": 1, "verdict": "B", "passed": True, "parse_valid": True},
                {"control": "test-b", "orientation": 0, "verdict": "A", "passed": True, "parse_valid": True}]
        self.assertEqual(summarize_rows(rows), (4, 2, True))
        for invalid in (rows[:-1], rows + [rows[0]], []):
            with self.assertRaises(ValueError):
                summarize_rows(invalid)


if __name__ == "__main__":
    unittest.main()
