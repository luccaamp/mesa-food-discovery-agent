from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"evaluations"))
from relevance_judge_guarded import GuardedJudge, BoundedJudge, opaque_name


class GuardedJudgeTests(unittest.TestCase):
    def test_only_explicit_opaque_labels_are_intercepted(self):
        for name in ("Item 7392","Product #A814","Chef's Special","??? ###"," "):
            self.assertTrue(opaque_name(name),name)
        for name in ("Chicken Rice","Special Fried Rice","2 Chicken Wings","鱼汤","Combo Chicken Rice"):
            self.assertFalse(opaque_name(name),name)

    def test_opaque_only_batch_abstains_without_model_call(self):
        judge=GuardedJudge.__new__(GuardedJudge)
        with patch.object(BoundedJudge,"grade",side_effect=AssertionError("Must not infer unknown food")):
            result=judge.grade([{"id":"c3","name":"SKU 120","query":"fish soup"}])
        self.assertEqual(result["grades"]["c3"]["grade"],-1)
        self.assertEqual(result["deterministic_abstentions"],1)

    def test_mixed_batch_preserves_ids_and_model_grade(self):
        judge=GuardedJudge.__new__(GuardedJudge)
        known={"id":"c8","name":"Fish Soup","query":"fish soup"}
        with patch.object(BoundedJudge,"grade",return_value={"grades":{"c8":{"grade":2,"reason":"Match"}},"elapsed_ms":1,"output_sha256":"fixture"}) as model:
            result=judge.grade([{"id":"c2","name":"Daily Special","query":"fish soup"},known])
        model.assert_called_once_with([known])
        self.assertEqual(set(result["grades"]),{"c2","c8"})
        self.assertEqual(result["grades"]["c8"]["grade"],2)

    def test_dietary_certification_abstains_without_model_even_when_name_claims_it(self):
        judge=GuardedJudge.__new__(GuardedJudge)
        with patch.object(BoundedJudge,"grade",side_effect=AssertionError("Must not infer safety")):
            result=judge.grade([{"id":"safe","name":"Egg-Free Bread","query":"safe for egg allergy"}])
        self.assertEqual(result["grades"]["safe"]["grade"],-1)


if __name__=="__main__":
    unittest.main()
