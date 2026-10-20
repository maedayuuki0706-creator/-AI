"""Fail-closed settlement of independently remotely received fusion forecasts.

Read-only remote history + one official post-race review. No outcome field is
ever passed into the forecaster. No local creation counts; both exact Git blob
histories must be accessible, verifiable and on the independent state branch.

Runner-clock remote observation is NOT an independent GitHub server timestamp;
report that limitation explicitly in every race row. Do not use inferred tactics.
"""
from __future__ import annotations

from collections import Counter
from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path
import re

from research.scenario_v2 import engine as scenario
from . import remote_receipt as rr
from .prospective import MODELS

GRADE_VERSION="venue-fusion-forward-independent-grader-v1"


def _checked_json(raw):
    j=json.loads(raw)
    if not isinstance(j,dict):
        raise ValueError("Expected one JSON object")
    return j


def _card_label(winner, picks):
    if winner in picks:return "hit"
    win=winner.split("-")
    if not any(p.split("-")[0]==win[0] for p in picks):
        return "head_not_in_ten"
    if not any(p.split("-")[:2]==win[:2] for p in picks):
        return "second_not_in_ten_after_head"
    return "third_not_in_ten_after_head_second"


def evidence(root, race_id, *, allow_local_origin_for_tests=False):
    """Fetch ONLY official Git research state branch; prove forecast and receipt history.

    Note: git commit timestamp is not sufficient external time attestation.
    This validates content, authorship history and *recorded* observer time.
    """
    root=Path(root).resolve()
    forecast_path,receipt_path=rr.source_paths(race_id)
    # Read-only remote ref fetch into ephemeral worktree branch; no pushes.
    remote_url=rr._run(root,"remote","get-url","origin").strip()
    if not allow_local_origin_for_tests and remote_url not in rr.REMOTE_URLS:
        raise ValueError("Only official research GitHub remote is allowed for grading")
    rr._run(root,"fetch","--no-tags","origin",
            f"refs/heads/{rr.REMOTE_BRANCH}:refs/remotes/origin/{rr.REMOTE_BRANCH}")
    remote_ref=f"refs/remotes/origin/{rr.REMOTE_BRANCH}"
    commits=rr._run(root,"log","--format=%H",remote_ref,"--",receipt_path).splitlines()
    if len(commits)!=1:
        raise ValueError("Missing or rewritten receipt; only one immutable creation commit accepted")
    receipt_sha=commits[0]
    proof_raw=rr._run(root,"show",f"{receipt_sha}:{receipt_path}",binary=True)
    proof=_checked_json(proof_raw)
    if proof.get("race_id")!=race_id or proof.get("remote_branch")!=rr.REMOTE_BRANCH:
        raise ValueError("Incorrect remote receipt identity")
    if proof.get("version")!=rr.VERSION or proof.get("status")!="remote_forecast_observed_before_cutoff":
        raise ValueError("Receipt version/status mismatch")
    if proof.get("count_as_prospective") is not False:
        raise ValueError("Remote receipt itself must not claim graded performance")
    scenario.verify(proof)
    prior_sha=proof.get("forecast_commit_sha")
    if not isinstance(prior_sha,str) or not re.fullmatch(r"[a-f0-9]{40}",prior_sha):
        raise ValueError("Missing immutable forecast commit SHA")
    rr._run(root,"merge-base","--is-ancestor",prior_sha,receipt_sha)
    creation=rr._run(root,"log","--format=%H",remote_ref,"--",forecast_path).splitlines()
    if len(creation)!=1 or creation[0]!=prior_sha:
        raise ValueError("Original forecast has been rewritten or replaced")
    fore_raw=rr._run(root,"show",f"{prior_sha}:{forecast_path}",binary=True)
    card=_checked_json(fore_raw)
    scenario.verify(card)
    if sha256(fore_raw).hexdigest()!=proof.get("forecast_file_sha256"):
        raise ValueError("Remote frozen forecast bytes do not match receipt")
    if card.get("race_id")!=race_id or card.get("digest")!=proof.get("forecast_digest"):
        raise ValueError("Remote original forecast digest mismatch")
    if card.get("input_digest")!=proof.get("original_input_digest"):
        raise ValueError("Input digest changed between forecast and receipt")
    if card.get("official_source_sha256")!=proof.get("official_source_sha256"):
        raise ValueError("Source original SHA changed")
    if card.get("research_only") is not True or card.get("count_as_prospective") is not False:
        raise ValueError("Wrong source forecast status")
    rr.source_paths(card["race_id"])
    if tuple(card.get("model_cards",{}))!=MODELS:
        raise ValueError("Missing one of the three models")
    for model,card_picks in card["model_cards"].items():
        if len(card_picks)!=10 or len(set(card_picks))!=10 or not set(card_picks)<=scenario.COMBINATIONS:
            raise ValueError("Incorrect fixed card")
    cutoff=scenario.aware(card["deadline_at"])-timedelta(minutes=3)
    when=[card["input_captured_at"],card["generated_at"],
          proof["remote_forecast_checked_at"]]
    clocktimes=[scenario.aware(v) for v in when]
    if not (clocktimes[0]<=clocktimes[1]<=clocktimes[2]<cutoff):
        raise ValueError("Forecast was not independently observed on time")
    if scenario.aware(proof["cutoff_at"])!=cutoff:
        raise ValueError("Official cutoff mismatch")
    if card.get("result_accessed") is not False or proof.get("no_results_read") is not True:
        raise ValueError("Forecast may have seen results")
    if card.get("status")!="local_frozen_unconfirmed":
        raise ValueError("Only original frozen cards count")
    # Independent Git commit committer clock (stronger than local marker
    # alone, but still not a GitHub server timestamp / cryptographic TSA).
    receipt_git_time=scenario.aware(rr._run(root,"show","-s","--format=%cI",receipt_sha).strip())
    if receipt_git_time>=cutoff or receipt_git_time<clocktimes[1]-timedelta(minutes=2):
        raise ValueError("Git receipt committed outside claimed forecast window")
    return {
        "forecast":card,"receipt":proof,"forecast_commit_sha":prior_sha,
        "receipt_commit_sha":receipt_sha,
        "receipt_git_commit_at":receipt_git_time.isoformat(),
        "source_branch":rr.REMOTE_BRANCH,
        "read_only_remote_git_verified":True,
        "runner_clock_not_server_time_attestation":True,
    }


def grade(saved,review):
    """Grade only *after* remote Git validation and official result observance."""
    if saved.get("read_only_remote_git_verified") is not True:
        raise ValueError("No independent Git receipt evidence")
    fore,proof=saved["forecast"],saved["receipt"]
    rid=fore["race_id"]
    if review.get("race_id")!=rid or str(review.get("jcd")).zfill(2)!=fore["venue_code"]:
        raise ValueError("Different official race/result")
    if review.get("status")!="graded" or review.get("refund_lanes") or not review.get("official_trifectas"):
        return {"race_id":rid,"status":"excluded","reason":"refund, ungraded or missing official payout",
                "count_as_prospective":False}
    if review.get("source")!="BOAT RACE official raceresult":
        raise ValueError("Unsupported result source")
    if review.get("digest"):
        scenario.verify(review)
    observed=scenario.aware(review["official_observed_at"])
    if observed<=scenario.aware(fore["deadline_at"]):
        raise ValueError("Result appears observed before the race deadline")
    winnings=review["official_trifectas"]
    if len(winnings)!=1:
        return {"race_id":rid,"status":"excluded","reason":"multi-payoff or dead heat; review manually",
                "count_as_prospective":False}
    winner,payout=next(iter(winnings.items()))
    if winner not in scenario.COMBINATIONS or isinstance(payout,bool) or not isinstance(payout,(int,float)) or payout<=0:
        raise ValueError("Invalid standard official winning combination or payment")
    # Original forecast may be v1 (cards only) or v2 (120 Main-core ranks
    # and all six tactical hypotheses). Never reconstruct tactical evidence
    # from today's code after knowing the official finish.
    ranked=fore.get("main_core_120_rank")
    if ranked is not None:
        if len(ranked)!=120 or set(x["combination"] for x in ranked)!=scenario.COMBINATIONS:
            raise ValueError("Corrupt original full 120-ranked candidate evidence")
        winner_rank=next(x["rank"] for x in ranked if x["combination"]==winner)
    else:
        winner_rank=None
    frozen_scenario=fore.get("scenario_formation_candidates")
    if frozen_scenario is None:
        winning_scenario_candidate=None
    else:
        if not isinstance(frozen_scenario,list) or not set(frozen_scenario).issubset(scenario.COMBINATIONS):
            raise ValueError("Corrupt original scenario candidate list")
        winning_scenario_candidate=winner in frozen_scenario
    six_tactics=fore.get("scenario_all_six")
    if six_tactics is not None and (len(six_tactics)!=6 or set(b["lane"] for b in six_tactics)!=set(range(1,7))):
        raise ValueError("Corrupt original six-boat tactical forecast")
    data={}
    for model,picks in fore["model_cards"].items():
        hit=winner in picks
        returned=int(round(payout)) if hit else 0
        data[model]={
            "hit":hit,
            "miss_reason":_card_label(winner,picks),
            "stake_yen":len(picks)*fore["per_ticket_stake_yen"],
            "return_yen":returned,
            "roi_pct":round(100*returned/(len(picks)*fore["per_ticket_stake_yen"]),2),
            "profit_yen":returned-len(picks)*fore["per_ticket_stake_yen"],
            "torigami":hit and returned<len(picks)*fore["per_ticket_stake_yen"],
            "picked_heads":list(dict.fromkeys(p[0] for p in picks)),
        }
    return {
        "version":GRADE_VERSION,"research_only":True,
        "race_id":rid,"venue_code":fore["venue_code"],"status":"graded",
        "count_as_prospective":True,
        "time_attestation_type":"research_runner_clock_plus_git_commit_time_NOT_independent_server_time",
        "original_input_digest":fore["input_digest"],"forecast_digest":fore["digest"],
        "forecast_commit_sha":saved["forecast_commit_sha"],
        "receipt_commit_sha":saved["receipt_commit_sha"],
        "official_review_digest":review.get("digest"),
        "official_observed_at":review["official_observed_at"],
        "winner":winner,"payout_yen_per_100":int(round(payout)),
        "per_model":data,
        "winning_main_core_rank_in_frozen_120":winner_rank,
        "winner_inside_frozen_scenario_candidates":winning_scenario_candidate,
        "frozen_six_tactical_paths_available":six_tactics is not None,
        "main_vs_yuuki_card_delta":fore.get("card_comparison"),
        "actual_1mark_tactics_verified":False,
        "model_is_full_production_main":False,
        "remarks":[
          "All three variants originated from the same pre-deadline original source",
          "No live grade without a pre-deadline remote forecast AND separate receipt",
          "Input/selection errors are not the true cause of tactical failure",
          "Research clock and Git commit timestamps are not a trusted external time authority",
        ],
    }


def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--state",type=Path,required=True,
                   help="Read-only copy of a Git repo with reachable research state branch")
    p.add_argument("--race-id",required=True)
    p.add_argument("--official-review",type=Path,required=True)
    opts=p.parse_args()
    out=grade(evidence(opts.state,opts.race_id),
              _checked_json(opts.official_review.read_bytes()))
    print(json.dumps(out,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
