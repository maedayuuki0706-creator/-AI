"""One manual pilot tick; publish originals, remote receipts, then results.

Reuses both the existing fusion collector and the Phase 1 retrying persister.
Does not dispatch workflows, post messages or modify any production state.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import time

import fusion_shadow_runner as runner
from research.venue_specialists_v1.worker import persist, git

BRANCH = "research-fusion-recovery-state"
PREFIX = "data/fusion_shadow"
REQUIRED = ("fusion_shadow.py", "fusion_shadow_runner.py", "direct_discord_notify.py",
            "detailed_discord_notify.py", "hiyori_source.py", "hiyori_model.py",
            "prediction_engine.py", "prediction_engine_v2.py", "four_way_prototype.py",
            "pt2_sheet_db.py", "pt2_strategy_cards.py", "x_delivery_v2/__init__.py",
            "research/fusion_log_recovery/pilot.py", "research/venue_specialists_v1/worker.py")


def preflight(state, day, *, code_root=None):
    """Read-only readiness, including at night; never a forecast/save success.

    Only Git's ls-remote is allowed to contact a remote. No source requests,
    prediction generation, staging, push, checkpoints or result collection.
    """
    if datetime.strptime(day, "%Y%m%d").strftime("%Y%m%d") != day:
        raise ValueError("Expected YYYYMMDD")
    code_root = Path(code_root) if code_root is not None else Path(__file__).resolve().parents[2]
    missing = [name for name in REQUIRED if not (code_root / name).is_file()]
    if missing:
        raise ValueError("Missing required research checkout files: " + ",".join(missing))
    database = {}
    for name in ("players", "motors", "venues", "meta"):
        path = code_root / "data/sheet_db" / (name + ".json")
        database[name] = runner.load(path)
        if not isinstance(database[name], dict) or not database[name]:
            raise ValueError("Empty/invalid pinned database: " + name)
    snapshot_at = runner.core.aware(database["meta"]["snapshot_at"])
    if snapshot_at > runner.now_jst():
        raise ValueError("Future database snapshot cannot pass readiness")
    pinned = [*REQUIRED, *("data/sheet_db/" + name + ".json" for name in database)]
    git(code_root, "ls-files", "--error-unmatch", "--", *pinned)
    if git(code_root, "status", "--porcelain", "--untracked-files=all", "--", *pinned).strip():
        raise ValueError("Research code/database differ from the pinned commit")
    head = git(state, "rev-parse", "HEAD").strip()
    remote = git(state, "ls-remote", "--exit-code", "origin", "refs/heads/" + BRANCH).strip()
    if remote.split() != [head, "refs/heads/" + BRANCH]:
        raise ValueError("State checkout does not match the current recovery remote; refresh before testing")
    pending = git(state, "status", "--porcelain", "--untracked-files=all", "--", PREFIX).strip()
    if pending:
        raise ValueError("Pending research state exists; preserve it before preflight")
    health = {"status": "preflight_ready_live_save_not_verified", "mode": "preflight",
              "observed_at": runner.now_jst().isoformat(), "day": day,
              "branch": BRANCH, "remote_state_sha": head,
              "code_sha": git(code_root, "rev-parse", "HEAD").strip(),
              "database_snapshot_at": snapshot_at.isoformat(),
              "database_rows": {k: len(database[k]) for k in ("players", "motors", "venues")},
              "source_sha256": {name: runner.core.sha256((code_root / name).read_bytes()).hexdigest()
                                for name in REQUIRED},
              "official_source_requests": 0, "new_predictions": 0, "new_receipts": 0,
              "state_writes": 0, "pushes": 0, "seven_day_gate": "not_measured"}
    print(json.dumps(health, ensure_ascii=False), flush=True)
    return health


def tick(state, day):
    now = runner.now_jst()
    if day != now.strftime("%Y%m%d") or not 8 <= now.hour <= 23:
        raise ValueError("Live pilot requires today's race hours; no backfill or overnight requests")
    root = Path(state) / PREFIX
    code = runner.run(root, budget_seconds=85, only_venues={"23"}, only_rnos={1, 2, 3},
                      max_captures=1, skip_results=True)
    # Even a timeout coverage event must be durable. The persister retries an
    # already committed but unpushed original with no new staged changes.
    sha = persist(state, "research: freeze bounded Karatsu fusion pilot originals and coverage",
                  fusion_pilot_day=day)
    receipts = runner.checkpoint(root, sha)
    persist(state, "research: verify remote fusion pilot originals in separate receipts",
            fusion_pilot_day=day)
    results = runner.collect_results(root, time.monotonic() + 35, max_fetch=2)
    runner.write_summary(root)
    persist(state, "research: append official fusion pilot results after original receipts",
            fusion_pilot_day=day)
    health = {"day": day, "branch": BRANCH, "pre_result_remote_sha": sha,
              "new_receipts": receipts, "results": results, "capture_exit_code": code,
              "pilot_scope": "Karatsu 1-3R only; at most one capture in this manual invocation",
              "seven_day_gate": "not_measured"}
    print(json.dumps(health, ensure_ascii=False), flush=True)
    if code or results["errors"]:
        raise RuntimeError("Research pilot incomplete; see durable coverage and Actions artifact")
    return health


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True)
    parser.add_argument("--day", required=True)
    parser.add_argument("--mode", choices=("preflight", "live"), default="preflight")
    args = parser.parse_args()
    if args.mode == "preflight":
        preflight(args.state, args.day)
    else:
        tick(args.state, args.day)


if __name__ == "__main__":
    main()
