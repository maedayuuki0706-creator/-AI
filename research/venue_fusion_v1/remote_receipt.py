"""Independent research-only Git remote receipt for *already live-frozen* 3 cards.

NEVER schedules or captures races, calls a delivery API, uses Sheets, or
modifies production. Never upgrades source forecast JSON after original freeze.
It publishes a separate receipt ONLY after verifying the forecast bytes can
be read from the named Git remote SHA before the -3 minute cutoff.

Clock is the executing runner's wall clock, not an independent GitHub server
clock. Actions job logs must be retained as supplementary timestamp evidence.
No guaranteed predictability or full-main parity claim.
"""
from __future__ import annotations

import argparse
from datetime import timedelta, datetime
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlparse

from research.scenario_v2 import engine as scenario
from .prospective import MODELS

VERSION="venue-fusion-remote-receipt-v1"
REMOTE_BRANCH="research-venue-fusion-forward-state"
REMOTE_URLS={
    "https://github.com/maedayuuki0706-creator/-AI",
    "https://github.com/maedayuuki0706-creator/-AI.git",
    "git@github.com:maedayuuki0706-creator/-AI.git",
}
RACE_RE=re.compile(r"^(\d{8})_(03|06|16|23)_(0[1-9]|1[0-2])$")
HEX64=re.compile(r"^[0-9a-f]{64}$")
SOURCE_PREFIX="data/venue_fusion_forward_v1"


def now_jst():
    return datetime.now(scenario.JST)


def source_paths(race_id):
    match=RACE_RE.fullmatch(race_id)
    if not match:
        raise ValueError("Malformed four-venue race ID")
    return (
        f"{SOURCE_PREFIX}/forecasts/{match.group(1)}/{race_id}.json",
        f"{SOURCE_PREFIX}/receipts/{match.group(1)}/{race_id}.json",
    )


def _clock(clock):
    value=clock()
    if isinstance(value,str):
        return scenario.aware(value)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timezone-aware runner clock mandatory")
    return value.astimezone(scenario.JST)


def validate_prepub(card, *, clock=now_jst):
    if not isinstance(card,dict):
        raise ValueError("Missing forecast record")
    # Includes checks for nested result leakage despite source schema changes.
    scenario.reject_outcomes(card)
    scenario.verify(card)
    race_id=card.get("race_id","")
    source_paths(race_id)
    if card.get("research_only") is not True or card.get("result_accessed") is not False:
        raise ValueError("Not an outcome-free research forecast")
    if card.get("status")!="local_frozen_unconfirmed":
        raise ValueError("Only original locally frozen / UNCONFIRMED cards can be published")
    if card.get("git_remote_receipt_confirmed") is not False or card.get("count_as_prospective") is not False:
        raise ValueError("Locally generated card has counterfeit remote receipt flags")
    if card.get("main_full_delivery_parity") is not False:
        raise ValueError("Original Main-core must not be reported as full Main")
    if tuple(card.get("model_cards",{}))!=MODELS:
        raise ValueError("Expected exactly the three original model identities")
    for model, picks in card["model_cards"].items():
        if len(picks)!=10 or len(set(picks))!=10 or not set(picks).issubset(scenario.COMBINATIONS):
            raise ValueError("Invalid fixed ten-ticket card: "+model)
    src=card.get("official_source_sha256","")
    if not isinstance(src,str) or not HEX64.fullmatch(src):
        raise ValueError("No verified original official-source hash")
    generated=scenario.aware(card["generated_at"])
    captured=scenario.aware(card["input_captured_at"])
    deadline=scenario.aware(card["deadline_at"])
    now=_clock(clock)
    prefix=card["race_id"].split("_")[0]
    if now.strftime("%Y%m%d")!=prefix or generated.strftime("%Y%m%d")!=prefix:
        raise ValueError("Only today's real live research is eligible")
    if card.get("day")!=prefix or card.get("venue_code")!=card["race_id"].split("_")[1]:
        raise ValueError("Inconsistent card race identity")
    if captured>generated or generated>now:
        raise ValueError("Future or inconsistent pre-race card timestamps")
    if (now-generated).total_seconds()>180:
        raise ValueError("Card too stale to publish as current live research")
    cutoff=deadline-timedelta(minutes=3)
    if generated>=cutoff or captured>=cutoff or now>=cutoff:
        raise ValueError("Receipt publication missed the safety cutoff")
    if card.get("ticket_count")!=10 or card.get("per_ticket_stake_yen")!=100:
        raise ValueError("Unexpected ticket stake/point count")
    return {"race_id":race_id,"cutoff":cutoff,"deadline":deadline,"checked_at":now}


def _run(root, *args, binary=False):
    cmd=["git","-C",str(root),*args]
    r=subprocess.run(cmd,check=True,capture_output=True,
                     **({} if binary else {"text":True}))
    return r.stdout


def _remote_head(root):
    text=_run(root,"ls-remote","origin",f"refs/heads/{REMOTE_BRANCH}").strip().split()
    if len(text)!=2 or text[1]!=f"refs/heads/{REMOTE_BRANCH}" or not re.fullmatch(r"[a-f0-9]{40}",text[0]):
        raise ValueError("Remote research state branch missing or ambiguous")
    return text[0]


def _assert_worktree(root, *, allow_local_origin_for_tests=False):
    root=Path(root).resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError("Research state git worktree required")
    b=_run(root,"symbolic-ref","--quiet","--short","HEAD").strip()
    if b!=REMOTE_BRANCH:
        raise ValueError("Refusing to write any Git branch except independent fusion state")
    url=_run(root,"remote","get-url","origin").strip()
    if not allow_local_origin_for_tests and url not in REMOTE_URLS:
        raise ValueError("Remote URL does not match allowed research GitHub repository")
    dirty=_run(root,"status","--porcelain")
    if dirty.strip():
        raise ValueError("Research state must be clean; never accidentally commit other work")
    return root


def _git_publish(root, path, content, message):
    dest=root/path
    dest.parent.mkdir(parents=True,exist_ok=True)
    if dest.exists():
        raise FileExistsError("Immutable forecast or receipt already exists: "+path)
    # For the initial research state, use exclusive write; no replacement.
    with dest.open("x",encoding="utf-8") as out:
        out.write(content)
    _run(root,"add","--",path)
    _run(root,"commit","-m",message,"--",path)
    sha=_run(root,"rev-parse","HEAD").strip()
    _run(root,"push","origin",f"HEAD:refs/heads/{REMOTE_BRANCH}")
    return sha


def _remote_exact(root, sha, path, expected_bytes, *, clock, cutoff):
    actual_sha=_remote_head(root)
    if actual_sha!=sha:
        raise ValueError("Remote head differs from pushed immutable candidate")
    _run(root,"fetch","--no-tags","origin",sha)
    data=_run(root,"show",f"{sha}:{path}",binary=True)
    if data!=expected_bytes:
        raise ValueError("Remote Git blob bytes/digest do not match local original")
    observed=_clock(clock)
    if observed>=cutoff:
        raise ValueError("Remote Git checked only after forecast safety cutoff")
    return observed


def publish(card, root, *, clock=now_jst, allow_local_origin_for_tests=False):
    """Publish one *current-day* frozen research card and its separate receipt.

    This function has remote Git effects on the ONLY specified independent
    research state branch. It MUST NOT be called for historic/replay cards.
    A failed network step may leave a remote forecast without receipt; it is
    categorically NOT graded and must not be overwritten/retried in place.
    """
    gate=validate_prepub(card,clock=clock)
    root=_assert_worktree(root,allow_local_origin_for_tests=allow_local_origin_for_tests)
    forecast_path,receipt_path=source_paths(card["race_id"])
    if (root/forecast_path).exists() or (root/receipt_path).exists():
        raise FileExistsError("Research race already frozen; do not update or duplicate")
    existing=_remote_head(root)
    local=_run(root,"rev-parse","HEAD").strip()
    if existing!=local:
        raise ValueError("Remote changed; re-check isolated state without rewriting")
    data=(json.dumps(card,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+"\n").encode("utf-8")
    forecast_sha=_git_publish(root,forecast_path,data.decode("utf-8"),
                              "Research fusion forecast frozen "+card["race_id"])
    confirmed_at=_remote_exact(root,forecast_sha,forecast_path,data,
                               clock=clock,cutoff=gate["cutoff"])
    proof={
        "version":VERSION,"research_only":True,"race_id":card["race_id"],
        "status":"remote_forecast_observed_before_cutoff",
        "prospective_eligible_pending_independent_grading":True,
        "forecast_digest":card["digest"],
        "forecast_file_sha256":sha256(data).hexdigest(),
        "forecast_path":forecast_path,"forecast_commit_sha":forecast_sha,
        "original_input_digest":card["input_digest"],
        "official_source_sha256":card["official_source_sha256"],
        "remote_branch":REMOTE_BRANCH,
        "generation_time":card["generated_at"],
        "remote_forecast_checked_at":confirmed_at.isoformat(),
        "cutoff_at":gate["cutoff"].isoformat(),
        "deadline_at":card["deadline_at"],
        "main_full_delivery_parity":False,
        "venue_effect_validated":bool(card["venue_adjustment_validated"]),
        "server_independent_timestamp_attestation":False,
        "runner_clock_and_actions_logs_required":True,
        "count_as_prospective":False,
        "no_results_read":True,
    }
    proof["digest"]=scenario.digest(proof)
    proof_json=json.dumps(proof,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+"\n"
    receipt_sha=_git_publish(root,receipt_path,proof_json,
                            "Research fusion remote receipt "+card["race_id"])
    final_checked_at=_remote_exact(root,receipt_sha,receipt_path,proof_json.encode("utf-8"),
                                   clock=clock,cutoff=gate["cutoff"])
    return {
        "race_id":card["race_id"],"forecast_commit_sha":forecast_sha,
        "receipt_commit_sha":receipt_sha,"remote_receipt_observed_at":final_checked_at.isoformat(),
        "forecast_digest":card["digest"],"receipt_digest":proof["digest"],
        "remote_receipt_confirmed_before_cutoff":True,
        "count_as_prospective":False,
        "requires_independent_grade":True,
        "note":"Git content observed remotely by runner clock; no independent GitHub server-time attestation.",
    }


def main():
    parser=argparse.ArgumentParser(description="Publish only a genuine predeadline LOCAL frozen research card to independent state")
    parser.add_argument("--card",type=Path,required=True)
    parser.add_argument("--state",type=Path,required=True,
                        help="Clean worktree checked out to research-venue-fusion-forward-state")
    options=parser.parse_args()
    record=json.loads(options.card.read_text(encoding="utf-8"))
    result=publish(record,options.state)
    print("RECEIPT_CHECK="+json.dumps(result,ensure_ascii=False))


if __name__=="__main__":
    main()
