"""Research-only Qwen reasoning comparison; no deployment or provider keys.

The earlier failed controls are development diagnostics, never a fresh holdout.
Only final grades and short evidence statements are stored, not reasoning traces.
"""
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


def parse_thinking_output(text, ids):
    # The opening think tag is part of the input prefix. Missing closure means
    # truncation, never a valid final answer. Do not extract arbitrary JSON from
    # inside reasoning or accept a partial answer.
    if text.count("</think>") != 1:
        raise ValueError("Missing or ambiguous final-answer boundary")
    _, final = text.split("</think>", 1)
    final = final.strip().replace("\r\n", "\n")
    if final.endswith("[end of text]"):
        final = final[:-len("[end of text]")].strip()
    # Accept only a single complete JSON fence; never search for JSON within prose.
    if final.startswith("```json\n") and final.endswith("```"):
        final = final[len("```json\n"):-3].strip()
    return parse_output(final, ids)


class ThinkingJudge(Judge):
    def __init__(self, seed=42):
        super().__init__()
        self.seed = seed
        self.description.update(
            temperature=0.6, top_p=0.95, top_k=20, min_p=0,
            seed=seed, max_tokens=2048, reasoning="enabled",
            template="explicit_Qwen_ChatML_with_open_think",
            sampling_reference="https://huggingface.co/Qwen/Qwen3-8B",
            output="unconstrained generation, strict final JSON validation",
        )

    def grade(self, candidates):
        ids = [c["id"] for c in candidates]
        user = json.dumps(candidates, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")
        prompt = f"<|im_start|>system\n{SYSTEM}<|im_end|>\n<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n<think>\n"
        started = perf_counter()
        with tempfile.TemporaryDirectory(dir=ROOT / ".tools") as folder:
            path = Path(folder) / "prompt.txt"
            path.write_text(prompt, encoding="utf-8")
            result = subprocess.run([
                str(self.exe), "-m", str(self.model), "-f", str(path),
                "-no-cnv", "--no-display-prompt", "--no-escape", "--simple-io",
                "-t", "6", "-c", "4096", "-n", "2048",
                "--temp", "0.6", "--top-p", "0.95", "--top-k", "20", "--min-p", "0",
                "--seed", str(self.seed), "--no-warmup",
            ], capture_output=True, timeout=420,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            raise RuntimeError("Local judge exited unsuccessfully")
        grades = parse_thinking_output(result.stdout.decode("utf-8"), ids)
        return {"grades": grades, "elapsed_ms": round((perf_counter()-started)*1000, 2),
                "output_sha256": hashlib.sha256(result.stdout).hexdigest()}


def diagnose(output, languages=("pt", "en")):
    if output.exists():
        raise ValueError("Preserve previous reports")
    controls_path = ROOT / "configs/relevance-judge-controls-v2.json"
    controls = json.loads(controls_path.read_text(encoding="utf-8"))["controls"]
    # One bounded diagnostic batch contains prior errors plus an exact match.
    ids = {"soup-variant", "juice-variant", "embedded-command", "exact-soup"}
    controls = [c for c in controls if c["id"] in ids]
    judge = ThinkingJudge()
    report = {"kind": "thinking_judge_development_diagnostic",
              "created_at": datetime.now(timezone.utc).isoformat(),
              "complete": False, "admitted": False, "judge": judge.description,
              "controls_sha256": file_hash(controls_path),
              "evaluator_sha256": file_hash(Path(__file__)),
              "rows": [], "calls": [], "commercial_calls": 0,
              "limitations": "Previously observed controls; diagnostic only, not held-out calibration or permission to score the catalog."}
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        for language in languages:
            candidates = [{"id": c["id"], "query": c[language], "name": c["name"]} for c in controls]
            result = judge.grade(candidates)
            report["calls"].append({k:v for k,v in result.items() if k != "grades"})
            report["rows"].extend({"id": c["id"], "language": language, "expected": c["expected"],
                                  **result["grades"][c["id"]],
                                  "passed": result["grades"][c["id"]]["grade"] == c["expected"]} for c in controls)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
            print(json.dumps({"language":language, "passed":sum(x["passed"] for x in report["rows"]), "completed":len(report["rows"])}), flush=True)
        report["complete"] = True
    except (ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        report["stop_reason"] = type(error).__name__
        if isinstance(error, ValueError):
            report["validation_failure"] = "final_boundary" if "boundary" in str(error) else "final_json_schema"
    finally:
        report["summary"] = {"correct":sum(x["passed"] for x in report["rows"]), "total":len(report["rows"])}
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--language", choices=("pt", "en"))
    args = parser.parse_args()
    result = diagnose(args.output, (args.language,) if args.language else ("pt", "en"))
    print(json.dumps(result["summary"]))
