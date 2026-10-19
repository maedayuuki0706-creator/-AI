"""Main engine + New-Yuuki scenario v2 + venue diagnostics.

An independent *research-only* comparison. Main ranker is literally
prediction_engine.analyze_race; never substitute a retrospective score for it.
This module has no fetching, dispatch, X, Discord, cron or state writes.

Production parity requires supplying the fully preprocessed main input from
the SAME pre-deadline capture, with independent source timestamps. A specialist
input alone lacks national/local stats and official odds and MUST NOT be treated
as an authentic existing-main forecast. If such a capture is unavailable, no
fusion prediction exists, even though descriptive scenarios can still be saved.

The venue residual is zero until out-of-time approved; no invented weather/tide
impact. Actual tactics and forecast probabilities are not verified by this code.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import datetime
from math import exp, isfinite
from zoneinfo import ZoneInfo

from prediction_engine import analyze_race
from research.scenario_v2 import engine as scenario
from research.venue_specialists_v1 import engine as venue

JST = ZoneInfo("Asia/Tokyo")
VERSION = "main-plus-yuuki-plus-venue-v1-isolated-research"
REQUIRED_MAIN_FIELDS = (
    "win_rate", "top2_rate", "top3_rate", "local_win_rate",
    "motor_top2_rate", "motor_top3_rate",
    "boat_top2_rate", "boat_top3_rate", "avg_st",
)
ALLOWED_SOURCE = "official_pre_deadline_single_snapshot"
EXPECTED_MAIN_VERSION = "kyoutei-navi-course-v7-market-structure"


def _verify_main_capture(specialist, main_capture):
    """Do not silently downgrade missing input into the main engine's defaults."""
    scenario.reject_outcomes(specialist)
    scenario.reject_outcomes(main_capture)
    if not isinstance(main_capture, dict) or not isinstance(main_capture.get("payload"), dict):
        raise ValueError("Missing real main-engine input payload")
    meta = main_capture.get("meta")
    if not isinstance(meta, dict):
        raise ValueError("Missing main source timestamp and race identity")
    s_meta = specialist["meta"]
    for key in ("day", "rno", "deadline"):
        if str(meta.get(key)) != str(s_meta.get(key)):
            raise ValueError("Mismatch between main and specialist race: " + key)
    if str(meta.get("jcd")).zfill(2) != str(s_meta.get("jcd")).zfill(2):
        raise ValueError("Main venue mismatch")
    if meta.get("source_type") != ALLOWED_SOURCE:
        raise ValueError("Main must come from a genuine frozen official pre-race capture")
    if meta.get("production_preprocessing_verified") is not True:
        raise ValueError("Original full-main preprocessing has not been verified")
    if not meta.get("source_sha256") or len(str(meta["source_sha256"])) != 64:
        raise ValueError("Source content hash required")
    captured = scenario.aware(s_meta["captured_at"])
    main_observed = scenario.aware(meta["captured_at"])
    source_observed = scenario.aware(meta["source_observed_at"])
    if not (source_observed <= main_observed <= captured):
        raise ValueError("Future source observations are not allowed")
    if (captured - source_observed).total_seconds() > 120:
        raise ValueError("Inputs were not captured together (over 120 seconds)")
    if "db_snapshot_at" in meta and meta["db_snapshot_at"]:
        if scenario.aware(meta["db_snapshot_at"]) > source_observed:
            raise ValueError("Future database in main capture")
    main = main_capture["payload"]
    if not isinstance(main.get("race"), dict) or not isinstance(main.get("boats"), list):
        raise ValueError("Main race and six official boats required")
    code = str(s_meta["jcd"]).zfill(2)
    if code not in venue.VENUES:
        raise ValueError("Venue not a four-venue research specialist")
    if main["race"].get("venue") != venue.VENUES[code]["venue"]:
        raise ValueError("Main race venue string does not match")
    s_boats = {int(b["lane"]): b for b in specialist["boats"]}
    m_boats = {}
    for b in main["boats"]:
        try:
            lane = int(b["lane"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("Main missing a numbered boat")
        if lane in m_boats:
            raise ValueError("Duplicate main boat")
        m_boats[lane] = b
    if set(s_boats) != set(range(1, 7)) or set(m_boats) != set(range(1, 7)):
        raise ValueError("Exactly six entrants in each input required")
    for lane in range(1, 7):
        s, m = s_boats[lane], m_boats[lane]
        if str(s.get("racer_id")) != str(m.get("racer_id")):
            raise ValueError("Main and scenario racer IDs differ")
        if int(s["course"]) != int(m.get("predicted_course", m.get("course", 0))):
            raise ValueError("Main and scenario observed entry courses differ")
        if any(m.get(key) is None for key in REQUIRED_MAIN_FIELDS):
            raise ValueError("Main official input missing required field for boat " + str(lane))
    odds = main.get("trifecta_odds")
    if odds is not None and not isinstance(odds, dict):
        raise ValueError("Odds must be captured mapping or absent")
    return main, meta


def _ordered_cards(rows):
    if len(rows) != 120 or len({r["combination"] for r in rows}) != 120:
        raise ValueError("Main did not produce all 120 ordered trifectas")
    ranked = []
    for row in rows:
        combination = row.get("combination")
        value = row.get("probability")
        if combination not in scenario.COMBINATIONS or isinstance(value, bool):
            raise ValueError("Main output has invalid combinations/probabilities")
        if not isinstance(value, (int, float)) or not (0 < value < float("inf")):
            raise ValueError("Main output is not finite")
        ranked.append({"combination": combination, "main_probability": value})
    if abs(sum(r["main_probability"] for r in ranked) - 1.0) > 1e-7:
        raise ValueError("Main 120 probabilities are not normalized")
    return sorted(ranked, key=lambda x: (-x["main_probability"], x["combination"]))


def _venue_adjust(main_rank, lane_audits):
    """Conditional and bounded scenario research: zero residual == no change."""
    scores = {int(r["lane"]): float(r["score"]) for r in lane_audits}
    if set(scores) != set(range(1, 7)):
        raise ValueError("Six venue-lane audit scores are required")
    if any(not isfinite(v) or abs(v) > .6 for v in scores.values()):
        raise ValueError("Unbounded venue score; require separately validated evidence")
    if all(abs(v) < 1e-12 for v in scores.values()):
        return main_rank, False
    values = []
    for r in main_rank:
        head = int(r["combination"][0])
        w = r["main_probability"] * exp(scores[head])
        values.append((r["combination"], w))
    normalizer = sum(w for _, w in values)
    # These scores are not calibrated probabilities; just a research ranking.
    ranked = sorted(({"combination": key, "main_probability": w / normalizer}
                     for key, w in values),
                    key=lambda row: (-row["main_probability"], row["combination"]))
    return ranked, True


def _build_with_ranking(snapshot, ranking, *, mode, now):
    source = deepcopy(snapshot)
    source["baseline_ranking"] = [r["combination"] for r in ranking]
    source["baseline_picks"] = source["baseline_ranking"][:10]
    output = scenario.generate(source, mode=mode, now=now)
    scenario.verify(output)
    if output["virtual_card"] is None or len(output["virtual_card"]["picks"]) != 10:
        raise ValueError("Incomplete hybrid scenario selection")
    return output


def _card(obj):
    picks = obj["virtual_card"]["picks"]
    if len(picks) != 10 or len(set(picks)) != 10 or not set(picks) <= scenario.COMBINATIONS:
        raise ValueError("Invalid 10-point card")
    return picks


def generate(specialist_snapshot, main_capture, *, mode="replay", now=None,
             venues_db=None, motor_db=None, conditioned=None):
    """One race / six authentic entrants / one captured pre-deadline time.

    replay: post-race simulation (NEVER count as a saved pre-deadline forecast).
    live: caller still needs real Git receipt and operational audit to count.
    Neither mode posts or saves anything.
    """
    if now is None:
        now = datetime.now(JST).isoformat()
    # Even the unadorned specialist source must pass the strict research preflight.
    scenario.validate(specialist_snapshot, mode, now)
    main_payload, meta = _verify_main_capture(specialist_snapshot, main_capture)
    main = analyze_race(deepcopy(main_payload))
    if main["model_version"] != EXPECTED_MAIN_VERSION:
        raise ValueError("Unrecognized original main-engine version")
    raw_rank = _ordered_cards(main["trifecta"])
    # Old main itself supplies the baseline, not V4 or a reconstructed synthetic model.
    primary = raw_rank[:10]
    yuuki = _build_with_ranking(specialist_snapshot, raw_rank, mode=mode, now=now)
    # Venue engine supplies *gated* evidence; currently unvalidated scores are zero.
    specialist = venue.analyze(specialist_snapshot, venues_db=venues_db,
                               motor_db=motor_db, conditioned=conditioned,
                               mode=mode, now=now)
    venue_rank, enabled = _venue_adjust(raw_rank, specialist["lane_audits"])
    final_scenario = (_build_with_ranking(specialist_snapshot, venue_rank, mode=mode, now=now)
                      if enabled else yuuki)
    variants = {
        "existing_main": [r["combination"] for r in primary],
        "existing_main_plus_yuuki": _card(yuuki),
        "existing_main_plus_yuuki_plus_venue": _card(final_scenario),
    }
    for card in variants.values():
        if len(card) != 10 or len(set(card)) != 10:
            raise ValueError("Bad 10-point research comparison")
    probabilities = {r["combination"]: r["main_probability"] for r in raw_rank}
    result = {
        "version": VERSION, "research_only": True,
        "status": "retrospective_replay" if mode == "replay" else "prospective_uncheckpointed",
        "count_as_delivered": False, "auto_promote_live": False,
        "race_id": specialist["race_id"],
        "captured_at": specialist_snapshot["meta"]["captured_at"],
        "main_source_captured_at": meta["captured_at"],
        "source_identity_sha256": meta["source_sha256"],
        "raw_specialist_input_digest": scenario.digest(specialist_snapshot),
        "raw_main_input_digest": scenario.digest(main_capture),
        "main_engine_version": main["model_version"],
        "main_120_rank": raw_rank,
        "main_head_strength": {str(lane): round(sum(
            r["main_probability"] for r in raw_rank
            if r["combination"].startswith(str(lane) + "-")), 8)
            for lane in range(1, 7)},
        "yuuki_v2_digest": yuuki["digest"],
        "all_six_win_and_loss_hypotheses": yuuki["lanes"],
        "yuuki_supported_pre_race_formations": yuuki["formation_candidates"],
        "venue_diagnostics_digest": specialist["digest"],
        "venue_name": specialist["venue"],
        "venue_observations": specialist["seven_features"],
        "venue_lane_audits": specialist["lane_audits"],
        "venue_validated_adjustment_active": enabled,
        "variants": variants,
        "main_probability_is_calibrated": False,
        "expected_value_computed": False,
        "unit_yen": 100, "points": 10, "per_variant_stake_yen": 1000,
        "limits": [
            "No current venue weather/tide/motor effects are enabled until holdout validation",
            "No official actual ST, finishing position or payout enters either input",
            "Six-lane attack and outcome hypothesis does not prove actual 1M tactics",
            "Research-only comparison; pre-deadline remote Git receipt required for forward performance",
            "Full preprocessing must be frozen from main engine before the forecast deadline",
            "No additional probability calibration or odds/EV recomputation is applied",
        ],
    }
    result["digest"] = scenario.digest(result)
    return result
