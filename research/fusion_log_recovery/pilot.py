"""One manual pilot tick; publish originals, remote receipts, then results.

Reuses both the existing fusion collector and the Phase 1 retrying persister.
Does not dispatch workflows, post messages or modify any production state.
"""
import argparse
import json
from pathlib import Path
import time

import fusion_shadow_runner as runner
from research.venue_specialists_v1.worker import persist

BRANCH = "research-fusion-recovery-state"
PREFIX = "data/fusion_shadow"


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
    args = parser.parse_args()
    tick(args.state, args.day)


if __name__ == "__main__":
    main()
