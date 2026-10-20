"""One-shot research-only bridge from EXISTING specialist remote originals to new fusion receipts.

This never scrapes BOAT RACE, invokes a production or existing research worker,
or touches the existing specialist state. It only uses official originals
already received by the existing four-venue worker, optionally creates NEW
Main-core / Yuuki / venue 10-ticket cards, and writes to the independent
research-venue-fusion-forward-state branch.

Default is preflight/dry-run. An explicit --publish is needed for network Git
pushes. No perpetual scheduler or delivery hooks. Use with a separate GitHub
checkout of the two research state branches.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta
import json
from pathlib import Path
import re

from research.scenario_v2 import engine as scenario
from . import prospective
from . import remote_receipt as remote

VERSION="fusion-existing-specialist-origin-bridge-v1"
ORIG_SOURCE_BRANCH="research-venue-specialists-state"
ORIG_PREFIX="data/venue_specialists_v1"


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def verify_original(input_file, source_root):
    """Existing remotely saved original must be intact and received on time."""
    source_root=Path(source_root).resolve()
    snapshot=_read(input_file)
    scenario.reject_outcomes(snapshot)
    meta=snapshot["meta"]
    rid=f'{meta["day"]}_{str(meta["jcd"]).zfill(2)}_{int(meta["rno"]):02d}'
    remote.source_paths(rid)
    expected=f"{ORIG_PREFIX}/inputs/{meta['day']}/{rid}.json"
    if Path(input_file).resolve() != (source_root/expected).resolve():
        raise ValueError("Official research input is not at its canonical path")
    old_receipt_path=source_root/f"{ORIG_PREFIX}/receipts/{meta['day']}/{rid}.json"
    old_forecast_path=source_root/f"{ORIG_PREFIX}/forecasts/{meta['day']}/{rid}.json"
    if not old_receipt_path.is_file() or not old_forecast_path.is_file():
        raise ValueError("Original source does not have remotely received forecast")
    proof=_read(old_receipt_path)
    forecast=_read(old_forecast_path)
    if proof.get("race_id")!=rid or forecast.get("race_id")!=rid:
        raise ValueError("Existing original race differs from receipt")
    if proof.get("status")!="confirmed_before_deadline" or proof.get("complete_originals_verified") is not True:
        raise ValueError("Original official input does not have a pre-deadline remote receipt")
    scenario.verify(forecast)
    if proof.get("digest")!=forecast["digest"] or proof.get("snapshot_digest")!=scenario.digest(snapshot):
        raise ValueError("Original frozen input/forecast digest does not match receipt")
    if forecast.get("snapshot_digest")!=proof["snapshot_digest"]:
        raise ValueError("Original forecast was computed from different input")
    if not snapshot.get("official_originals") or set(snapshot["official_originals"])!={"racelist","beforeinfo"}:
        raise ValueError("Missing archived original official HTML")
    deadline=scenario.aware(forecast["deadline_at"])
    captured=scenario.aware(meta["captured_at"])
    acknowledged=scenario.aware(proof["checked_at"])
    if not captured<=acknowledged<deadline-timedelta(minutes=3):
        raise ValueError("Original specialist receipt too late")
    original_sha=proof.get("commit_sha","")
    if not re.fullmatch(r"[a-f0-9]{40}",str(original_sha)):
        raise ValueError("Original remote commit SHA missing")
    # The old origin is read-only. Require original SHA to be on its history.
    remote._run(source_root,"merge-base","--is-ancestor",original_sha,"HEAD")
    prior_path=str(proof.get("forecast_path") or "")
    prior_input=str(proof.get("input_path") or "")
    expected_forecast=f"{ORIG_PREFIX}/forecasts/{meta['day']}/{rid}.json"
    if prior_path!=expected_forecast or prior_input!=expected:
        raise ValueError("Existing remote original receipt paths differ")
    old_bytes=remote._run(source_root,"show",f"{original_sha}:{prior_path}",binary=True)
    old_object=json.loads(old_bytes)
    if old_object.get("digest")!=forecast["digest"] or scenario.digest(old_object)!=forecast["digest"]:
        # note: digest(object) including digest is not equal to signed digest.
        if old_object.get("digest")!=forecast["digest"] or scenario.digest({
            k:v for k,v in old_object.items() if k!="digest"})!=forecast["digest"]:
            raise ValueError("Original specialist remote Git forecast differs")
    input_bytes=remote._run(source_root,"show",f"{original_sha}:{prior_input}",binary=True)
    if scenario.digest(json.loads(input_bytes))!=proof["snapshot_digest"]:
        raise ValueError("Original specialist input not in the original remote commit")
    return rid,snapshot,{
        "source_receipt_commit_sha":original_sha,
        "source_receipt_checked_at":proof["checked_at"],
        "source_forecast_digest":forecast["digest"],
        "source_input_digest":proof["snapshot_digest"],
        "source_remote_received_before_deadline":True,
    }


def scan_inputs(source_root,now=None):
    now=scenario.aware(now or datetime.now(scenario.JST).isoformat())
    day=now.strftime("%Y%m%d")
    root=Path(source_root)
    paths=list((root/ORIG_PREFIX/"inputs"/day).glob(f"{day}_*.json"))
    # The input file can be published 4-28m before the deadline. Order by the
    # deadline string from the original page, not by filename or venue.
    metadata=[]
    for path in paths:
        try:
            s=_read(path)
            m=s["meta"]
            hhmm=str(m["deadline"])
            metadata.append((hhmm,path))
        except (OSError,KeyError,ValueError,TypeError):
            metadata.append(("99:99",path))
    return [p for _,p in sorted(metadata)]


def process(source_root, target_root, scratch, *, clock=None, max_races=2, publish=False):
    """Short one-shot scan. Never reconnect to official servers or replay yesterday."""
    clock=clock or remote.now_jst
    if max_races<1 or max_races>12:
        raise ValueError("Bounded research pilot: 1..12 races per run")
    source_root=Path(source_root).resolve()
    target_root=Path(target_root).resolve()
    scratch=Path(scratch).resolve()
    if source_root==target_root or scratch in (source_root,target_root):
        raise ValueError("Source, target and scratch must be disjoint")
    today=remote._clock(clock)
    # Old source must correspond to the original read-only branch, not main.
    current_branch=remote._run(source_root,"symbolic-ref","--quiet","--short","HEAD").strip()
    if current_branch!=ORIG_SOURCE_BRANCH:
        raise ValueError("Original research source checkout must have its own branch")
    if publish:
        remote._assert_worktree(target_root)
    attempts=0
    out={"version":VERSION,"research_only":True,
         "day":today.strftime("%Y%m%d"),"checked_at":today.isoformat(),
         "published":[],"dry_run_verified":[],"skipped":[],
         "publish_mode":publish,"not_a_production_prediction":True,
         "new_model_prospective_grade_count":0}
    for source_file in scan_inputs(source_root,today.isoformat()):
        if attempts>=max_races:break
        id_from_file=source_file.stem
        if (target_root/remote.source_paths(id_from_file)[0]).exists():
            out["skipped"].append({"race_id":id_from_file,"reason":"already_frozen_independent_state"})
            continue
        try:
            rid,snapshot,old=verify_original(source_file,source_root)
            real_clock=remote._clock(clock)
            deadline=scenario.aware(
                snapshot["meta"]["day"][:4]+"-"+snapshot["meta"]["day"][4:6]+"-"+
                snapshot["meta"]["day"][6:8]+"T"+snapshot["meta"]["deadline"]+":00+09:00")
            # Don't start expensive research if there is not time to read back
            # both independent remote commits before the -3m safety cutoff.
            if deadline-real_clock<timedelta(minutes=5):
                raise ValueError("Too close to cutoff to safely publish")
            if real_clock.strftime("%Y%m%d")!=snapshot["meta"]["day"]:
                raise ValueError("Race day expired")
            card=prospective.build_live(snapshot,now=real_clock.isoformat())
            if card.get("input_digest")!=old["source_input_digest"]:
                raise ValueError("Main-core used a different official source")
            local=scratch/"locally_frozen"/f"{rid}.json"
            prospective.save_local_only(card,local)
            if not publish:
                out["dry_run_verified"].append({
                    "race_id":rid,"generated_at":card["generated_at"],
                    "existing_specialist_commit_sha":old["source_receipt_commit_sha"],
                    "new_fusion_card_digest":card["digest"],
                    "remote_received":False})
            else:
                receipt=remote.publish(card,target_root,clock=clock)
                out["published"].append({
                    "race_id":rid,"existing_specialist_commit_sha":old["source_receipt_commit_sha"],
                    "new_fusion_card_digest":card["digest"],
                    "remote_receipt_commit_sha":receipt["receipt_commit_sha"],
                    "receipt_observed_at":receipt["remote_receipt_observed_at"],
                    "note":"Runner clock remote receipt only; requires independent official result grading"})
            attempts+=1
        except (ValueError,KeyError,TypeError,FileNotFoundError,RuntimeError,OSError,
                __import__("subprocess").CalledProcessError) as exc:
            # A fatal publisher error may leave one immutable remote forecast
            # without a receipt. Report, retain local evidence; NEVER backfill.
            out["skipped"].append({"race_id":id_from_file,"reason":type(exc).__name__,
                                    "detail":str(exc)[:250]})
    scratch.mkdir(parents=True,exist_ok=True)
    (scratch/"pilot_status.json").write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return out


def main():
    p=argparse.ArgumentParser(description="Independent one-shot (default dry run) forward research, no prod effects")
    p.add_argument("--source",required=True,type=Path)
    p.add_argument("--state",required=True,type=Path)
    p.add_argument("--scratch",required=True,type=Path)
    p.add_argument("--max-races",type=int,default=2)
    p.add_argument("--publish",action="store_true",help="EXPLICIT isolated research-state Git push; never default")
    a=p.parse_args()
    result=process(a.source,a.state,a.scratch,max_races=a.max_races,publish=a.publish)
    print("FUSION_ONE_SHOT="+json.dumps(result,ensure_ascii=False))
    if a.publish and not result["published"]:
        print("No remote fusion receipt created; any would-be scores remain 0 (safe no-op).")


if __name__=="__main__":
    main()
