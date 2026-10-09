"""Offline-only missed-manshu pattern exports for the Oct 10 shadow monitor.

A research feature can only use frozen pre-deadline observations. Official results
are stored separately as LABELS and must never be used to trigger alerts.
This module neither trains nor modifies the live Sniper Hole-kun or sends posts.
"""
from __future__ import annotations

from collections import Counter, defaultdict

SCHEMA_VERSION = "manshu-shadow-learning-v1"


def _n(value):
    try:
        return float(value) if value is not None else None
    except (ValueError, TypeError):
        return None


def pre_race_tags(entry):
    """Stable, interpret-able keys usable for case-matched negative controls."""
    wind, wave = _n(entry.get("pre_wind_m")), _n(entry.get("pre_wave_cm"))
    dip, gap = _n(entry.get("pre_inner_dip_s")), _n(entry.get("pre_outer_fast_gap_s"))
    rank = _n(entry.get("pre_lane1_rank"))
    fifth, sixth = _n(entry.get("pre_lane5_rank")), _n(entry.get("pre_lane6_rank"))
    tags = []
    venue = entry.get("venue_context") or {}
    if venue.get("weak_in_baseline"):
        tags.append("公式弱イン場（1コース1着率50%未満）")
    if venue.get("a1_2or3_lanes"):
        tags.append("2・3号艇にA1級あり")
    if venue.get("in_loss_suppressed_as_baseline"):
        tags.append("場の通常のイン敗北として警戒抑制")
    if venue.get("strong_exception"):
        tags.append("弱イン場で上乗せ異常あり")
    if wind is not None:
        tags.append("風3m以上" if wind >= 3 else "風3m未満")
    if wave is not None:
        tags.append("波3cm以上" if wave >= 3 else "波3cm未満")
    if wind is not None and wave is not None and wind < 3 and wave < 3:
        tags.append("低風波")
    if wind is not None and wave is not None and wind >= 3 and wave >= 3:
        tags.append("高風波")
    if rank is not None:
        tags.append("1号艇展示4位以下" if rank >= 4 else "1号艇展示3位以内")
    if dip is not None:
        tags.append("ST内凹み0.06以上" if dip >= 0.06 else "ST内凹み未満")
    if gap is not None:
        tags.append("外艇タイム優勢0.13以上" if gap >= 0.13 else "外艇タイム差未満")
    if fifth is not None and fifth <= 3:
        tags.append("5号艇展示3位以内")
    if sixth is not None and sixth <= 3:
        tags.append("6号艇展示3位以内")
    return tags


def reasons_alert_not_triggered(entry):
    """Explain gates not met using only the frozen observation.

    Multiple reasons can apply. These are descriptive, NOT counterfactual proofs.
    """
    if entry.get("alert"):
        return []
    wind, wave = _n(entry.get("pre_wind_m")), _n(entry.get("pre_wave_cm"))
    dip, gap = _n(entry.get("pre_inner_dip_s")), _n(entry.get("pre_outer_fast_gap_s"))
    rank = _n(entry.get("pre_lane1_rank"))
    r5, r6 = _n(entry.get("pre_lane5_rank")), _n(entry.get("pre_lane6_rank"))
    reasons = []
    venue = entry.get("venue_context") or {}
    if venue.get("in_loss_suppressed_as_baseline"):
        reasons.append("公式弱イン場のため通常のイン敗北シグナルを抑制")
    if venue.get("a1_2or3_lanes") and not venue.get("strong_exception"):
        reasons.append("2・3号艇A1の通常頭候補だけでは万舟イン敗北警戒に不足")
    if wind is not None and wave is not None and wind < 3 and wave < 3:
        reasons.append("気象ゲート不成立（風<3m・波<3cm）")
    if gap is not None and gap < 0.13:
        reasons.append("外艇展示タイム差0.13秒未満")
    if dip is not None and dip < 0.06:
        reasons.append("ST内凹み0.06秒未満")
    if rank is not None and rank <= 3:
        reasons.append("1号艇展示上位（1〜3位）")
    if wave is not None and wave < 3:
        reasons.append("ヒモ荒れ用波高3cmゲート不成立")
    if not any(v is not None and v <= 3 for v in (r5, r6)):
        reasons.append("5・6号艇の展示3位以内なし")
    return reasons


def _pre_fields(entry):
    return {
        "record_key": entry["key"],
        "day": entry["day"],
        "venue": entry.get("venue"),
        "jcd": entry["jcd"],
        "rno": entry["rno"],
        "observed_at": entry.get("observed_at"),
        "deadline": entry.get("deadline"),
        "lead_minutes": entry.get("lead_minutes"),
        "wind_m": entry.get("pre_wind_m"),
        "wave_cm": entry.get("pre_wave_cm"),
        "lane1_ex_rank": entry.get("pre_lane1_rank"),
        "lane5_ex_rank": entry.get("pre_lane5_rank"),
        "lane6_ex_rank": entry.get("pre_lane6_rank"),
        "inner_dip_s": entry.get("pre_inner_dip_s"),
        "outside_ex_time_advantage_s": entry.get("pre_outer_fast_gap_s"),
        "venue_context": entry.get("venue_context"),
        "weak_in_baseline_suppression": bool(entry.get("baseline_in_loss_suppressed")),
        "six_boat_exhibition": entry.get("pre_boats"),
        "features_complete": bool(entry.get("pre_boats")) and len(entry.get("pre_boats") or []) == 6,
        "tags": pre_race_tags(entry),
    }


def _case(entry):
    outcome = entry.get("outcome") or {}
    if outcome.get("settled") is not True:
        return None
    combination = str(outcome.get("trifecta") or "")
    slots = combination.split("-")
    if len(slots) != 3 or len(set(slots)) != 3:
        return None
    payout = outcome.get("payout_per_100")
    if payout is None:
        return None
    # Crucial separation: pre_race_features and observed_result stay separate.
    return {
        "key": entry["key"],
        "pre_race_features": _pre_fields(entry),
        "pre_race_decision": {
            "alert": bool(entry.get("alert")),
            "types": entry.get("types") or [],
            "rule": entry.get("rule"),
            "venue_policy_version": entry.get("venue_policy_version"),
            "in_loss_suppressed_as_baseline": bool(entry.get("baseline_in_loss_suppressed")),
            "context_reason": (entry.get("venue_context") or {}).get("decision_reason"),
            "not_triggered_reasons": reasons_alert_not_triggered(entry),
        },
        "observed_result": {
            "trifecta": combination,
            "payout_per_100": payout,
            "manshu": bool(outcome.get("manshu")),
            "head": slots[0],
            "second": slots[1],
            "third": slots[2],
            "five_in_top3": "5" in slots,
            "six_in_top3": "6" in slots,
            "race_shape": (
                "イン逃げヒモ荒れ" if slots[0] == "1"
                else "イン敗北3頭" if slots[0] == "3"
                else "イン敗北その他"
            ),
            "source": outcome.get("source"),
        },
        "sniper_join_key": entry.get("sniper_join_key") or entry["key"],
        "live_sniper_modified": False,
    }


def _tag_comparison(cases):
    """Ground each tag's occurrence rate in all observed, settled cases."""
    seen = defaultdict(lambda: {"n": 0, "manshu": 0, "alert": 0, "missed_manshu": 0})
    for case in cases:
        result = case["observed_result"]
        flagged = case["pre_race_decision"]["alert"]
        for tag in set(case["pre_race_features"]["tags"]):
            bucket = seen[tag]
            bucket["n"] += 1
            bucket["manshu"] += bool(result["manshu"])
            bucket["alert"] += bool(flagged)
            bucket["missed_manshu"] += bool(result["manshu"] and not flagged)
    return {
        tag: {
            **stats,
            "manshu_rate_pct": round(100 * stats["manshu"] / stats["n"], 1),
            "minimum_20_race_sample": stats["n"] >= 20,
        }
        for tag, stats in sorted(seen.items())
    }


def _unobserved_official_manshu(day, entries, official_results):
    """Separate official man-shu without any frozen pre-race snapshot.

    They are missing observation opportunities, NOT rule-based no-alert examples.
    Never reconstruct a signal using postrace/exhibition fields that may be overwritten.
    """
    seen = {f'{int(x["jcd"]):02d}:{int(x["rno"])}' for x in entries.values()}
    cases = []
    checked = 0
    for official_key, record in sorted((official_results or {}).items()):
        if not isinstance(record, dict) or record.get("status") != "settled":
            continue
        try:
            jcd_raw, rno_raw = str(official_key).split(":", 1)
            jcd, rno = f"{int(jcd_raw):02d}", int(rno_raw)
        except (ValueError, TypeError):
            continue
        key = f"{jcd}:{rno}"
        if key in seen:
            continue
        payouts = record.get("payouts") or {}
        valid = [
            (combo, _n(pay)) for combo, pay in payouts.items()
            if isinstance(combo, str) and len(combo.split("-")) == 3
            and len(set(combo.split("-"))) == 3
            and all(x in "123456" for x in combo.split("-"))
        ]
        valid = [(combo, pay) for combo, pay in valid if pay is not None and pay > 0]
        if len(valid) != 1:
            continue
        checked += 1
        combo, amount = valid[0]
        if amount >= 10000:
            cases.append({
                "key": f"{day}_{jcd}_{rno:02d}",
                "day": day, "jcd": jcd, "rno": rno,
                "classification": "no_prerace_observation_unknown_alert",
                "reason": "締切前の凍結展示データ未取得。発報ルールの見逃しと混同しない",
                "trifecta": combo, "payout_per_100": int(amount),
                "source": record.get("source_url"),
                "pre_race_features": None,
                "eligible_for_signal_learning": False,
            })
    return checked, cases


def export_learning(day, entries, official_results=None):
    """Return a learning dataset without silently rewriting production rules."""
    settled = [_case(row) for _, row in sorted(entries.items())]
    settled = [row for row in settled if row is not None]
    misses = [x for x in settled if x["observed_result"]["manshu"]
              and not x["pre_race_decision"]["alert"]]
    alert_manshu = [x for x in settled if x["observed_result"]["manshu"]
                    and x["pre_race_decision"]["alert"]]
    ordinary = [x for x in settled if not x["observed_result"]["manshu"]]
    shapes = Counter(x["observed_result"]["race_shape"] for x in misses)
    heads = Counter(x["observed_result"]["head"] for x in misses)
    reasons = Counter(reason for x in misses
                      for reason in x["pre_race_decision"]["not_triggered_reasons"])
    unobserved_count, unobserved_manshu = _unobserved_official_manshu(
        day, entries, official_results
    )
    return {
        "day": day,
        "schema": SCHEMA_VERSION,
        "training_status": "case_collection_only_not_model_retraining",
        "live_sniper_integration": "not_enabled",
        "join_key_format": "YYYYMMDD_JCD_RR",
        "target_alert_manshu_rate_pct": 30.0,
        "target_is_an_alert_condition_precision_not_ticket_hit_rate": True,
        "resolved_examples": len(settled),
        "missed_manshu_count": len(misses),
        "unobserved_official_resolved_races": unobserved_count,
        "unobserved_official_manshu_count": len(unobserved_manshu),
        "total_unalerted_or_unobserved_manshu_cases": len(misses) + len(unobserved_manshu),
        "unobserved_official_manshu_cases": unobserved_manshu,
        "alert_manshu_count": len(alert_manshu),
        "negative_control_count": len(ordinary),
        "missed_manshu_keys": [x["key"] for x in misses],
        "missed_manshu_shape_counts": dict(sorted(shapes.items())),
        "missed_manshu_winning_head_counts": dict(sorted(heads.items())),
        "missed_manshu_failure_gate_counts": dict(sorted(reasons.items())),
        "tag_comparisons": _tag_comparison(settled),
        "missed_manshu_cases": misses,
        "alert_manshu_cases": alert_manshu,
        "non_manshu_control_cases": ordinary,
        "sniper_future_bridge": {
            "status": "analysis_only",
            "join_key": "sniper_join_key",
            "combine_later_with": [
                "opportunity_alerts.py sniper select yes/no",
                "sniper score", "best expected value", "one_head_probability",
                "non_one_head_probability", "chosen ticket and official outcome",
            ],
            "leakage_guard": "only pre-race features for signal; outcomes as labels",
            "do_not_autotune_on_same_evaluation_day": True,
        },
    }
