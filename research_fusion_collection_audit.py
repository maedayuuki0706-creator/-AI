"""Offline collection health audit. Does not fetch data or operate workflows."""
import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path

from research_fusion_roi_replay import read_json, when


def audit(root, now):
    if now.tzinfo is None:
        raise ValueError("Timezone required")
    path = root / "heartbeat.json"
    if not path.is_file():
        return {"research_only": True, "health": "UNKNOWN", "reasons": ["missing_heartbeat"]}
    hb = read_json(path)
    finished = when(hb["finished_at"])
    age = (now - finished).total_seconds()
    reasons = []
    if age < 0:
        raise ValueError("Heartbeat from future")
    captures = Counter(x["status"] for x in hb.get("captures", []))
    failures = sum(v for k, v in captures.items() if k not in ("frozen", "already_frozen"))
    if failures: reasons.append("capture_failures_or_deferrals")
    if hb.get("status") == "collector_error": reasons.append("collector_error")
    if hb.get("results", {}).get("errors"): reasons.append("result_errors")
    # Last heartbeat can be stale outside collection hours too: this is freshness,
    # not proof that the scheduler or production delivery has stopped.
    if age > 1200: reasons.append("heartbeat_older_than_20_minutes")
    days = Counter(p.parent.name for p in (root / "predictions").glob("*/*.json"))
    return {"research_only": True, "health": "DEGRADED" if reasons else "NO_RECORDED_ERROR",
            "heartbeat_at": hb["finished_at"], "age_seconds": round(age),
            "reported_runner_status": hb.get("status"), "capture_statuses": dict(captures),
            "predictions_by_day": dict(sorted(days.items())),
            "missing_races_at_heartbeat": len(hb.get("missing_races", [])), "reasons": reasons,
            "note": "Research collection only; no inference about Discord/X health. A green Actions run does not prove capture success."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--now", help="ISO timestamp with timezone; defaults to current time")
    args = parser.parse_args()
    now = when(args.now) if args.now else datetime.now().astimezone()
    print(json.dumps(audit(args.state_root, now), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
