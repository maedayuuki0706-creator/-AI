"""Venue-conditional, 120-combination candidate selector: V3 *shadow research only*.

Trained distributions come solely from the official K archive <= 2026-06-30
(four_venue_phase2 manifests). Neither a finishing result nor a final-race ST,
tactic/method, or payout is allowed in candidate construction.

V3 fixes the V1 6-head interleave which gave all 6 heads equal preference,
and compares two existing historical selectors (A/B) with a bounded B variant.
No calibration/causal claim; no production routes, cron, network or state writes.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from itertools import permutations
import json

from research.scenario_v2 import engine as scenario
from research.four_venue_phase2 import model as historical

VERSION = "venue-conditional-selection-v3-research-20261019"
VARIANTS = ("A", "B", "V3")
HEAD_CAP = 5
PAIR_CAP = 2
COURSE_COMBOS = tuple(permutations(range(1, 7), 3))
assert len(COURSE_COMBOS) == 120


def course_to_lane(boats):
    """Map observed *pre-race exhibition course* to lane; never use outcome course."""
    if len(boats) != 6:
        raise ValueError("Exactly six pre-race entries required")
    bycourse = {}
    lanes = set()
    for boat in boats:
        course, lane = boat.get("course"), boat.get("lane")
        if (not isinstance(course, int) or not isinstance(lane, int)
                or course not in range(1, 7) or lane not in range(1, 7)
                or course in bycourse or lane in lanes):
            raise ValueError("Ambiguous six-course / six-lane entry")
        bycourse[course] = lane
        lanes.add(lane)
    if len(bycourse) != 6:
        raise ValueError("Missing pre-race course")
    return bycourse


def rank_weights(scores, course_lanes):
    """Sort 120 possible three-boat finishes by *historical descriptive* weight."""
    if len(scores) != 120 or set(scores) != set(COURSE_COMBOS):
        raise ValueError("Complete 120-way distribution required")
    if set(course_lanes) != set(range(1, 7)) or set(course_lanes.values()) != set(range(1, 7)):
        raise ValueError("Exactly six distinct course-to-lane mappings required")
    ranking = []
    combos = set()
    for courses in COURSE_COMBOS:
        weight = scores[courses]
        if isinstance(weight, bool) or not isinstance(weight, (float, int)) or not (0 <= weight < float("inf")):
            raise ValueError("Invalid historical weight")
        lanes = tuple(course_lanes[c] for c in courses)
        key = "-".join(str(c) for c in lanes)
        if key in combos:
            raise ValueError("Duplicate combination")
        combos.add(key)
        ranking.append({"combination": key, "courses": list(courses), "weight": round(float(weight), 12)})
    ranking.sort(key=lambda row: (-row["weight"], row["combination"]))
    if len(combos) != 120:
        raise ValueError("Not full permutations")
    return ranking


def choose(ranked, variant="V3"):
    """Exactly ten unique tickets; fixed policies declared before score evaluation.

    A/B: pure descending historical rank, as in Phase2 original selectors.
    V3: identical B weights, but max five tickets per head and max two for
    a specific ordered 1st/2nd pair. This is coverage policy, not learning
    a tuned coefficient or probability calibration.
    """
    if variant not in VARIANTS:
        raise ValueError("Unknown selector variant")
    if len(ranked) != 120 or len({v["combination"] for v in ranked}) != 120:
        raise ValueError("Require complete unique 120 candidate log")
    picked, heads, pairs = [], Counter(), Counter()
    for row in ranked:
        combo = row["combination"]
        if combo not in scenario.COMBINATIONS:
            raise ValueError("Invalid three-boat combination")
        head, second, _ = combo.split("-")
        if variant == "V3" and (heads[head] >= HEAD_CAP or pairs[head, second] >= PAIR_CAP):
            continue
        picked.append(row)
        heads[head] += 1
        pairs[head, second] += 1
        if len(picked) == 10:
            break
    if len(picked) != 10:
        raise ValueError("Unable to choose ten tickets")
    return picked


def _scoring(manifest, variant):
    historical.check_model(manifest)
    return historical.course_scores(manifest, "B" if variant in ("B", "V3") else "A")


def snapshot_candidates(snapshot, manifest, variant, *, mode="replay", now=None, strict_asof=True):
    """Generate counterfactual pre-race scenario hypotheses with a 120-way card.

    Any use of post-race fields or model trained/available after captured_at
    fails under strict_asof. Replay is marked post-hoc regardless of validation.
    """
    if variant not in VARIANTS:
        raise ValueError("Unknown variant")
    historical.check_model(manifest)
    if str(snapshot["meta"]["jcd"]).zfill(2) != manifest["venue_code"]:
        raise ValueError("Venue and model mismatch")
    day = str(snapshot["meta"]["day"])
    if not (len(day) == 8 and day.isdigit() and day > manifest["training_end"].replace("-", "")):
        raise ValueError("Snapshot overlaps historical training")
    captured = scenario.aware(snapshot["meta"]["captured_at"])
    if strict_asof:
        for when in [manifest["fitted_at"], manifest.get("data_available_at")]:
            if when and scenario.aware(when) > captured:
                raise ValueError("Model was not available when the frozen input was captured")
    if now is None:
        now = datetime.now(scenario.JST).isoformat()
    # Reject both known and nested labels, even if scenario_v2 does not recognize them.
    scenario.reject_outcomes(snapshot)
    def prohibit(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in {"method", "trifecta", "first", "second", "third", "winning_combinations",
                         "official_trifectas", "payout_per_100", "refund_lanes", "settled"}:
                    raise ValueError("Post-race field in pre-race source: " + k)
                prohibit(v)
        elif isinstance(obj, list):
            for v in obj:
                prohibit(v)
    prohibit(snapshot)
    base = scenario.generate(snapshot, mode=mode, now=now)
    # scenario_v2 lane records expose "predicted_course"; the original
    # frozen input (not the outcome) owns the authoritative course field.
    bycourse = course_to_lane(snapshot["boats"])
    weights = _scoring(manifest, variant)
    ranked = rank_weights(weights, bycourse)
    chosen = choose(ranked, variant)
    coverage = {}
    for lane in base["lanes"]:
        for hypo in lane["hypotheses"]:
            for formation in hypo["formations"]:
                coverage.setdefault(formation["combination"], []).append(hypo["id"])
    enriched = []
    for n, item in enumerate(ranked, 1):
        enriched.append({**item, "rank": n,
                         "v2_scenario_supported": item["combination"] in coverage,
                         "scenario_hypothesis_ids": coverage.get(item["combination"], [])})
    included = {r["combination"] for r in chosen}
    picks = [next(r for r in enriched if r["combination"] == x["combination"]) for x in chosen]
    record = {
        "version": VERSION, "variant": variant,
        "research_only": True, "status": "retrospective_replay" if mode == "replay" else "prospective_uncheckpointed",
        "meta": base["meta"], "generated_at": datetime.now(scenario.JST).isoformat(),
        "input_digest": scenario.digest(snapshot), "model_digest": manifest["digest"],
        "model_fitted_at": manifest["fitted_at"], "model_available_at": manifest.get("data_available_at"),
        "training_end": manifest["training_end"], "training_n": manifest["training_n"],
        "course_mapping_source": "frozen official pre-race exhibition",
        "raw_scenario_digest": base["digest"], "lanes": base["lanes"],
        "all_120_candidates": enriched, "virtual_card": picks,
        "not_selected": [{**r, "reason": "outside fixed ten-ticket selector / V3 head-pair caps"}
                         for r in enriched if r["combination"] not in included],
        "unit_yen": 100, "stake_yen": 1000,
        "selection_policy": {"A": "trained_joint_A_top10",
                             "B": "trained_head_method_followers_B_top10",
                             "V3": "trained_head_method_followers_B_head5_pair2"}[variant],
        "head_cap": HEAD_CAP if variant == "V3" else None,
        "pair_cap": PAIR_CAP if variant == "V3" else None,
        "probabilities_calibrated": False, "scenario_mechanism_verified": False,
        "limitations": [
            "This is a research counterfactual, not a delivered or remotely received forecast",
            "Past observed frequency is an uncalibrated ranking signal, not a race win probability",
            "A missing V2 scenario hypothesis does not make a historically common 3-combination impossible",
            "No odds, EV, future outcome, finish, actual ST or actual race tactics were used",
            "Live use requires separate prospective receipt/latency and resource tests",
        ],
    }
    record["digest"] = scenario.digest(record)
    return record


def historical_card(manifest, variant, *, bycourse=None):
    """Historical analysis assumes lane=course, never uses the recorded actual course."""
    return [r["combination"] for r in choose(rank_weights(
        _scoring(manifest, variant), bycourse or dict(zip(range(1, 7), range(1, 7)))),
        variant)]


def miss_type(winner, card):
    if winner in card:
        return "hit"
    parts = winner.split("-")
    if not any(s.split("-")[0] == parts[0] for s in card):
        return "head_not_selected"
    if not any(s.split("-")[:2] == parts[:2] for s in card):
        return "second_not_selected_given_head"
    return "third_not_selected_given_head_and_second"
