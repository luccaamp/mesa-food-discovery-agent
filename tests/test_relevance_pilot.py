from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"evaluations"))
from relevance_top1_pilot import require_admission, summarize


class RelevancePilotTests(unittest.TestCase):
    def test_abstention_is_not_an_irrelevant_grade_and_empty_search_is_not_dropped(self):
        rows=[{"mode":"lexical","grade":g,"empty":g is None} for g in (2,-1,1,None)]
        result=summarize(rows)["lexical"]
        self.assertEqual(result["queries"],4)
        self.assertEqual(result["scored_queries"],3)
        self.assertAlmostEqual(result["full_match_rate_at_1"],1/3)
        self.assertEqual(result["abstentions"],1)
        self.assertEqual(result["empty_results"],1)
        self.assertEqual(result["unrelated"],0)

    def test_admission_requires_unique_complete_controls_and_matching_code(self):
        controls=[{"id":str(i),"expected":i%3} for i in range(8)]
        rows=[{"id":c["id"],"language":lang,"reverse":rev,"grade":c["expected"],
               "expected":c["expected"],"passed":True} for c in controls for lang in ("pt","en") for rev in (False,True)]
        report={"complete":True,"admitted":True,"evaluator_sha256":"verified","calibration":rows}
        require_admission(report,"verified",controls)
        for broken in ({**report,"complete":False},{**report,"admitted":False},
                       {**report,"evaluator_sha256":"changed"},{**report,"calibration":[rows[0]]*32}):
            with self.assertRaises(ValueError):
                require_admission(broken,"verified",controls)


if __name__=="__main__":
    unittest.main()
