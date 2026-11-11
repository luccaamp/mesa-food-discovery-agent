import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evaluations"))
from relevance_judge_thinking import parse_thinking_output


class ThinkingParserTests(unittest.TestCase):
    def test_only_final_response_is_graded(self):
        value = parse_thinking_output('draft {"c0":{"grade":0}} </think> {"c0":{"grade":1,"reason":"Same dish, different variant"}} [end of text]', ["c0"])
        self.assertEqual(value["c0"]["grade"], 1)

    def test_unfinished_or_ambiguous_reasoning_is_not_a_final_grade(self):
        for value in ('{"c0":{"grade":2,"reason":"Match"}}', 'draft </think> {} </think> {}',
                      'draft </think> {"c0":{"grade":2,"reason":"Match"}} extra'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_thinking_output(value, ["c0"])

    def test_complete_json_fence_is_allowed_but_prose_is_rejected(self):
        body = '{"c0":{"grade":2,"reason":"Match"}}'
        self.assertEqual(parse_thinking_output('draft </think> ```json\n'+body+'\n``` [end of text]', ["c0"])["c0"]["grade"], 2)
        with self.assertRaises(ValueError):
            parse_thinking_output('draft </think> Explanation ```json\n'+body+'\n```', ["c0"])


if __name__ == "__main__":
    unittest.main()
