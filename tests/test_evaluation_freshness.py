import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from meal_discovery.api import create_app


class EvaluationFreshnessTests(unittest.TestCase):
    def test_new_failed_run_is_not_hidden_by_older_success(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "public-assistant-summary-v1.json").write_text(
                json.dumps({"passed": 6, "total": 6}), encoding="utf-8")
            (root / "public-assistant-summary-v2.json").write_text(
                json.dumps({"passed": 0, "total": 10, "complete": False}), encoding="utf-8")
            with patch.dict(os.environ, {"MEAL_EVALUATIONS_DIR": folder}):
                app = create_app()
                endpoint = next(route.endpoint for route in app.routes if route.path == "/v1/evaluations")
                summary = endpoint()["public_assistant_evaluation"]
            self.assertEqual(summary["passed"], 0)
            self.assertFalse(summary["complete"])


if __name__ == "__main__":
    unittest.main()
