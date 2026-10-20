"""Research-only prospective frozen-official fusion generator.

One-shot CLI; NO scheduler, network, Google, Discord, X, betting or production
state. The runner will not generate a new "live" card from old input, and
never accesses result pages. Remote Git receipt is a SEPARATE unimplemented
step; local creation is not evidence of remote receipt.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from prediction_engine import analyze_race
from research.scenario_v2 import engine as scenario
from research.venue_specialists_v1 import engine as venue
from . import engine as hybrid
from .official_program import from_frozen_official

VERSION = "venue-fusion-prospective-local-v1"
MODELS = ("official_main_core", "official_main_core_plus_yuuki",
          "official_main_core_plus_yuuki_plus_venue")


def build_live(snapshot: dict, *, now: str | None = None) -> dict:
    """Only accepts actual on-time original; outcome keys forbidden everywhere."""
    scenario.reject_outcomes(snapshot)
    at = scenario.aware(now or datetime.now(scenario.JST).isoformat())
    # Must reject after deadline BEFORE the expensive work or output writes.
    scenario.validate(snapshot, "live", at.isoformat())
    source = from_frozen_official(snapshot)
    if source["meta"]["preprocessing_level"] != "main_official_core_without_profile_form_odds":
        raise ValueError("Unexpected main-core input class")
    core = analyze_race(source["payload"])
    if core["model_version"] != hybrid.EXPECTED_MAIN_VERSION:
        raise ValueError("Production main-core version changed")
    ranked = hybrid._ordered_cards(core["trifecta"])
    new_yuuki = hybrid._build_with_ranking(snapshot, ranked, mode="live", now=at.isoformat())
    specialist = venue.analyze(snapshot, mode="live", now=at.isoformat())
    adjusted, active = hybrid._venue_adjust(ranked, specialist["lane_audits"])
    new_venue = (hybrid._build_with_ranking(snapshot, adjusted, mode="live", now=at.isoformat())
                 if active else new_yuuki)
    picks = {
        "official_main_core": [r["combination"] for r in ranked[:10]],
        "official_main_core_plus_yuuki": hybrid._card(new_yuuki),
        "official_main_core_plus_yuuki_plus_venue": hybrid._card(new_venue),
    }
    for name,card in picks.items():
        if len(card) != 10 or len(set(card)) != 10 or not set(card).issubset(scenario.COMBINATIONS):
            raise ValueError("Bad ten-combination research card: " + name)
    meta = snapshot["meta"]
    rid = f'{meta["day"]}_{str(meta["jcd"]).zfill(2)}_{int(meta["rno"]):02d}'
    payload = {
        "version": VERSION, "research_only": True,
        "race_id": rid, "day": meta["day"], "venue_code": str(meta["jcd"]).zfill(2),
        "deadline_at": scenario.aware(
            f'{meta["day"][:4]}-{meta["day"][4:6]}-{meta["day"][6:8]}T{meta["deadline"]}:00+09:00'
        ).isoformat(),
        "generated_at": at.isoformat(),
        "input_captured_at": meta["captured_at"],
        "input_digest": scenario.digest(snapshot),
        "official_source_sha256": source["meta"]["source_sha256"],
        "official_racelist": source["meta"]["official_pages"]["racelist"],
        "official_beforeinfo": source["meta"]["official_pages"]["beforeinfo"],
        "main_model_version": core["model_version"],
        "main_full_delivery_parity": False,
        "missing_full_main_features": source["limitations"],
        "scenario_digest": new_yuuki["digest"],
        "venue_digest": specialist["digest"],
        "venue_adjustment_validated": bool(active),
        "model_cards": picks,
        "per_ticket_stake_yen": 100, "ticket_count": 10,
        "status": "local_frozen_unconfirmed",
        "git_remote_receipt_confirmed": False,
        "count_as_prospective": False,
        "result_accessed": False,
        "notes": [
            "Generated before deadline from original official HTML and current clock",
            "Not full production main (historical racer profiles/form/live odds absent)",
            "Must be pushed to an independent research state and remotely acknowledged before deadline",
            "Only after confirmed receipt may independent result grader mark as prospective",
            "No predictive benefit claimed for unvalidated venue adjustment",
        ],
    }
    payload["digest"] = scenario.digest(payload)
    return payload


def save_local_only(record: dict, destination: Path) -> Path:
    """No overwrite; never silently replace an earlier or conflicting card."""
    if record.get("status") != "local_frozen_unconfirmed":
        raise ValueError("Local prospective card must be unconfirmed")
    if record.get("digest") != scenario.digest({k:v for k,v in record.items() if k!="digest"}):
        raise ValueError("Card digest changed")
    if destination.suffix != ".json":
        raise ValueError("Only JSON evidence files allowed")
    destination.parent.mkdir(parents=True,exist_ok=True)
    # O_EXCL is atomic; repeated invocation cannot replace a frozen original.
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            json.dump(record,f,ensure_ascii=False,indent=2,sort_keys=True,allow_nan=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return destination


def main():
    p=argparse.ArgumentParser(description="LOCAL prospective 3-card study only, no dispatch")
    p.add_argument("--snapshot",type=Path,required=True)
    p.add_argument("--out-dir",type=Path,required=True)
    a=p.parse_args()
    snap=json.loads(a.snapshot.read_text(encoding="utf-8"))
    result=build_live(snap)
    out=a.out_dir/(result["race_id"]+".json")
    save_local_only(result,out)
    print(json.dumps({"race_id":result["race_id"],"local_path":str(out),
                      "status":result["status"],"remote_receipt_confirmed":False,
                      "count_as_prospective":False},ensure_ascii=False))


if __name__=="__main__":
    main()
