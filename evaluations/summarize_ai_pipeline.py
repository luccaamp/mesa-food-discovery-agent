"""Derive public AI experiment counts without turning judge opinion into acceptance."""
import json
from pathlib import Path

from meal_discovery.dataset import file_hash

ROOT = Path(__file__).resolve().parents[1] / "evaluations/results"


def summarize(directory=ROOT):
    files = {name: directory / filename for name, filename in {
        "simulation": "user-simulation-v4.json", "execution": "generated-conversations-v3.json",
        "en": "judge-calibration-qwen3-en-schema-v1.json", "pt": "judge-calibration-qwen3-pt-schema-v1.json",
        "advisory": "conversation-advisory-v1.json"}.items()}
    data = {name: json.loads(path.read_text(encoding="utf-8")) for name, path in files.items()}
    if not data["execution"]["complete"]:
        raise ValueError("Simulation execution incomplete")
    if data["execution"]["summary"]["episodes"] != data["simulation"]["accepted"]:
        raise ValueError("Accepted simulation and executed episode coverage differ")
    return {"kind": "recorded_local_ai_pipeline", "simulator_requested": data["simulation"]["requested"],
            "simulator_accepted": data["simulation"]["accepted"],
            "wording_changed_turns": data["simulation"]["wording_changed_turns"],
            "generated_episodes_passed": data["execution"]["summary"]["passed"],
            "generated_episodes": data["execution"]["summary"]["episodes"],
            "judge_controls_passed": data["en"]["passed"] + data["pt"]["passed"],
            "judge_judgments": data["en"]["judgments"] + data["pt"]["judgments"],
            "advisory_reviews": len(data["advisory"]["rows"]),
            "advisory_valid": sum(row["valid"] for row in data["advisory"]["rows"]),
            "qualitative_score_status": "withheld; initial pilot revealed judge/rubric errors; no product acceptance from opinion",
            "source_report_sha256": {name: file_hash(path) for name, path in files.items()},
            "limitations": ["Bounded artificial profiles; lexical validation can reject legitimate paraphrases.",
                            "Factual judge calibration does not establish qualitative-score validity or human preference alignment.",
                            "Local experiments do not measure the public Gemini service."]}


if __name__ == "__main__":
    with (ROOT / "ai-pipeline-summary-v1.json").open("x", encoding="utf-8") as stream:
        json.dump(summarize(), stream, ensure_ascii=False, indent=2)
        stream.write("\n")
