"""Weak-in-venue longshot pattern STUDY. No predictions, betting, or delivery.

Input cases have time-frozen pre_race_features and separately joined official
observed_result from manshu_shadow_learning._case. The 1-course historical
baseline is NOT treated as a rare 'upset' signal by itself.

Uses official 2026/07-09 venue baselines pinned in manshu_venue_context.py.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from manshu_venue_context import VENUE_BASELINES, POLICY_VERSION

STUDY_VERSION = "weak-in-manshu-patterns-v1"
MIN_RECOMMENDED_SAMPLE = 30


def _p(value):
    try:
        return float(value) if value is not None else None
    except (ValueError, TypeError):
        return None


def _rate(x, n):
    return round(100 * x / n, 1) if n else None


def _feature_profile(pre):
    """Use only pre-deadline data. Unknown grades remain unknown."""
    boats = pre.get("six_boat_exhibition") or []
    by_lane = {int(row["lane"]): row for row in boats if row.get("lane") in range(1, 7)}
    ranks = {i: _p(by_lane.get(i, {}).get("ex_rank")) for i in range(1, 7)}
    valid_2_3 = len(by_lane) == 6 and all(
        str(by_lane.get(i, {}).get("class") or "") in ("A1", "A2", "B1", "B2") for i in (2, 3)
    )
    a1 = [
        i for i in (2, 3)
        if str(by_lane.get(i, {}).get("class") or "") == "A1"
    ]
    stronger_2_3 = []
    for i in a1:
        tm1 = _p(by_lane.get(1, {}).get("ex_time"))
        tmi = _p(by_lane.get(i, {}).get("ex_time"))
        st1 = _p(by_lane.get(1, {}).get("ex_st"))
        sti = _p(by_lane.get(i, {}).get("ex_st"))
        if tm1 is None or tmi is None or st1 is None or sti is None:
            continue
        # ST F values are not positive 'fast starts' for this indicator.
        if tm1 - tmi >= 0.08 and st1 >= 0 and sti >= 0 and st1 - sti >= 0.04:
            stronger_2_3.append(i)
    return {
        "grade_status": "confirmed" if valid_2_3 else "unknown",
        "a1_boats_2or3": a1,
        "a1_with_both_exhibition_edges": stronger_2_3,
        "lane1_class": by_lane.get(1, {}).get("class") or None,
        "lane1_ex_rank": ranks.get(1),
        "five_ex_top3": ranks.get(5) is not None and ranks[5] <= 3,
        "six_ex_top3": ranks.get(6) is not None and ranks[6] <= 3,
        "pre_ex_courses": {str(i): _p(by_lane.get(i, {}).get("ex_course")) for i in range(1, 7)},
        "pre_wind_m": _p(pre.get("wind_m")),
        "pre_wave_cm": _p(pre.get("wave_cm")),
        "pre_ex_outer_gap_s": _p(pre.get("outside_ex_time_advantage_s")),
        "pre_ex_inner_dip_s": _p(pre.get("inner_dip_s")),
    }


def _label(result):
    """Outcome-only labels, never input to a pre-race signal."""
    parts = str(result.get("trifecta") or "").split("-")
    if len(parts) != 3 or any(c not in "123456" for c in parts):
        return None
    head, second, third = (int(s) for s in parts)
    if head == 1:
        label = "イン艇頭_5_6号艇がヒモ" if any(x in (5, 6) for x in (second, third)) else "イン艇頭_内寄り"
    elif head in (2, 3):
        label = "2_3号艇頭_外絡み" if any(x in (5, 6) for x in (second, third)) else "2_3号艇頭_内寄り"
    else:
        label = "4_5_6号艇頭_外攻め"
    return label


def _summarize_cohort(rows):
    mans = [x for x in rows if x["manshu"]]
    head = Counter(x["head"] for x in rows)
    mans_head = Counter(x["head"] for x in mans)
    return {
        "races": len(rows),
        "manshu_races": len(mans),
        "manshu_rate_pct": _rate(len(mans), len(rows)),
        "head_distribution_all": dict(sorted(head.items())),
        "head_distribution_manshu": dict(sorted(mans_head.items())),
        "manshu_with_5_or_6_in_top3": sum(x["contains_outer"] for x in mans),
        "manshu_1_head_with_5_or_6": sum(
            x["head"] == 1 and x["contains_outer"] for x in mans
        ),
        "manshu_2_3_head": sum(x["head"] in (2, 3) for x in mans),
        "manshu_4_5_6_head": sum(x["head"] in (4, 5, 6) for x in mans),
        "insufficient_for_stable_generalization": len(rows) < MIN_RECOMMENDED_SAMPLE,
    }


def analyze_weak_in(cases):
    """Group all eligible settled, pre-observed weak-venue cases.

    Include non-manshu as controls; no claim of independent predictive
    strength, and do not grade an unobserved race as a negative alert.
    """
    rows = []
    for case in cases:
        pre = case.get("pre_race_features") or {}
        result = case.get("observed_result") or {}
        jcd = str(pre.get("jcd") or "").zfill(2)
        baseline = VENUE_BASELINES.get(jcd)
        if not baseline or baseline["course1_win_pct"] >= 50:
            continue
        label = _label(result)
        payout = _p(result.get("payout_per_100"))
        if label is None or payout is None:
            continue
        features = _feature_profile(pre)
        first_head = int(str(result["trifecta"]).split("-")[0])
        contains_outer = bool(result.get("five_in_top3") or result.get("six_in_top3"))
        row = {
            "key": case["key"], "jcd": jcd, "venue": baseline["name"],
            "date": pre.get("day"), "rno": pre.get("rno"),
            "payout_per_100": int(payout), "manshu": bool(result.get("manshu")),
            "head": first_head, "trifecta": result.get("trifecta"),
            "contains_outer": contains_outer, "outcome_pattern": label,
            "pre_features": features,
            "alert": bool((case.get("pre_race_decision") or {}).get("alert")),
            "in_loss_suppressed_as_normal_venue": bool(
                (case.get("pre_race_decision") or {}).get("in_loss_suppressed_as_baseline")
            ),
            "result_source": result.get("source"),
        }
        rows.append(row)
    groups = defaultdict(list)
    groups["all"] = rows
    for r in rows:
        groups["venue_" + r["jcd"]].append(r)
        if r["pre_features"]["grade_status"] == "confirmed":
            if r["pre_features"]["a1_boats_2or3"]:
                groups["a1_in_2or3"].append(r)
            else:
                groups["no_a1_in_2or3"].append(r)
        else:
            groups["unknown_2or3_grade"].append(r)
        if r["pre_features"]["a1_with_both_exhibition_edges"]:
            groups["a1_2or3_advantage_in_exhibition"].append(r)
        if r["pre_features"]["five_ex_top3"] or r["pre_features"]["six_ex_top3"]:
            groups["outer_exhibition_top3"].append(r)
        if r["pre_features"]["lane1_ex_rank"] is not None and r["pre_features"]["lane1_ex_rank"] >= 4:
            groups["lane1_exhibition_rank4_or_worse"].append(r)
    summaries = {k: _summarize_cohort(v) for k, v in sorted(groups.items())}
    unique_manshu = [r for r in rows if r["manshu"]]
    hit_but_ordinary = [
        r["key"] for r in unique_manshu
        if r["head"] in (2, 3) and r["pre_features"]["a1_boats_2or3"]
    ]
    non1_manshu = [r for r in unique_manshu if r["head"] != 1]
    return {
        "version": STUDY_VERSION, "baseline_version": POLICY_VERSION,
        "official_baselines": {
            k: v for k, v in sorted(VENUE_BASELINES.items())
            if v["course1_win_pct"] < 50
        },
        "scope": "only settled races with frozen BEFORE-deadline six-boat data",
        "no_future_values_in_features": True,
        "model_training_state": "offline_case_study_not_predictor_retraining",
        "base": _summarize_cohort(rows),
        "cohorts": summaries,
        "manshu_cases": unique_manshu,
        "non_manshu_controls": [r for r in rows if not r["manshu"]],
        "ordinary_a1_2or3_head_manshu_candidates": hit_but_ordinary,
        "non1_head_manshu_count": len(non1_manshu),
        "one_head_manshu_count": sum(r["head"] == 1 for r in unique_manshu),
        "weak_in_head_does_not_imply_manshu": True,
        "notes": [
            "Course-1 historical rate does not equal boat-1 victory chance exactly; pre-ex-course stored.",
            "Non-1 head is common here. Only elevated payout is a manshu label.",
            "Unknown racer grade never treated as no-A1; 2/3 A1 alone not an alert.",
            "Cases are time-frozen pre-race features and separate hindsight labels.",
            "Cohort rates are exploratory; no automatic live sniper recalibration.",
        ],
    }
