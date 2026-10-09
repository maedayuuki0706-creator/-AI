"""Conservative venue-aware gate for internal *upset* shadow alerts.

Official BOAT RACE 2026-07-01..2026-09-30 course-1 win rates.
A weak-in venue's ordinary non-1 head outcome is not itself a rare upset.

Research only. This file does not send alerts or modify any real prediction.
"""
from __future__ import annotations

VENUE_BASELINES = {
    "02": {
        "name": "戸田", "course1_win_pct": 42.8,
        "period": "2026-07-01..2026-09-30",
        "source": "https://www.boatrace.jp/owpc/pc/data/stadium?jcd=02",
    },
    "03": {
        "name": "江戸川", "course1_win_pct": 48.8,
        "period": "2026-07-01..2026-09-30",
        "source": "https://www.boatrace.jp/owpc/pc/data/stadium?jcd=03",
    },
    "04": {
        "name": "平和島", "course1_win_pct": 40.5,
        "period": "2026-07-01..2026-09-30",
        "source": "https://www.boatrace.jp/owpc/pc/data/stadium?jcd=04",
    },
}
WEAK_IN_COURSE1_THRESHOLD_PCT = 50.0
POLICY_VERSION = "course1-venue-baseline-20260701-20260930-v1"


def as_number(value):
    try:
        return float(value) if value is not None else None
    except (ValueError, TypeError):
        return None


def gate_in_loss(jcd, boats, ex_st, ex_time, lane1_rank, wind, wave, generic_upset):
    """Return (allowed, frozen_venue_context).

    Weak-in venues require strong evidence above the usual 2/3-course threat:
      * A1 entrant in boat 2/3 AND a direct exhibition advantage over boat 1,
      * AND severe water or multiple independent remarkable exhibition signals.
    A1 standing alone is explicitly NOT a trigger.
    """
    info = VENUE_BASELINES.get(str(jcd).zfill(2))
    weak = bool(info and info["course1_win_pct"] < WEAK_IN_COURSE1_THRESHOLD_PCT)
    ctx = {
        "policy_version": POLICY_VERSION,
        "verified_baseline": bool(info),
        "weak_in_baseline": weak,
        "baseline_course1_win_pct": info["course1_win_pct"] if info else None,
        "baseline_source": info["source"] if info else None,
        "baseline_period": info["period"] if info else None,
        "a1_2or3_lanes": [],
        "strong_attacker_lanes": [],
        "attacker_evidence": [],
        "normal_outside_head_context": False,
        "generic_in_loss_triggered": bool(generic_upset),
        "in_loss_suppressed_as_baseline": False,
        "strong_exception": False,
        "decision_reason": "",
    }
    if not weak:
        ctx["decision_reason"] = (
            "通常の展示・気象判定（弱イン場として公式に確認された対象外）"
            if generic_upset else "通常の展示・気象条件が未成立"
        )
        return bool(generic_upset), ctx

    for lane in (2, 3):
        if str(boats[lane].get("current_class") or "").strip().upper() != "A1":
            continue
        ctx["a1_2or3_lanes"].append(lane)
        gap_t = round(ex_time[1] - ex_time[lane], 3)
        gap_st = round(ex_st[1] - ex_st[lane], 3)
        st_valid = ex_st[1] >= 0 and ex_st[lane] >= 0
        lane_rank = as_number(boats[lane].get("exhibition_rank"))
        evidence = {
            "lane": lane, "class": "A1",
            "time_advantage_s": gap_t,
            "st_advantage_s": gap_st if st_valid else None,
            "exhibition_rank": lane_rank,
        }
        ctx["attacker_evidence"].append(evidence)
        # Both speed and first-turn attack signs must exceed ordinary head risk,
        # not merely the venue's baseline 1-course weakness.
        strong_time = gap_t >= 0.10
        strong_st = st_valid and gap_st >= 0.08
        strong_rank = lane_rank is not None and lane_rank <= 2 and lane1_rank >= 4
        abnormal_water = wind >= 4 or wave >= 4
        very_large_dual_edge = (gap_t >= 0.13 and st_valid and gap_st >= 0.06)
        unusual_dominance = (lane1_rank >= 5 and strong_time and strong_st)
        extreme_weather_attack = (abnormal_water and
                                  ((strong_time and strong_st) or
                                   (strong_time and strong_rank) or
                                   (strong_st and strong_rank)))
        if very_large_dual_edge or unusual_dominance or extreme_weather_attack:
            ctx["strong_attacker_lanes"].append(lane)

    ctx["normal_outside_head_context"] = bool(ctx["a1_2or3_lanes"])
    ctx["strong_exception"] = bool(ctx["strong_attacker_lanes"])
    allowed = bool(generic_upset and ctx["strong_exception"])
    ctx["in_loss_suppressed_as_baseline"] = bool(generic_upset and not allowed)
    if allowed:
        ctx["decision_reason"] = "弱イン場だが2/3号艇A1が複数の異常展示材料を満たした例外"
    elif ctx["a1_2or3_lanes"]:
        ctx["decision_reason"] = "2/3号艇A1は通常の頭候補。明確な上乗せ異常なしではイン敗北警戒しない"
    else:
        ctx["decision_reason"] = "弱イン場の通常のイン敗北は警戒対象外。2/3号艇のA1攻め根拠が未確認"
    return allowed, ctx
