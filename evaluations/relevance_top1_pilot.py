"""Name-only top-1 pilot, gated by frozen independent calibration controls."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from relevance_judge_guarded import GuardedJudge, ROOT
from meal_discovery.dataset import file_hash


def require_admission(calibration, source_hash, controls):
    rows=calibration.get("calibration",[])
    expected={(c["id"], language, reverse):c["expected"] for c in controls
              for language in ("pt","en") for reverse in (False,True)}
    actual={(r.get("id"),r.get("language"),r.get("reverse")):r.get("grade") for r in rows}
    if not (calibration.get("complete") is True and calibration.get("admitted") is True
            and calibration.get("evaluator_sha256")==source_hash and len(rows)==32
            and len(expected)==32 and actual==expected
            and all(r.get("passed") is True and r.get("grade")==r.get("expected") for r in rows)):
        raise ValueError("A complete matching 32/32 calibration is required")


def summarize(rows):
    groups=defaultdict(list)
    for row in rows:
        groups[row["mode"]].append(row)
    summary={}
    for mode, values in groups.items():
        known=[r for r in values if r["grade"] != -1]
        summary[mode]={"queries":len(values), "scored_queries":len(known),
            "full_match_rate_at_1":sum(r["grade"]==2 for r in known)/len(known) if known else None,
            "partial_matches":sum(r["grade"]==1 for r in values),
            "unrelated":sum(r["grade"]==0 for r in values),
            "abstentions":sum(r["grade"]==-1 for r in values),
            "empty_results":sum(r["empty"] for r in values)}
    return summary


def run(output, calibration_path):
    if output.exists():
        raise ValueError("Preserve previous reports")
    calibration=json.loads(calibration_path.read_text(encoding="utf-8"))
    inference_hash=file_hash(ROOT/"evaluations/relevance_judge_bounded.py")
    controls_path=ROOT/"configs/relevance-judge-controls-v5.json"
    if calibration.get("controls_sha256") != file_hash(controls_path):
        raise ValueError("Calibration controls changed")
    require_admission(calibration,inference_hash,json.loads(controls_path.read_text(encoding="utf-8"))["controls"])
    protocol_path=ROOT/"configs/relevance-top1-pilot-v1.json"
    protocol=json.loads(protocol_path.read_text(encoding="utf-8"))
    retrieval_path=ROOT/protocol["retrieval"]
    retrieval=json.loads(retrieval_path.read_text(encoding="utf-8"))
    if not retrieval.get("complete"):
        raise ValueError("Incomplete retrieval evidence")
    pool={}
    for row in retrieval["rows"]:
        if row["items"]:
            item=row["items"][0]
            pool[(row["id"],row["language"],item["name"])]=row["query"]
    keys=sorted(pool,key=lambda k:hashlib.sha256(json.dumps(k).encode()).hexdigest())
    judge=GuardedJudge()
    if judge.description != calibration["judge"]:
        raise ValueError("Judge configuration differs from calibration")
    report={"kind":protocol["kind"], "complete":False,"created_at":datetime.now(timezone.utc).isoformat(),
        "protocol":protocol,"protocol_sha256":file_hash(protocol_path),
        "retrieval_sha256":file_hash(retrieval_path),"calibration_sha256":file_hash(calibration_path),
        "inference_sha256":inference_hash,"evaluator_sha256":file_hash(Path(__file__)),
        "judge":judge.description,"judgments":[],"calls":[],"rows":[],"summary":{},"commercial_calls":0}
    grades={}
    def save():
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    save()
    try:
        for start in range(0,len(keys),4):
            batch=keys[start:start+4]
            result=judge.grade([{"id":"c"+str(i),"query":pool[k],"name":k[2]} for i,k in enumerate(batch)])
            for i,key in enumerate(batch):
                grades[key]=result["grades"]["c"+str(i)]
                report["judgments"].append({"concept":key[0],"language":key[1],"name":key[2],**grades[key]})
            report["calls"].append({k:v for k,v in result.items() if k!="grades"})
            save()
            print(json.dumps({"graded":len(grades),"required":len(keys)}),flush=True)
        for row in retrieval["rows"]:
            item=row["items"][0] if row["items"] else None
            grade=grades[(row["id"],row["language"],item["name"])] if item else {"grade":None,"reason":"No result returned"}
            report["rows"].append({"concept":row["id"],"language":row["language"],"mode":row["mode"],
                "query":row["query"],"item":item,"empty":item is None,**grade})
        report["summary"]=summarize(report["rows"])
        report["complete"]=True
    finally:
        save()
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--calibration",type=Path,required=True)
    args=parser.parse_args()
    run(args.output,args.calibration)
