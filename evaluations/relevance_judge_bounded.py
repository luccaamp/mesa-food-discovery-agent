"""Bounded local reasoning followed by schema-constrained final grades."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from time import perf_counter
from relevance_judge_cli import Judge, ROOT, SYSTEM, parse_output
from meal_discovery.dataset import file_hash


class BoundedJudge(Judge):
    def __init__(self):
        super().__init__()
        self.description.update(temperature=0.6, top_p=0.95, top_k=20, min_p=0,
            seed=42, reasoning_tokens=512, max_tokens=768,
            template="explicit_ChatML_bounded_reasoning_then_constrained_final",
            output="JSON schema constrained final; reasoning not retained")

    def grade(self, candidates):
        ids = [c["id"] for c in candidates]
        user = json.dumps(candidates, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")
        prefix = f"<|im_start|>system\n{SYSTEM}<|im_end|>\n<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n<think>\n"
        schema = {"type":"object", "properties": {key: {"type":"object", "properties": {
            "grade":{"type":"integer","enum":[-1,0,1,2]}, "reason":{"type":"string"}},
            "required":["grade","reason"], "additionalProperties":False} for key in ids},
            "required":ids, "additionalProperties":False}
        started = perf_counter()
        with tempfile.TemporaryDirectory(dir=ROOT / ".tools") as folder:
            folder = Path(folder)
            path = folder / "prompt.txt"
            schema_path = folder / "schema.json"
            schema_path.write_text(json.dumps(schema), encoding="utf-8")
            def generate(prompt, tokens, constrained=False):
                path.write_text(prompt, encoding="utf-8")
                args = [str(self.exe), "-m", str(self.model), "-f", str(path),
                        "-no-cnv", "--no-display-prompt", "--no-escape", "--simple-io",
                        "-t", "6", "-c", "4096", "-n", str(tokens), "--temp", "0.6",
                        "--top-p", "0.95", "--top-k", "20", "--min-p", "0", "--seed", "42", "--no-warmup"]
                if constrained:
                    args += ["-jf", str(schema_path)]
                result = subprocess.run(args, capture_output=True, timeout=240,
                    creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
                if result.returncode:
                    raise RuntimeError("Local judge failed")
                return result.stdout
            reasoning = generate(prefix, 512).decode("utf-8").split("</think>", 1)[0]
            # Force a final-answer phase even when the reasoning budget expires.
            final = generate(prefix + reasoning + "\n</think>\n\n", 768, True)
        return {"grades":parse_output(final.decode("utf-8"), ids),
                "elapsed_ms":round((perf_counter()-started)*1000,2),
                "output_sha256":hashlib.sha256(final).hexdigest()}


def run(output, calibration=False, judge_factory=BoundedJudge, controls_path=None):
    if output.exists():
        raise ValueError("Preserve earlier reports")
    controls_path = controls_path or ROOT / ("configs/relevance-judge-controls-v3.json" if calibration else "configs/relevance-judge-controls-v2.json")
    controls = json.loads(controls_path.read_text(encoding="utf-8"))["controls"]
    if not calibration:
        controls = [c for c in controls if c["id"] in {"soup-variant","juice-variant","embedded-command","exact-soup"}]
    judge = judge_factory()
    report = {"kind":"bounded_judge_calibration" if calibration else "bounded_judge_development_diagnostic",
        "created_at":datetime.now(timezone.utc).isoformat(), "complete":False, "admitted":False,
        "judge":judge.description, "controls_sha256":file_hash(controls_path),
        "evaluator_sha256":file_hash(Path(__file__)), "calibration":[], "calls":[],
        "commercial_calls":0, "judgments":[],
        "limitations":"AI-authored controls, not human preferences. Development controls cannot admit the judge. Calibration stops at the first failed batch; all 32 grades required for admission."}
    def save():
        output.parent.mkdir(parents=True, exist_ok=True)
        report["summary"] = {"correct":sum(r["passed"] for r in report["calibration"]),
            "total":len(report["calibration"]), "required":len(controls)*(4 if calibration else 2)}
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n",encoding="utf-8")
    save()
    try:
        for language in ("pt","en"):
            for reverse in ((False,True) if calibration else (False,)):
                ordered = list(reversed(controls)) if reverse else controls
                for start in range(0,len(ordered),4):
                    batch=ordered[start:start+4]
                    result=judge.grade([{"id":"c"+str(i),"query":c[language],"name":c["name"]} for i,c in enumerate(batch)])
                    rows=[{"id":c["id"],"language":language,"reverse":reverse,"expected":c["expected"],
                        **result["grades"]["c"+str(i)],"passed":result["grades"]["c"+str(i)]["grade"]==c["expected"]} for i,c in enumerate(batch)]
                    report["calibration"].extend(rows)
                    report["calls"].append({k:v for k,v in result.items() if k!="grades"})
                    save()
                    print(json.dumps(report["summary"]),flush=True)
                    if calibration and not all(r["passed"] for r in rows):
                        report["decision"]="rejected_failed_control_no_pool_scores"
                        return report
        report["complete"]=True
        report["admitted"]=calibration and all(r["passed"] for r in report["calibration"])
    except (ValueError,RuntimeError,subprocess.TimeoutExpired) as error:
        report["stop_reason"]=type(error).__name__
    finally:
        save()
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--calibration",action="store_true")
    args=parser.parse_args()
    run(args.output,args.calibration)
