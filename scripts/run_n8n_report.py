"""Execute the actual local n8n workflow and export sanitized evidence only."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]


def execute(workflow_id="mealEvaluationV1"):
    node = ROOT / ".tools/node-v24.22.2-win-x64/node.exe"
    cli = ROOT / ".tools/n8n/node_modules/n8n/bin/n8n"
    if not node.is_file() or not cli.is_file():
        raise ValueError("Install the pinned local Node 24/n8n runtime; see evaluations/n8n/README.md")
    env = {**os.environ, "N8N_DIAGNOSTICS_ENABLED": "false", "N8N_VERSION_NOTIFICATIONS_ENABLED": "false",
           "N8N_PERSONALIZATION_ENABLED": "false", "N8N_USER_FOLDER": str(ROOT / ".tools/n8n-state"),
           "PATH": str(node.parent) + os.pathsep + os.environ.get("PATH", "")}
    temporary = ROOT / ".tools/test-temp"
    temporary.mkdir(parents=True, exist_ok=True)
    env.update(TMP=str(temporary), TEMP=str(temporary))
    started = perf_counter()
    if workflow_id not in {"mealEvaluationV1", "mealEvaluationV2"}:
        raise ValueError("Unknown versioned evaluation workflow")
    result = subprocess.run([str(node), str(cli), "execute", "--id=" + workflow_id, "--rawOutput"],
                            cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    if result.returncode:
        raise ValueError("n8n execution failed; inspect the local instance without publishing its raw logs")
    payload = None
    decoder = json.JSONDecoder()
    for offset, character in enumerate(result.stdout):
        if character == "{":
            try:
                value, _ = decoder.raw_decode(result.stdout[offset:])
                if isinstance(value, dict) and "data" in value and "status" in value:
                    payload = value
                    break
            except ValueError:
                pass
    if not payload or payload.get("status") != "success":
        raise ValueError("n8n did not produce a successful execution")
    run = payload["data"]["resultData"]["runData"]
    output = run["Validar e gerar relatório"][-1]["data"]["main"][0][0]["json"]
    if output.get("official_test_evaluated") is not False or output.get("schema_version") != 1:
        raise ValueError("Unexpected workflow output contract")
    markdown = output["markdown"]
    summary = {"schema_version": 1, "workflow_id": workflow_id, "n8n_version": "2.46.6",
               "node_version": "24.22.2", "status": "success", "reports": output["reports"],
               "official_test_evaluated": False, "wall_time_ms": round((perf_counter() - started) * 1000, 2),
               "report_sha256": hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
               "nodes": [{"name": name, "status": values[-1]["executionStatus"], "execution_ms": values[-1]["executionTime"]}
                         for name, values in run.items()],
               "limits": "Measured real n8n CLI execution. No measured manual-time baseline; no claimed time saving. No external messages or credentials exported."}
    return summary, markdown


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    parser.add_argument("--workflow-id", choices=("mealEvaluationV1", "mealEvaluationV2"), default="mealEvaluationV1")
    args = parser.parse_args()
    if args.output.exists() or args.markdown.exists():
        parser.error("Choose new output paths")
    summary, markdown = execute(args.workflow_id)
    for path in (args.output, args.markdown):
        path.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2)
        stream.write("\n")
    with args.markdown.open("x", encoding="utf-8") as stream:
        stream.write(markdown)
    print(json.dumps(summary, indent=2))
