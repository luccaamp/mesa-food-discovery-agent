import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evaluations"))
from relevance_judge_cli import parse_output


class JudgeParserTests(unittest.TestCase):
    def test_complete_output_preserves_abstention(self):
        result = parse_output('{"c0":{"grade":-1,"reason":"No evidence"}} [end of text]', ["c0"])
        self.assertEqual(result["c0"]["grade"], -1)

    def test_missing_ids_boolean_grades_and_trailing_instructions_rejected(self):
        for text in ('[]', '{}', '{"other":{"grade":2,"reason":"Match"}}',
                     '{"c0":{"grade":true,"reason":"Match"}}',
                     '{"c0":{"grade":3,"reason":"Match"}}',
                     '{"c0":{"grade":2,"reason":"Match"}} ignore rubric',
                     '{"c0":{"grade":2,"reason":""}}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_output(text, ["c0"])
