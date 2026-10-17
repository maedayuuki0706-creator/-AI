"""Adapters for existing research originals; no prediction policy or delivery code.

The specialist archive remains the source of truth. Yuuki uses the same v2
engine and write-once primitive, sharing official observations with that archive.
An absent frozen baseline is NOT replaced by a newly invented ten-ticket card.
"""
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
import subprocess
import threading

from research.scenario_v2 import engine as scenario
from research.scenario_v2.adapters import from_fusion
from research.scenario_v2.collector import save_immutable
from .engine import digest, VENUES

SCHEMA = "boat-research-log/phase1-v1"
PREFIX = "data/venue_specialists_v1"
YUUKI = "new_yuuki_v2"


def read(path):
    path = Path(path)
    if not path.is_file():
        return None
    # A corrupt file must not become an ordinary missing file or a successful 0.
    return json.loads(path.read_text(encoding="utf-8"))


def descriptor(forecast, ai=None):
    """One contract over the two pre-existing forecast formats, without editing either."""
    is_yuuki = "meta" in forecast
    meta = forecast["meta"] if is_yuuki else forecast
    key = meta["race_id"]
    day, code, rno = key.split("_")
    card = forecast.get("virtual_card")
    picks = list(card.get("picks") or []) if isinstance(card, dict) else [x["combination"] for x in card or []]
    lanes = forecast["lanes"] if is_yuuki else forecast["common_v2"]["lanes"]
    return {
        "schema": SCHEMA, "ai_id": ai or (YUUKI if is_yuuki else "venue_" + code),
        "model": "新ゆうきv2" if is_yuuki else forecast["model"],
        "race_id": key, "day": day, "jcd": code, "rno": int(rno),
        "venue": VENUES.get(code, {}).get("venue", code),
        "deadline_at": meta["deadline_at"],
        "generated_at": forecast["generated_at"] if is_yuuki else forecast["created_at"],
        "captured_at": meta["captured_at"], "forecast_digest": forecast["digest"],
        "input_digest": forecast["input_digest"] if is_yuuki else forecast["snapshot_digest"],
        "version": forecast["version"],
        "code_sha": forecast.get("source", forecast.get("input_sources", {})).get("research_code_sha"),
        "selection_policy": card.get("policy") if isinstance(card, dict) else forecast.get("selection_policy"),
        "mode": forecast.get("mode") if is_yuuki else forecast.get("status"),
        "six_boat_scenarios": len(lanes) == 6 and {x["lane"] for x in lanes} == set(range(1, 7))
            and all(x.get("win_paths") and x.get("loss_paths") and x.get("hypotheses") for x in lanes),
        "picks": picks, "complete_card": len(picks) == 10 and len(set(picks)) == 10
            and set(picks) <= scenario.COMBINATIONS,
        "missing_fields": [{"lane": x["lane"], "fields": x.get("missing_fields", [])} for x in lanes],
        "tactical_hypotheses_are_observations": False,
    }


def validate_receipt(forecast, receipt, snapshot=None):
    scenario.verify(forecast)
    item = descriptor(forecast)
    if not receipt or receipt.get("race_id") != item["race_id"] or receipt.get("digest") != forecast["digest"]:
        raise ValueError("Receipt identity/digest mismatch")
    captured, generated, deadline = map(scenario.aware, (item["captured_at"], item["generated_at"], item["deadline_at"]))
    checked = scenario.aware(receipt["checked_at"])
    if not captured <= generated <= checked < deadline or receipt.get("status") != "confirmed_before_deadline":
        raise ValueError("Not a verified pre-deadline original")
    if item["mode"] != "prospective_uncheckpointed" or not item["six_boat_scenarios"]:
        raise ValueError("Replay or incomplete scenarios excluded")
    if len(receipt.get("commit_sha", "")) != 40:
        raise ValueError("Missing remote commit identity")
    if snapshot is not None and digest(snapshot) != item["input_digest"]:
        raise ValueError("Input does not match immutable forecast")
    return item


def save_event(root, forecast, *, clock, kind="specialist"):
    """Separate factual disk-save time from the forecast's generation time."""
    item = descriptor(forecast)
    path = Path(root) / "save_events" / item["day"] / (item["race_id"] + ".json")
    if path.exists():
        return read(path)
    event = {"schema": SCHEMA, "race_id": item["race_id"], "ai_id": item["ai_id"],
             "forecast_digest": forecast["digest"], "local_saved_at": clock().isoformat(),
             "generated_at": item["generated_at"], "kind": kind}
    save_immutable(path, event)
    return event


class FrozenBaseline:
    """Lazy, read-only fetch of the existing fusion archive, at most once per tick.

    No checkout, prediction execution, dispatch, or push into the baseline branch.
    Exact originals are read at a fetched remote SHA before the live deadline.
    """
    branch = "research-fusion-shadow-state"

    def __init__(self, git_root, clock):
        self.git_root, self.clock = git_root, clock
        self.loaded, self.remote_sha, self.error = False, None, None
        self.lock = threading.Lock()

    def _git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.git_root), *args],
                                       text=True, stderr=subprocess.PIPE, timeout=20)

    def __call__(self, key):
        with self.lock:
            if not self.loaded:
                self.loaded = True
                try:
                    self._git("fetch", "--quiet", "--depth=1", "origin", "refs/heads/" + self.branch)
                    self.remote_sha = self._git("rev-parse", "FETCH_HEAD").strip()
                except (subprocess.SubprocessError, OSError) as exc:
                    self.error = type(exc).__name__
        if self.error:
            raise ValueError("baseline_remote_unavailable:" + self.error)
        prefix = "data/fusion_shadow/"
        try:
            record = json.loads(self._git("show", f"{self.remote_sha}:{prefix}predictions/{key[:8]}/{key}.json"))
            cp = json.loads(self._git("show", f"{self.remote_sha}:{prefix}checkpoints/{key[:8]}/{key}.json"))
        except subprocess.CalledProcessError as exc:
            raise ValueError("baseline_original_or_checkpoint_missing") from exc
        payload = from_fusion(record, cp)
        if self.clock() >= scenario.aware(record["deadline_at"]) - timedelta(minutes=3):
            raise ValueError("baseline_received_after_capture_cutoff")
        return payload, {"branch": self.branch, "remote_sha": self.remote_sha,
                         "baseline_digest": record["digest"],
                         "remote_observed_at": self.clock().isoformat()}


def capture_yuuki(snapshot, root, *, clock, baseline=None):
    """Save v2 now, never retroactively. Preserve partial scenarios without claiming a card.

    Only the existing v2 retain-main6-flow4 selection policy is used. A missing
    baseline leaves a partial scenario and a reason, not a made-up comparison bet.
    """
    root = Path(root) / "yuuki"
    m = snapshot["meta"]
    key = f"{m['day']}_{int(m['jcd']):02}_{int(m['rno']):02}"
    deadline = datetime.strptime(m["day"] + " " + m["deadline"], "%Y%m%d %H:%M").replace(tzinfo=scenario.JST)
    if clock().date() != deadline.date() or deadline - clock() < timedelta(minutes=3):
        return {"race_id": key, "status": "capture_cutoff_closed_no_backfill"}
    target = root / "forecasts" / key[:8] / (key + ".json")
    if target.exists():
        scenario.verify(read(target))
        return {"race_id": key, "status": "already_frozen"}
    # Recover an input already published before an interruption, without
    # replacing its bytes or re-fetching a different baseline.
    pending_input = read(root / "inputs" / key[:8] / (key + ".json"))
    payload = pending_input if pending_input is not None else deepcopy(snapshot)
    reason = "baseline_not_connected"
    if baseline and pending_input is None:
        try:
            supplied, evidence = baseline(key)
            if supplied["meta"]["day"] != m["day"] or str(supplied["meta"]["jcd"]).zfill(2) != str(m["jcd"]).zfill(2) or int(supplied["meta"]["rno"]) != int(m["rno"]):
                raise ValueError("Baseline race mismatch")
            if supplied["meta"]["deadline"] != m["deadline"]:
                raise ValueError("Baseline deadline mismatch")
            identity = lambda rows: {(int(b["lane"]), str(b["racer_id"]), int(b["course"])) for b in rows}
            if identity(supplied["boats"]) != identity(snapshot["boats"]):
                raise ValueError("Baseline entrant/entry mismatch")
            payload["baseline_picks"] = supplied["baseline_picks"]
            payload["baseline_ranking"] = supplied["baseline_ranking"]
            payload.setdefault("source", {})["frozen_baseline"] = evidence
            payload["meta"]["source_observed_at"] = m["captured_at"]
            payload["meta"]["captured_at"] = clock().isoformat()
        except (ValueError, KeyError, TypeError) as exc:
            reason = str(exc)[:200]
    # The source has been assembled at this instant; the original official
    # observation timestamp remains in the evidence and original envelopes.
    forecast = scenario.generate(payload, mode="live", now=clock().isoformat())
    complete = descriptor(forecast)["complete_card"]
    if deadline - clock() < timedelta(minutes=3):
        raise ValueError("Yuuki analysis completed after capture cutoff")
    folder = "forecasts" if complete else "partial_scenarios"
    input_folder = "inputs" if complete else "partial_inputs"
    dest = root / folder / key[:8] / (key + ".json")
    if dest.exists():
        return {"race_id": key, "status": "partial_scenario_already_saved", "reason": reason}
    save_immutable(root / input_folder / key[:8] / (key + ".json"), payload)
    save_immutable(dest, forecast)
    if complete:
        save_event(root, forecast, clock=clock, kind="yuuki_v2_existing_policy")
    else:
        save_immutable(root / "partial_reasons" / key[:8] / (key + ".json"),
                       {"race_id": key, "observed_at": clock().isoformat(), "reason": reason,
                        "status": "six_scenarios_saved_no_comparison_card", "forecast_digest": forecast["digest"]})
    return {"race_id": key, "status": "locally_frozen_uncheckpointed" if complete else "partial_no_baseline_card",
            "reason": None if complete else reason}


def verify_yuuki(root, commit_sha, *, git_show, confirmed_at):
    root = Path(root) / "yuuki"
    confirmed = []
    for path in sorted((root / "forecasts").glob("*/*.json")):
        f = read(path)
        item = descriptor(f)
        scenario.verify(f)
        snapshot = read(root / "inputs" / item["day"] / path.name)
        if not snapshot or digest(snapshot) != item["input_digest"]:
            raise ValueError("Yuuki original input missing or different")
        remote_path = PREFIX + "/yuuki/forecasts/" + item["day"] + "/" + path.name
        input_path = PREFIX + "/yuuki/inputs/" + item["day"] + "/" + path.name
        if json.loads(git_show(commit_sha, remote_path)) != f or json.loads(git_show(commit_sha, input_path)) != snapshot:
            raise ValueError("Yuuki remote Git original mismatch")
        receipt_path = root / "receipts" / item["day"] / path.name
        previous = read(receipt_path)
        if previous:
            if previous.get("digest") != f["digest"] or previous.get("race_id") != item["race_id"]:
                raise ValueError("Yuuki receipt conflict")
            confirmed.append(previous)
            continue
        before = confirmed_at < scenario.aware(item["deadline_at"])
        rec = {"schema": SCHEMA, "race_id": item["race_id"], "digest": f["digest"],
               "snapshot_digest": digest(snapshot), "commit_sha": commit_sha,
               "forecast_path": remote_path, "input_path": input_path,
               "checked_at": confirmed_at.isoformat(), "confirmation_method": "pushed_remote_ref_and_exact_git_objects",
               "status": "confirmed_before_deadline" if before else "late_remote_save_excluded"}
        save_immutable(receipt_path, rec)
        confirmed.append(rec)
    return confirmed
