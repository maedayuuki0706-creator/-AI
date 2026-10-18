"""Offline tactical hypotheses. No delivery, network, probability, or wager API."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from itertools import permutations
import json
from math import isfinite
from zoneinfo import ZoneInfo

VERSION = "yuuki-scenario-research-v2"
JST = ZoneInfo("Asia/Tokyo")
COMBINATIONS = frozenset("-".join(map(str, p)) for p in permutations(range(1, 7), 3))
POLICY = {"id": "retain-main6-flow4-v1", "retain": 6, "points": 10,
          "unit_yen": 100, "st_gap_seconds": .03, "foot_rank_max": 2,
          "pairs_per_branch": 3, "probabilities_calibrated": False}
OUTCOME_KEYS = {"result", "results", "race_result", "race_results", "finish", "finishes",
                "actual_st", "actual_course", "payout", "payouts", "payout_per_100",
                "winning_method", "winner", "refund_lanes", "race_details", "settled",
                "settled_at", "official_result", "current_outcome"}


def digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def aware(value):
    dt = datetime.fromisoformat(str(value))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("Timezone-aware timestamp required")
    return dt.astimezone(JST)


def number(value, low=None, high=None):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("Boolean is not a measurement")
    n = float(value)
    if not isfinite(n) or (low is not None and n < low) or (high is not None and n > high):
        raise ValueError("Invalid measurement")
    return n


def integer(value, low, high):
    n = number(value, low, high)
    if n is None or n != int(n):
        raise ValueError("Integer required")
    return int(n)


def reject_outcomes(value, path="input"):
    """Reject nested current outcomes before any projection can hide them."""
    if isinstance(value, dict):
        for key, item in value.items():
            k = str(key).lower()
            if k in OUTCOME_KEYS or k.startswith("actual_") or k.startswith("current_result"):
                raise ValueError(f"Outcome field forbidden: {path}.{key}")
            reject_outcomes(item, f"{path}.{key}")
    elif isinstance(value, list):
        for i, item in enumerate(value):
            reject_outcomes(item, f"{path}[{i}]")


def verify(record):
    if record.get("digest") != digest({k: v for k, v in record.items() if k != "digest"}):
        raise ValueError("Frozen record digest mismatch")


def validate(data, mode, now):
    reject_outcomes(data)
    meta = data["meta"]
    day = str(meta["day"])
    if len(day) != 8 or not day.isdigit():
        raise ValueError("Day must be YYYYMMDD")
    datetime.strptime(day, "%Y%m%d")
    jcd, rno = integer(meta["jcd"], 1, 24), integer(meta["rno"], 1, 12)
    deadline = datetime.strptime(day + " " + meta["deadline"], "%Y%m%d %H:%M").replace(tzinfo=JST)
    captured = aware(meta["captured_at"])
    if captured.strftime("%Y%m%d") != day or (deadline - captured).total_seconds() < 180:
        raise ValueError("Need a race-day source captured >=3 minutes before deadline")
    generated = aware(now)
    if generated < captured:
        raise ValueError("Generation cannot precede source capture")
    if mode == "live":
        if generated.strftime("%Y%m%d") != day or (deadline - generated).total_seconds() < 180:
            raise ValueError("Live forecast must actually be generated >=3 minutes before deadline")
    elif mode != "replay":
        raise ValueError("Explicit live or replay mode required")
    for name in ("db_snapshot_at", "source_observed_at"):
        if meta.get(name) and aware(meta[name]) > captured:
            raise ValueError(f"Future evidence: {name}")
    boats = deepcopy(data["boats"])
    if len(boats) != 6:
        raise ValueError("Exactly six boats required")
    lanes, courses, ids = set(), set(), set()
    for b in boats:
        b["lane"] = integer(b["lane"], 1, 6)
        b["course"] = integer(b["course"], 1, 6)
        racer = str(b.get("racer_id") or "")
        if b["lane"] in lanes or b["course"] in courses or not racer or racer in ids:
            raise ValueError("Unique lanes, courses and racer IDs required")
        lanes.add(b["lane"]); courses.add(b["course"]); ids.add(racer)
        for field, lo, hi in (("avg_st", 0, 1), ("exhibition_st", -1, 1),
                              ("motor_top2_rate", 0, 100), ("course_top2_rate", 0, 100)):
            b[field] = number(b.get(field), lo, hi)
        for field in ("straight_time", "turn_time", "lap_time", "exhibition_time"):
            b[field] = number(b.get(field), .001, 100)
        for observation in b.get("observations", []):
            if aware(observation["observed_at"]) > captured:
                raise ValueError("Future boat evidence")
    base = data.get("baseline_picks")
    ranking = data.get("baseline_ranking")
    if (base is None) != (ranking is None):
        raise ValueError("Baseline card and complete ranking must be supplied together")
    if base is not None:
        if len(base) != 10 or len(set(base)) != 10 or not set(base) <= COMBINATIONS:
            raise ValueError("Need ten unique frozen baseline tickets")
        if len(ranking) != 120 or set(ranking) != COMBINATIONS:
            raise ValueError("Complete unique 120-combination baseline ranking required")
    return sorted(boats, key=lambda b: b["course"]), {
        **deepcopy(meta), "race_id": f"{day}_{jcd:02}_{rno:02}",
        "deadline_at": deadline.isoformat(), "captured_at": captured.isoformat(),
    }, generated


def rank_measure(boats, field, lane):
    values = {b["lane"]: b[field] for b in boats if b.get(field) is not None}
    if lane not in values or len(values) != 6 or max(values.values()) == min(values.values()):
        return None  # an incomplete field is never ranked against a smaller population
    return 1 + sum(v < values[lane] for v in values.values())


def condition(kind, boat, boats, other=None):
    if kind == "st_advantage":
        a, b = boat.get("avg_st"), other.get("avg_st")
        gap = round(b - a, 6) if a is not None and b is not None else None
        return {"kind": kind, "lane": boat["lane"], "other_lane": other["lane"],
                "threshold": POLICY["st_gap_seconds"], "observed_gap": gap,
                "support": None if gap is None else gap >= POLICY["st_gap_seconds"],
                "note": "Historical average contrast; race ST is unknown"}
    field = "straight_time" if kind == "straight_rank" else "turn_time"
    rank = rank_measure(boats, field, boat["lane"])
    return {"kind": kind, "lane": boat["lane"], "rank": rank,
            "threshold": POLICY["foot_rank_max"],
            "support": None if rank is None else rank <= POLICY["foot_rank_max"],
            "note": "Same-race observed timing rank; not motor-rate inference"}


def reactions(head, tactic, origin, boats):
    own = head["course"]
    rows = []
    for b in boats:
        if b["lane"] == head["lane"]:
            continue
        diff = b["course"] - own
        if tactic == "逃げ":
            role, priority = ("内を差して追走", 0) if diff == 1 else ("外を回って追走し競り合う", 1)
        elif tactic == "まくり":
            if diff == 1:
                role, priority = "攻めの直外から内を差す。連動が届けば2着候補", 0
            elif diff < 0:
                role, priority = "攻めに抵抗するか差し残す。絞られれば後退", 2
            else:
                role, priority = "先の攻めに追随。距離ロスと進路競合が条件", 1
        elif tactic == "差し":
            if b["course"] == 1:
                role, priority = "先マイ後に内から残す。差されても追走候補", 0
            elif diff < 0:
                role, priority = "先の差し場を競う。流れると後続の進路が開く", 1
            else:
                role, priority = "差し艇の外で追走。内差しの順番を争う", 2
        elif origin and b["lane"] == origin["lane"]:
            role, priority = "攻めの起点。握って流れた後に立て直して残す", 1
        elif b["course"] == 1:
            role, priority = "外の攻めを受けながら内側を残す", 0
        elif diff == 1:
            role, priority = "まくり差し艇の外から連動。進路競合に注意", 1
        else:
            role, priority = "開いた艇間を争う。前の艇が残れば進路が閉じる", 2
        rows.append({"lane": b["lane"], "course": b["course"], "hypothesis": role,
                     "tactical_priority": priority})
    return rows


def formations(head, tactic, responses, boats):
    by_lane = {b["lane"]: b for b in boats}
    def key(r):
        b = by_lane[r["lane"]]
        turn = rank_measure(boats, "turn_time", b["lane"])
        return (r["tactical_priority"], turn if turn is not None else 7,
                -(b["course_top2_rate"] if b["course_top2_rate"] is not None else -1), b["course"])
    ranked = sorted(responses, key=key)
    # Preserve an alternative second-place path rather than only varying third.
    # This fixed order is an explicit heuristic, not a probability.
    pairs = [(ranked[0], ranked[1]), (ranked[1], ranked[0]), (ranked[0], ranked[2])]
    return [{"combination": f"{head['lane']}-{a['lane']}-{b['lane']}",
             "second_reason": a["hypothesis"], "third_reason": b["hypothesis"],
             "rank_kind": "unvalidated_tactical_order"}
            for a, b in pairs[:POLICY["pairs_per_branch"]]]


def build_branch(head, tactic, origin, boats):
    by_course = {b["course"]: b for b in boats}
    tests = []
    if tactic == "まくり":
        tests = [condition("st_advantage", head, boats, by_course[head["course"] - 1]),
                 condition("straight_rank", head, boats)]
        trigger = "内側より先行する隊形と行き足を作り、抵抗を越えて外から攻め切る"
        loss = "内艇が壁を作る／握った攻めが止まる／外の連動艇に差される"
    elif tactic == "まくり差し":
        tests = [condition("st_advantage", origin, boats, by_course[origin["course"] - 1]),
                 condition("turn_rank", head, boats)]
        trigger = f"{origin['lane']}号艇が内側を攻め、開いた艇間に{head['lane']}号艇が差し込む"
        loss = "起点艇の攻めが不発／差し場が閉じる／起点艇に追いつけない／直外と進路競合"
    elif tactic == "差し":
        tests = [condition("turn_rank", head, boats)]
        trigger = "内艇の先マイ後に差し場が開き、出足・旋回出口の押しが届く"
        loss = "先行艇が小さく回る／先の差し艇が進路を塞ぐ／出口で押せず届かない"
    else:
        tests = [condition("st_advantage", head, boats, by_course[2]),
                 condition("turn_rank", head, boats)]
        trigger = "外の攻撃より先に先マイし、差し場を小さく保って出口加速を維持する"
        loss = "外に先行される／内差しを許す／先行後の道中逆転を受ける"
    responses = reactions(head, tactic, origin, boats)
    supported = sum(t["support"] is True for t in tests)
    return {"id": f"{head['lane']}:{tactic}:{origin['lane'] if origin else head['lane']}",
            "winner_lane": head["lane"], "tactic": tactic,
            "attack_origin_lane": origin["lane"] if origin else head["lane"],
            "attack_origin_kind": "linked_inner_attack" if origin else "self",
            "win_path": trigger, "loss_path": loss,
            "start_to_first_turn": trigger,
            "exit_to_backstretch": "出口で並んだ場合は出足と進路を再確認。ここからの着順固定はしない",
            "conditions": tests,
            "unobserved_conditions": ["本番の進路と抵抗", "実際の起こし位置・加速", "1Mの出口の位置関係"],
            "supported_observations": supported,
            "evidence_status": "observations_support_hypothesis" if supported else "hypothesis_only",
            "reactions": responses, "formations": formations(head, tactic, responses, boats)}


def select_card(data, branches):
    base = data.get("baseline_picks")
    if base is None:
        return None
    ranking = {c: i for i, c in enumerate(data["baseline_ranking"])}
    keep = list(base[:POLICY["retain"]])
    candidates = {}
    for h in branches:
        if h["supported_observations"]:
            for item in h["formations"]:
                candidates.setdefault(item["combination"], []).append(h["id"])
    selected = keep + [c for c in sorted(candidates, key=lambda c: ranking[c]) if c not in keep][:4]
    for c in list(base[6:]) + data["baseline_ranking"]:
        if len(selected) == 10:
            break
        if c not in selected:
            selected.append(c)
    return {"policy": POLICY["id"], "picks": selected, "unit_yen": 100,
            "stake_yen": len(selected) * 100, "retained_main": keep,
            "branch_support": {c: candidates.get(c, []) for c in selected},
            "note": "Virtual research card. Baseline ranks are inherited, uncalibrated and not probabilities here"}


def generate(data, *, mode="live", now=None):
    boats, meta, generated = validate(data, mode, now or datetime.now(JST).isoformat())
    rows, branches = [], []
    for b in boats:
        hs = []
        tactics = ("逃げ",) if b["course"] == 1 else ("差し", "まくり", "まくり差し")
        for tactic in tactics:
            origins = [a for a in boats if 1 < a["course"] < b["course"]] if tactic == "まくり差し" else [None]
            # A 2-course makurisashi requires an unobserved outside/turn interaction; do not invent an initiator.
            for origin in origins:
                hs.append(build_branch(b, tactic, origin, boats))
        branches.extend(hs)
        missing = [k for k in ("avg_st", "straight_time", "turn_time", "lap_time", "motor_top2_rate") if b.get(k) is None]
        rows.append({"lane": b["lane"], "predicted_course": b["course"], "racer_id": b["racer_id"],
                     "name": b.get("name"), "evidence": b, "missing_fields": missing,
                     "win_paths": [h["win_path"] for h in hs], "loss_paths": [h["loss_path"] for h in hs],
                     "hypotheses": hs})
    coverage = sorted({i["combination"] for h in branches for i in h["formations"]})
    record = {"version": VERSION, "status": "research_only", "mode": "retrospective_replay" if mode == "replay" else "prospective_uncheckpointed",
              "meta": meta, "generated_at": generated.isoformat(), "policy": deepcopy(POLICY),
              "input_digest": digest(data), "source": deepcopy(data.get("source", {})),
              "environment": deepcopy(data.get("environment", {})), "lanes": sorted(rows, key=lambda r: r["lane"]),
              "formation_candidates": coverage, "formation_candidate_count": len(coverage),
              "virtual_card": select_card(data, branches), "probabilities_calibrated": False,
              "limitations": ["No probabilities or EV generated; scenario repetition is not empirical frequency",
                              "All-six-head coverage is guaranteed by construction, not predictive accuracy",
                              "Motor top2 rate does not establish present straight/turn/launch performance",
                              "Wind, wave and tide are observations only; no unvalidated venue correction",
                              "Tactical and follower order is an unvalidated heuristic",
                              "No individual psychological state is inferred from F or comments",
                              "Winner method cannot establish losing boats' actual tactics or causal failure"]}
    record["digest"] = digest(record)
    return record


def review(frozen, result):
    verify(frozen)
    if frozen.get("version") != VERSION or result.get("race_id") != frozen["meta"]["race_id"]:
        raise ValueError("Version/race mismatch")
    deadline = aware(frozen["meta"]["deadline_at"])
    if aware(result["observed_at"]) < deadline:
        raise ValueError("Outcome observation must follow deadline")
    status = result.get("status")
    if status in {"pending", "void", "cancelled", "accident", "f", "l", "refund", "special", "incomplete_finish"} or result.get("refund_lanes"):
        return {"race_id": result["race_id"], "status": "excluded", "reason": status if not result.get("refund_lanes") else "refund_or_accident",
                "forecast_digest": frozen["digest"]}
    actual = result.get("trifecta")
    if status != "settled" or actual not in COMBINATIONS:
        raise ValueError("Need explicit settled result and valid trifecta")
    payout = integer(result["payout_per_100"], 1, 10**9)
    head, second, third = map(int, actual.split("-"))
    details = result.get("boats") or []
    if details:
        if len(details) != 6 or {integer(b["lane"], 1, 6) for b in details} != set(range(1, 7)):
            raise ValueError("Incomplete/duplicate actual entrants")
        if {integer(b["actual_course"], 1, 6) for b in details} != set(range(1, 7)):
            raise ValueError("Invalid actual entry")
        if {integer(b["finish"], 1, 6) for b in details} != set(range(1, 7)):
            raise ValueError("Normal failure analysis needs six classified finishers")
        got = sorted(details, key=lambda b: int(b["finish"]))
        if [int(b["lane"]) for b in got[:3]] != [head, second, third]:
            raise ValueError("Result detail/payout disagreement")
    by_lane = {int(b["lane"]): b for b in details}
    expected_ids = {r["lane"]: r["racer_id"] for r in frozen["lanes"]}
    if any(b.get("racer_id") is not None and str(b["racer_id"]) != expected_ids[int(b["lane"])] for b in details):
        raise ValueError("Actual racer identity mismatch")
    method = result.get("winning_method")
    changed = [r["lane"] for r in frozen["lanes"] if r["lane"] in by_lane and
               int(by_lane[r["lane"]]["actual_course"]) != r["predicted_course"]]
    rows = []
    for lane in frozen["lanes"]:
        checks = []
        for h in lane["hypotheses"]:
            for c in h["conditions"]:
                if c["kind"] != "st_advantage":
                    continue
                a, b = by_lane.get(c["lane"]), by_lane.get(c["other_lane"])
                gap = None
                if a and b:
                    x, y = number(a.get("actual_st"), 0, 1), number(b.get("actual_st"), 0, 1)
                    gap = round(y - x, 6) if x is not None and y is not None else None
                checks.append({"hypothesis_id": h["id"], "kind": "st_advantage", "lane": c["lane"],
                               "other_lane": c["other_lane"], "pre_support": c["support"],
                               "actual_gap": gap, "condition_occurred": None if gap is None else gap >= c["threshold"],
                               "same_entry": not bool(changed) if details else None,
                               "causal_failure_confirmed": False})
        winner = lane["lane"] == head
        matched = [h["id"] for h in lane["hypotheses"] if winner and method and h["tactic"] == method]
        rows.append({"lane": lane["lane"], "pre_win_paths": lane["win_paths"], "pre_loss_paths": lane["loss_paths"],
                     "actual_finish": by_lane.get(lane["lane"], {}).get("finish"), "winner": winner,
                     "winner_method_matches": matched if winner and method in {"逃げ", "差し", "まくり", "まくり差し"} else None,
                     "condition_checks": checks, "loss_cause": "未確定。進路・抵抗・出口の映像照合が必要",
                     "interpretation": "条件の再現性と着順を記録。負けた事実だけで戦術失敗を断定しない"})
    card = frozen.get("virtual_card")
    picks = card["picks"] if card else []
    method_known = method in {"逃げ", "差し", "まくり", "まくり差し"}
    consistent = [h["id"] for l in frozen["lanes"] if l["lane"] == head for h in l["hypotheses"]
                  if h["tactic"] == method and actual in {i["combination"] for i in h["formations"]}]
    if actual in picks:
        category = "hit"
    elif not any(int(c.split("-")[0]) == head for c in picks):
        category = "head_not_selected"
    elif not any(c.startswith(f"{head}-{second}-") for c in picks):
        category = "second_not_selected_for_head"
    else:
        category = "third_not_selected_for_pair"
    return {"race_id": result["race_id"], "status": "reviewed", "mode": frozen["mode"],
            "forecast_digest": frozen["digest"], "result_digest": digest(result),
            "actual_trifecta": actual, "winning_method": method, "entry_changed_lanes": changed,
            "method_and_formation_covered": bool(consistent) if method_known else None,
            "method_formation_matches": consistent,
            "entry_verified": bool(details), "formation_covered": actual in frozen["formation_candidates"],
            "candidate_count": frozen["formation_candidate_count"], "selection_error": category if card else "no_card",
            "virtual_performance": {"hit": actual in picks, "stake_yen": len(picks) * 100,
                                    "return_yen": payout if actual in picks else 0} if card else None,
            "lanes": rows, "source_url": result.get("source_url"),
            "causal_tactics_verified": False,
            "note": "Retrospective replay is not a prospective performance record; official winner method is not a full 1M annotation"}
