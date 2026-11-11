"""Run a pinned local judge in its own process; always stop the owned server."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen

from meal_discovery.dataset import file_hash

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--language", choices=("en", "pt"), default="en")
    parser.add_argument("--task", choices=("calibration", "review", "simulation"), default="calibration")
    parser.add_argument("--evidence-first", action="store_true")
    parser.add_argument("--reasoning", choices=("off", "on"), default="off")
    parser.add_argument("--max-tokens", type=int, choices=(256, 1024), default=256)
    parser.add_argument("--review-case-id", action="append", default=[])
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose a new report path")
    pin = json.loads((ROOT / "configs/judge-candidate-qwen3-v1.json").read_text(encoding="utf-8"))
    model = ROOT / "models/judge-qwen3-v1" / pin["file"]
    if file_hash(model) != pin["sha256"]:
        parser.error("Judge model checksum differs")
    server = subprocess.Popen([str(ROOT / ".tools/llama-b12182/llama-server.exe"), "-m", str(model),
        "--host", "127.0.0.1", "--port", "8082", "--alias", "meal-local", "--ctx-size", "4096",
        "--threads", "6", "--threads-batch", "6", "--parallel", "1", "--n-gpu-layers", "0",
        "--timeout", "60", "--no-webui", "--log-disable", "--jinja", "--reasoning", args.reasoning,
        "--reasoning-budget", "512" if args.reasoning == "on" else "0"],
        cwd=ROOT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        deadline = time.monotonic() + 90
        while True:
            if server.poll() is not None:
                raise RuntimeError("Judge server exited")
            try:
                with urlopen("http://127.0.0.1:8082/health", timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                if time.monotonic() > deadline:
                    raise RuntimeError("Judge server did not become ready")
                time.sleep(.2)
        task_args = (["evaluations/inspect_judge_calibration.py", "--model-config", "configs/judge-candidate-qwen3-v1.json", "--language", args.language]
                     if args.task == "calibration" else ["evaluations/inspect_conversation_review.py" if args.task == "review" else "evaluations/inspect_user_simulation.py"])
        if args.evidence_first:
            if args.task != "calibration":
                parser.error("Evidence ordering applies to calibration only")
            task_args.append("--evidence-first")
        if args.task == "calibration":
            task_args.extend(["--max-tokens", str(args.max_tokens), "--runtime-reasoning", args.reasoning])
        if args.task == "review":
            for identifier in args.review_case_id:
                task_args.extend(["--case-id", identifier])
        result = subprocess.run([str(ROOT / ".tools/eval-venv/Scripts/python.exe"), *task_args,
            "--judge-url", "http://127.0.0.1:8082", "--output", str(args.output)],
            cwd=ROOT, timeout=900, check=False)
        sys.exit(result.returncode)
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)
