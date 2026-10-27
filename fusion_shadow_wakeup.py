"""Continue only the isolated fusion workflow; never address delivery workflows."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import time
import urllib.request
from zoneinfo import ZoneInfo

API = "https://api.github.com/repos/maedayuuki0706-creator/-AI"
WORKFLOW = "all-ai-fusion-shadow.yml"
CODE_BRANCH = "work/x-fusion-recovery-20261013"


def request(path, payload=None):
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Research continuation needs the research job token")
    req = urllib.request.Request(API+path, method="GET" if payload is None else "POST",
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json", "User-Agent": "boat-ai-fusion-research-only"})
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response) if response.status != 204 else {}


def wake(*, api=request, now=None, current_run_id="", branch=CODE_BRANCH):
    if branch != CODE_BRANCH:
        raise ValueError("Only the dedicated research code branch may be continued")
    now = now or datetime.now(ZoneInfo("Asia/Tokyo"))
    race_hours = 8 <= now.astimezone(ZoneInfo("Asia/Tokyo")).hour <= 23
    workflow = api("/actions/workflows/"+WORKFLOW)
    if workflow.get("state") != "active":
        return {"status": "disabled_by_owner", "workflow": WORKFLOW}
    runs = api(f"/actions/workflows/{workflow['id']}/runs?branch={branch}&per_page=8")["workflow_runs"]
    if any(str(row["id"]) != str(current_run_id) and row["status"] != "completed" for row in runs):
        return {"status": "already_active", "workflow": WORKFLOW}
    # One attempt only: an ambiguous dispatch response is never retried.
    api(f"/actions/workflows/{workflow['id']}/dispatches", {"ref": branch})
    # Keep the relay alive overnight because cron only runs the default main
    # workflow. The collector itself still forbids out-of-hours forecasts.
    return {"status":"requested", "workflow":WORKFLOW, "branch":branch,
            "phase":"race_hours" if race_hours else "overnight_relay_no_forecast"}


def main():
    if os.getenv("GITHUB_REF") != "refs/heads/"+CODE_BRANCH:
        print(json.dumps({"status": "not_the_research_code_branch"}))
        return 0
    started = os.getenv("FUSION_RUN_STARTED_AT")
    if started:
        elapsed = (datetime.now(timezone.utc)-datetime.fromisoformat(started)).total_seconds()
        remaining = max(0, 240-elapsed)
        while remaining:
            pause = min(30, remaining)
            time.sleep(pause)
            remaining -= pause
    try:
        print("Research continuation "+json.dumps(wake(current_run_id=os.getenv("GITHUB_RUN_ID", ""))))
        return 0
    except Exception as exc:
        print(f"::warning::Research continuation unavailable: {type(exc).__name__}; no dispatch retry")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
