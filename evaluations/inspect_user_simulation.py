"""Generate bounded behavioral-profile messages with Qwen3, then audit goal adherence.

Only accepted messages can become product requests. Rejected simulation is reported
separately, never counted as product failure or silently replaced by a script.
"""
import argparse
from datetime import datetime, timezone
from importlib.metadata import version
import json
from pathlib import Path
import re

from inspect_ai import Task, eval as inspect_eval
from inspect_ai.dataset import Sample
from inspect_ai.model import modelapi
from inspect_ai.scorer import Score, accuracy, scorer
from inspect_ai.solver import generate, system_message

from inspect_judge_calibration import LocalJudgeAPI, local_endpoint
from meal_discovery.dataset import file_hash
from meal_discovery.discovery import WORDS, fold, guarded_constraint

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = {"type": "object", "properties": {"messages": {"type": "array", "items": {"type": "string"},
          "minItems": 1, "maxItems": 4}}, "required": ["messages"], "additionalProperties": False}
SYSTEM = """You simulate a bounded behavioral user profile for a historical food catalog.
Write one natural Portuguese user message for EACH supplied planned turn. Return only JSON {"messages":[...]},
with exactly the same number and order of planned turns. Preserve the explicit food, budget and action.
Do not add ingredients, cuisine, dietary constraints, prices, URLs, demographics or personal facts.
For a pure price refinement, use only 'até NUMBER unidades normalizadas' or 'no máximo NUMBER unidades normalizadas'.
For the initial greeting use only 'oi', 'olá', 'bom dia', 'boa tarde' or 'boa noite'.
For food requests, use concise polite wording and preserve every supplied core keyword in Portuguese or English.
For requests to recommend something without a dish, use 'Recomende algo' or 'Sugira opções'.
For restriction or malicious test requests, keep the original restriction or attempted SQL action explicit.
For food requests start with 'Por favor, gostaria de' followed by the requested food in Portuguese or English.
These are artificial test messages, not descriptions of real people. Never answer the user yourself.
"""


@modelapi(name="mesa-local-simulator")
class SimulatorAPI(LocalJudgeAPI):
    schema = SCHEMA


def validate_messages(case, completion):
    value = json.loads(completion)
    if not isinstance(value, dict) or set(value) != {"messages"} or not isinstance(value["messages"], list):
        raise ValueError("Invalid simulator output")
    messages = value["messages"]
    if len(messages) != len(case["turns"]):
        raise ValueError("Simulator changed the number of turns")
    polite = {"quero", "gostaria", "procuro", "buscar", "encontrar", "de", "do", "da", "com", "um", "uma",
              "e", "o", "a", "eu", "por", "favor", "para", "mim", "agora", "prefiro", "poderia", "me",
              "mostrar", "pode", "voce", "trazer", "comer", "beber", "prato", "bebida", "opcao", "please"}
    for original, message in zip(case["turns"], messages):
        if not isinstance(message, str) or not 1 <= len(message.strip()) <= 500:
            raise ValueError("Message length is outside the simulation contract")
        text = fold(message.strip())
        if original.get("preserve_query"):
            match = re.fullmatch(r"(?:ate|no maximo)\s*(\d+(?:[.,]\d+)?)\s+unidades?\s+normalizadas?[.!?\s]*", text)
            if not match or float(match.group(1).replace(",", ".")) != original["context_equals"]["max_price"]:
                raise ValueError("Simulator changed the explicit refinement budget")
        elif original["tool"] == "search_catalog":
            if original.get("message") and text == fold(original["message"].strip()):
                raise ValueError("Simulator copied the food request instead of generating a wording variation")
            tokens = re.findall(r"[^\W_]+", text)
            translated = {part for token in tokens for part in WORDS.get(token, token).split()}
            concepts = original["concepts"]
            if not all(any(term in translated for term in alternatives) for alternatives in concepts):
                raise ValueError("Simulator lost a required dish concept")
            allowed = polite | {term for alternatives in concepts for term in alternatives}
            if translated - allowed or guarded_constraint(message):
                raise ValueError("Simulator added an unsupported ingredient, constraint or action")
        elif original["tool"] == "recommend_items":
            if text.strip(".!? ") not in {"recomende algo", "sugira opcoes"}:
                raise ValueError("Simulator changed the recommendation action")
        elif case["profile"] == "uncertain":
            if text.strip(".!? ") not in {"oi", "ola", "bom dia", "boa tarde", "boa noite"}:
                raise ValueError("Simulator changed the greeting into a food request")
        elif case["profile"] == "newcomer":
            if not re.search(r"r\$|\breais\b|\bdollars\b", text):
                raise ValueError("Simulator lost the currency question")
        elif case["profile"] == "dietary_constraint":
            if not re.search(r"sem\s+gluten", text):
                raise ValueError("Simulator lost the gluten restriction")
        elif case["profile"] == "adversarial":
            if not re.search(r"execute.*sql", text):
                raise ValueError("Simulator lost the attempted SQL instruction")
        else:
            raise ValueError("No independent validation rule for this simulated profile")
    return messages


@scorer(metrics=[accuracy()])
def goal_adherence():
    async def score(state, target):
        try:
            messages = validate_messages(state.metadata["case"], state.output.completion)
            return Score(value=1, metadata={"accepted": True, "messages": messages})
        except (ValueError, KeyError, TypeError) as error:
            return Score(value=0, explanation=str(error), metadata={"accepted": False})
    return score


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--judge-url", default="http://127.0.0.1:8082")
    args = parser.parse_args()
    suite_path = args.output.with_name(args.output.stem + "-suite.json")
    if args.output.exists() or suite_path.exists():
        parser.error("Choose new simulation report and suite paths")
    source = ROOT / "configs/conversation-development-v1.json"
    cases = json.loads(source.read_text(encoding="utf-8"))["cases"]
    identifiers = {"direct-rice", "uncertain-tea", "budget-coffee", "changes_mind-noodles", "newcomer-currency",
                   "seed_selection-selected", "dietary_constraint-gluten", "adversarial-sql"}
    selected = [case for case in cases if case["id"] in identifiers]
    evaluator_hash = file_hash(Path(__file__))
    samples = []
    for case in selected:
        plans = []
        for turn in case["turns"]:
            if turn.get("preserve_query"):
                goal = {"action": "refine_price_only", "max_normalized_price": turn["context_equals"]["max_price"]}
            elif turn["tool"] == "search_catalog":
                goal = {"action": "request_food", "required_food_concepts": turn["concepts"]}
            elif turn["tool"] == "recommend_items":
                goal = {"action": "request_recommendations_without_a_dish"}
            else:
                goal = {"action": {"uncertain": "greet_only", "newcomer": "ask_if_prices_are_in_reais",
                                   "dietary_constraint": "request_food_sem_gluten",
                                   "adversarial": "attempt_to_execute_SQL_to_modify_products"}[case["profile"]]}
            plans.append(goal)
        samples.append(Sample(id=case["id"], input=json.dumps({"profile": case["profile"],
                       "planned_turns": plans}, ensure_ascii=False), metadata={"case": case}))
    logs = inspect_eval(Task(name="mesa_bounded_user_simulation_v1", dataset=samples,
                        solver=[system_message(SYSTEM), generate()], scorer=goal_adherence()),
                        model="mesa-local-simulator/meal-local", model_base_url=local_endpoint(args.judge_url),
                        max_samples=1, max_retries=0, max_tokens=256, temperature=0.7,
                        log_model_api=False, ctl_server=False, acp_server=False,
                        log_dir=str(ROOT / "reports/inspect-user-simulation"), display="plain")
    log = logs[0]
    if log.status != "success" or len(log.samples or []) != len(samples):
        raise RuntimeError("Incomplete user simulation")
    accepted = []
    rows = []
    for sample in log.samples:
        score = next(iter(sample.scores.values()))
        rows.append({"id": sample.id, **score.metadata, "rejection": score.explanation,
                     "raw_completion": sample.output.completion})
        if score.metadata["accepted"]:
            case = sample.metadata["case"]
            accepted.append({**case, "id": "generated-" + case["id"],
                "turns": [{**turn, "message": message} for turn, message in zip(case["turns"], score.metadata["messages"])]})
    original_by_id = {case["id"]: case for case in selected}
    accepted_rows = [row for row in rows if row["accepted"]]
    changed_turns = sum(fold(message.strip()) != fold(turn["message"].strip())
                        for row in accepted_rows for message, turn in
                        zip(row["messages"], original_by_id[row["id"]]["turns"]))
    report = {"kind": "actual_local_llm_bounded_user_simulation", "created_at": datetime.now(timezone.utc).isoformat(),
              "generation": {"temperature": 0.7, "seed": 42, "max_tokens": 256, "reasoning": "off"},
              "inspect_version": version("inspect-ai"), "evaluator_sha256": evaluator_hash,
              "source_suite_sha256": file_hash(source), "requested": len(selected), "accepted": len(accepted),
              "wording_changed_turns": changed_turns,
              "accepted_turns": sum(len(row["messages"]) for row in accepted_rows),
              "rows": rows, "model_configuration": json.loads((ROOT / "configs/judge-candidate-qwen3-v1.json").read_text(encoding="utf-8")),
              "model_usage": {k: v.model_dump() for k, v in log.stats.model_usage.items()},
              "limitations": ["Bounded AI paraphrase simulation, not demographic personas or representative human behavior.",
                              "Goal fidelity validated by restrictive lexical/action rules; not a semantic-fidelity benchmark.",
                              "Rejected simulations are excluded from product execution and reported separately."]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    with suite_path.open("x", encoding="utf-8") as stream:
        json.dump({"protocol_version": "llm-generated-conversations-v1", "split": "development_simulation",
                   "simulation_report_sha256": file_hash(args.output), "cases": accepted}, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"requested": len(selected), "accepted": len(accepted), "suite": str(suite_path)}))


if __name__ == "__main__":
    main()
