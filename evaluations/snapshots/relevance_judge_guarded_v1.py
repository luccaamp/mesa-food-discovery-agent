"""Abstain on explicit opaque menu labels before invoking the local name judge."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from relevance_judge_bounded import BoundedJudge, ROOT, run
from meal_discovery.dataset import file_hash


def opaque_name(name):
    text = " ".join(name.casefold().strip().split())
    return (not any(c.isalpha() for c in text)
            or bool(re.fullmatch(r"(?:item|product|sku|dish|menu)\s*[-:#]?\s*[a-z]*\d[\w-]*", text))
            or text in {"chef's special", "chef special", "daily special", "special of the day",
                        "set meal", "combo", "regular", "large", "small"})


class GuardedJudge(BoundedJudge):
    def __init__(self):
        super().__init__()
        self.description.update(name_guard="explicit_opaque_inventory_or_generic_menu_label_abstention",
                                name_guard_sha256=file_hash(Path(__file__)))

    def grade(self, candidates):
        unknown=[c for c in candidates if opaque_name(c["name"])]
        readable=[c for c in candidates if not opaque_name(c["name"])]
        if readable:
            result=super().grade(readable)
        else:
            result={"grades":{},"elapsed_ms":0,"output_sha256":None}
        result["grades"].update({c["id"]:{"grade":-1,"reason":"Opaque label contains no identifiable dish or drink"} for c in unknown})
        result["deterministic_abstentions"]=len(unknown)
        result["grades_sha256"]=hashlib.sha256(json.dumps(result["grades"],sort_keys=True).encode()).hexdigest()
        return result


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    run(args.output,True,GuardedJudge,ROOT/"configs/relevance-judge-controls-v4.json")
