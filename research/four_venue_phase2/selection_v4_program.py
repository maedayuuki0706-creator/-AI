"""V4 stand-alone, leakage-guarded contextual learning from official B program + K finishes.

**Historical exploratory research only.** The original B archive was acquired
after its races and lacks race-by-race pre-deadline publication receipts.
Program variables are projected from an explicit allowlist; NEVER use actual
start, result, finish, post-race course, winning method, or paid odds as input.

Four venue models are fit exclusively from official normal races <=2026-06-30.
July-Sept and October holdouts remain reports, not prospective predictions.
Only standard-library Python is required. Nothing touches production AIs.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from hashlib import sha256
from itertools import permutations
import json
import math
from pathlib import Path

from research.scenario_v2 import engine as scenario
from .selection_v3 import historical_card, miss_type
from .evaluate_selection_v3 import JCD, load_json, manifests, _actual_lanes

VERSION = "official-B-program-PL-context-v4-historical-exploratory"
FEATURES = ("lane1", "lane2", "lane3", "lane4", "lane5",
            "national_win_rate", "local_win_rate", "motor_top2_rate",
            "boat_top2_rate", "racer_class")
CLASS_VALUE = {"A1": 1.0, "A2": 0.45, "B1": -0.45, "B2": -0.95}
COMBOS=tuple(permutations(range(1,7),3))
TRAIN_END="2026-06-30"
LEARNING_RATE=0.04
EPOCHS=95
L2=0.04
FEATURE_SCALES={"national_win_rate":2.0,"local_win_rate":2.0,
                "motor_top2_rate":15.0,"boat_top2_rate":15.0}


def project_B_only(r):
    """Strictly allowlisted PRE-RACE program fields. Drop post-race record entirely.

    Historical B program provenance is archived but timestamped *later* than
    race; pre-race availability is not verified, hence no live use.
    """
    boats=r.get("boats")
    if not isinstance(boats,list) or len(boats)!=6:
        return None
    result=[]
    for b in boats:
        p=b.get("program")
        lane=b.get("lane")
        if not p or not isinstance(p,dict) or not isinstance(lane,int) or lane not in range(1,7):
            return None
        if str(p.get("racer_id"))!=str(b.get("racer_id")) or p.get("lane")!=lane:
            return None
        if p.get("racer_class") not in CLASS_VALUE:
            return None
        row={"lane":lane,"racer_id":str(b["racer_id"]),
             "racer_class":p["racer_class"]}
        for field in FEATURE_SCALES:
            val=p.get(field)
            if isinstance(val,bool) or val is None:
                return None
            try:
                val=float(val)
            except (ValueError,TypeError):
                return None
            if not math.isfinite(val):
                return None
            if field.endswith("top2_rate") and not (0<=val<=100):
                return None
            if field.endswith("win_rate") and not (0<=val<=20):
                return None
            row[field]=val
        result.append(row)
    result.sort(key=lambda x:x["lane"])
    if [x["lane"] for x in result]!=[1,2,3,4,5,6] or len({x["racer_id"] for x in result})!=6:
        return None
    return result


def feature_rows(program):
    """Six boats × fixed training-time feature order, per-race centered."""
    if len(program)!=6 or [x["lane"] for x in program]!=[1,2,3,4,5,6]:
        raise ValueError("Bad projected race entrants")
    matrix=[]
    for boat in program:
        v=[float(boat["lane"]==i) for i in range(1,6)]
        for field in FEATURE_SCALES:
            v.append(boat[field]/FEATURE_SCALES[field])
        v.append(CLASS_VALUE[boat["racer_class"]])
        matrix.append(v)
    means=[sum(row[j] for row in matrix)/6 for j in range(len(FEATURES))]
    return [tuple(v-means[j] for j,v in enumerate(row)) for row in matrix]


def _finish_indices(record):
    """Actual K finishes: used ONLY for supervised train target/evaluation."""
    actual=_actual_lanes(record)
    if actual is None:
        return None
    # Note: K finish may be linked to individual racer; B/K racer-ID equality
    # must have been verified before this routine is called.
    return tuple(int(n)-1 for n in actual.split("-"))


def training_pairs(records,jcd):
    train=[]
    for r in records:
        if r.get("venue_code")!=jcd or r.get("date","")>TRAIN_END:
            continue
        if not (r.get("normal_eligible") and r.get("official_verified")):
            continue
        proj=project_B_only(r)
        if proj is None:
            continue
        outcome=_finish_indices(r)
        if outcome is None:
            continue
        train.append((r["race_id"],feature_rows(proj),outcome))
    train.sort(key=lambda x:x[0])
    return train


def softmax(weights,features,remaining):
    scores=[sum(w*v for w,v in zip(weights,features[i])) for i in remaining]
    high=max(scores)
    e=[math.exp(max(-50,min(50,v-high))) for v in scores]
    denom=sum(e)
    return [v/denom for v in e]


def train_model(records,jcd):
    """Train 10 coefficients per venue from past normal B program + K target only."""
    if jcd not in JCD:
        raise ValueError("Bad venue")
    pairs=training_pairs(records,jcd)
    if len(pairs)<200:
        raise ValueError("Too few officially verified B/K train pairs")
    weights=[0.0]*len(FEATURES)
    for epoch in range(EPOCHS):
        g=[0.0]*len(FEATURES)
        for _,features,finish in pairs:
            rest=list(range(6))
            for choice in finish:
                probs=softmax(weights,features,rest)
                for k in range(len(FEATURES)):
                    g[k]+=features[choice][k]-sum(p*features[idx][k] for p,idx in zip(probs,rest))
                rest.remove(choice)
        weights=[w+LEARNING_RATE*(gg/len(pairs)-L2*w) for w,gg in zip(weights,g)]
    # Freeze the exact projected historical input identities, not K result values.
    trace=[{"race_id":rid,"program_inputs":x} for rid,x,y in pairs]
    fingerprint=sha256(json.dumps(trace,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    m={"version":VERSION,"venue_code":jcd,"training_end":TRAIN_END,
       "training_n":len(pairs),"training_input_digest":fingerprint,
       "features":list(FEATURES),"weights":[round(w,10) for w in weights],
       "optimization":{"epochs":EPOCHS,"learning_rate":LEARNING_RATE,
                       "ridge_l2":L2,"loss":"Plackett-Luce top-3 choice",
                       "fixed_before_holdout_review":True},
       "training_ids":[x[0] for x in pairs],
       "data_availability":"historical B program archive was downloaded after racing; pre-deadline publication is NOT verified",
       "adoption_status":"offline_research_unvalidated",
       "calibrated":False}
    m["digest"]=scenario.digest(m)
    return m


def checked(m):
    scenario.verify(m)
    if m.get("version")!=VERSION or m.get("venue_code") not in JCD:
        raise ValueError("Wrong model")
    if m.get("training_end")!=TRAIN_END or len(m.get("features",[]))!=len(FEATURES) or tuple(m["features"])!=FEATURES:
        raise ValueError("Training or features changed")
    if len(m["weights"])!=len(FEATURES) or len(set(m["training_ids"]))!=m["training_n"]:
        raise ValueError("Training identity mismatch")
    if any(not str(x).startswith("202") or str(x)[:8]>"20260630" or str(x)[8:10]!=m["venue_code"] for x in m["training_ids"]):
        raise ValueError("Training label leakage")


def card(pre_program,m):
    """PL top-three distribution. 120 ranking positions, research score only."""
    checked(m)
    feat=feature_rows(pre_program)
    weights=m["weights"]
    ranked=[]
    for a,b,c in COMBOS:
        ps=[]
        remaining=list(range(6))
        for chosen in [a-1,b-1,c-1]:
            probs=softmax(weights,feat,remaining)
            ps.append(probs[remaining.index(chosen)])
            remaining.remove(chosen)
        ranked.append({"combination":f"{a}-{b}-{c}",
                       "uncalibrated_pl_strength":round(math.prod(ps),12)})
    ranked.sort(key=lambda row:(-row["uncalibrated_pl_strength"],row["combination"]))
    if len(ranked)!=120 or len({x["combination"] for x in ranked})!=120:
        raise ValueError("120 outcome coverage failed")
    # PL top-3 scores add to ~1 but are NOT true calibrated race probabilities.
    return ranked[:10],ranked


def score_history(records,models,baseline):
    """Same officially verified Jul-Oct17 races, B program available for each."""
    output=[]
    for r in records:
        code=r.get("venue_code")
        if code not in models or not (TRAIN_END < r.get("date","") <= "2026-10-17"):
            continue
        truth=_actual_lanes(r)
        projected=project_B_only(r)
        if not truth or projected is None:
            continue
        chosen,ranked=card(projected,models[code])
        new_card=[x["combination"] for x in chosen]
        compare_card=baseline[code]
        date=r["date"].replace("-","")
        cohort="history_jul_sep" if date<="20260930" else "history_oct1_17"
        output.append({"race_id":r["race_id"],"venue_code":code,"day":date,"cohort":cohort,
                       "outcome":truth,"V4_hit":truth in new_card,"A_hit":truth in compare_card,
                       "V4_card":new_card,"A_card":compare_card,
                       "V4_miss":miss_type(truth,new_card),
                       "recorded_actual_course_FOR_REVIEW_ONLY":[b.get("course") for b in r["boats"]],
                       "B_archive_available_as_of_race":False,
                       "derived_prediction_after_race":True})
    return output


def day_cluster_interval(rows,n_boot=1200):
    """Exploratory day-resampled paired difference; not independent from prior review."""
    import random
    buckets=defaultdict(list)
    for row in rows:
        buckets[row["day"]].append(int(row["V4_hit"])-int(row["A_hit"]))
    if not buckets:
        return None
    rng=random.Random(20261019)
    days=sorted(buckets)
    sampled=[]
    for _ in range(n_boot):
        chosen=[buckets[rng.choice(days)] for _ in days]
        sampled.append(sum(sum(s) for s in chosen)/sum(len(s) for s in chosen))
    sampled.sort()
    return [round(100*sampled[int(n_boot*.025)],2),round(100*sampled[int(n_boot*.975)],2)]


def analyze(records):
    baseline_models=manifests(Path(__file__).resolve().parent/"model_manifests")
    baseline={code:historical_card(base,"A") for code,base in baseline_models.items()}
    models={c:train_model(records,c) for c in JCD}
    rows=score_history(records,models,baseline)
    grouped=defaultdict(list)
    for r in rows:
        grouped[(r["venue_code"],r["cohort"])].append(r)
    diagnostics=[]
    for (code,cohort),r in sorted(grouped.items()):
        n=len(r)
        a=sum(x["A_hit"] for x in r)
        v=sum(x["V4_hit"] for x in r)
        diagnostics.append({
            "venue":code,"cohort":cohort,"graded":n,"A_hits":a,"V4_hits":v,
            "A_hit_pct":round(a*100/n,2),"V4_hit_pct":round(v*100/n,2),
            "delta_hits":v-a,"difference_pct":round((v-a)*100/n,2),
            "day_clusters":len({x["day"] for x in r}),
            "cluster_interval_pct":day_cluster_interval(r),
            "model_trained_n":models[code]["training_n"],
            "historic_k_course_unused_in_predictions":True,
            "prospective_races":0,
        })
    return {"version":VERSION,"models":models,"diagnostics":diagnostics,
            "all_rows":rows,
            "limits":[
                "Official B archive acquisition happened after the historical races. Historical availability is not time-proven",
                "Historical input lane is assumed course; recorded actual course is NOT used for prediction",
                "Only K finish results train supervised choice; heldout truth is used for evaluation only",
                "Validation/October periods were inspected in previous analyses, so no untouched prospective claims",
                "Predicted 120-way PL weights are UNCALIBRATED and not EV/odds",
                "No wind, tide or actual ST, actual winner method, live motor replacement, or actual race replay video input",
                "As-of-matched B program fields are not in Oct19 frozen specialist snapshots: V4 is NOT replayed on Oct19",
                "No live AI predictions, results, model state, model cron or delivery configuration changed",
            ]}


def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--history",required=True,type=Path)
    parser.add_argument("--out",required=True,type=Path)
    a=parser.parse_args()
    rows=load_json(a.history)
    if len(rows)!=8876:
        raise ValueError("Audited K history mismatch")
    report=analyze(rows)
    a.out.mkdir(parents=True,exist_ok=True)
    for code,mod in report["models"].items():
        path=a.out/("venue_"+code+"_model.json")
        path.write_text(json.dumps(mod,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    summary={k:v for k,v in report.items() if k not in ["models","all_rows"]}
    summary["model_digests"]={code:model["digest"] for code,model in report["models"].items()}
    (a.out/"v4_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (a.out/"v4_races.json").write_text(json.dumps(report["all_rows"],ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("CONTEXT_LEARNING="+json.dumps({"summary":summary["diagnostics"],
      "train_counts":{code:mod["training_n"] for code,mod in report["models"].items()}},ensure_ascii=False))
    # Small durable registry may be copied verbatim to a research-only manifest.
    # Full inputs/training IDs remain in the reproducible Actions artifact.
    print("MODEL_REGISTRY="+json.dumps({
        code:{"version":mod["version"],"training_n":mod["training_n"],
              "training_end":mod["training_end"],"data_input_sha256":mod["training_input_digest"],
              "model_digest":mod["digest"],"weights_by_feature":dict(zip(mod["features"],mod["weights"])),
              "adoption_status":mod["adoption_status"],"historical_B_asof_verified":False}
        for code,mod in report["models"].items()},ensure_ascii=False,sort_keys=True))


if __name__=="__main__":
    main()
