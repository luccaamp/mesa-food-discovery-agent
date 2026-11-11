import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evaluations"))
import relevance_judge_bounded as bounded


class BoundedJudgeTests(unittest.TestCase):
    def run_fixture(self, final):
        judge = bounded.BoundedJudge.__new__(bounded.BoundedJudge)
        judge.exe = Path("fixture.exe")
        judge.model = Path("fixture.gguf")
        calls = []
        def fake_run(args, **kwargs):
            prompt = Path(args[args.index("-f")+1]).read_text(encoding="utf-8")
            calls.append((args, prompt))
            return SimpleNamespace(returncode=0, stdout=(b"unfinished draft" if len(calls)==1 else final))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".tools").mkdir()
            with patch.object(bounded,"ROOT",root), patch.object(bounded.subprocess,"run",side_effect=fake_run):
                result = judge.grade([{"id":"c0","query":"fish soup","name":"Fish Soup"}])
        return result, calls

    def test_truncated_reasoning_reaches_a_constrained_final_phase(self):
        result, calls = self.run_fixture(b'{"c0":{"grade":2,"reason":"Explicit match"}}')
        self.assertEqual(result["grades"]["c0"]["grade"],2)
        self.assertEqual(len(calls),2)
        self.assertIn("-jf",calls[1][0])
        self.assertTrue(calls[1][1].endswith("unfinished draft\n</think>\n\n"))
        self.assertNotIn("unfinished draft",json.dumps(result))

    def test_invalid_final_is_not_scored(self):
        with self.assertRaises(ValueError):
            self.run_fixture(b'{"c0":{"grade":true,"reason":"Match"}}')


if __name__ == "__main__":
    unittest.main()
