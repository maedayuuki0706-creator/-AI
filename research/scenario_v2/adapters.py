"""Read a frozen research snapshot; never read current DB or enriched exhibition logs."""
from copy import deepcopy
from .engine import aware, digest, number, reject_outcomes, verify


def from_fusion(record, checkpoint):
    verify(record)
    key = record["key"]
    if checkpoint.get("key") != key or checkpoint.get("prediction_digest") != record["digest"]:
        raise ValueError("Checkpoint identity/digest mismatch")
    if checkpoint.get("eligible_checkpoint") is not True:
        raise ValueError("Source checkpoint not eligible")
    frozen = aware(checkpoint["prediction_committed_at"])
    captured, created, deadline = map(aware, (record["captured_at"], record["created_at"], record["deadline_at"]))
    if not captured <= created <= frozen < deadline:
        raise ValueError("No valid pre-deadline frozen source")
    for value in (record["pre_race_boats"], record.get("pre_race_weather"), record.get("hiyori_features")):
        reject_outcomes(value)
    db = record.get("database") or {}
    if db.get("snapshot_at") and aware(db["snapshot_at"]) > captured:
        raise ValueError("Future DB snapshot")
    by_lane = {int(f["lane"]): f for f in record.get("hiyori_features", [])}
    boats = []
    for raw in record["pre_race_boats"]:
        lane = int(raw["lane"])
        f = by_lane.get(lane, {})
        preview = f.get("preview") or {}
        for field, expected in (("hiduke", record["day"]), ("place_no", record["jcd"]),
                                ("race_no", record["rno"]), ("player_no", raw["racer_id"])):
            if preview.get(field) is not None and int(preview[field]) != int(expected):
                raise ValueError(f"Timing preview identity mismatch: {field}")
        boat = {"lane": lane, "course": raw.get("predicted_course", raw.get("course")),
                "racer_id": str(raw.get("racer_id") or ""), "name": raw.get("name"),
                "class": raw.get("current_class"), "motor_number": raw.get("motor_number"),
                "avg_st": raw.get("avg_st"), "motor_top2_rate": raw.get("motor_top2_rate"),
                "course_top2_rate": raw.get("course_top2_rate"),
                "exhibition_st": raw.get("exhibition_st_timing", raw.get("exhibition_st")),
                "exhibition_flying": raw.get("exhibition_flying"), "exhibition_time": raw.get("exhibition_time"),
                "historical_course_st": raw.get("course_history_avg_st"),
                "historical_course_samples": raw.get("course_history_samples"),
                "historical_course_win_methods": deepcopy(raw.get("racer_profile_course_win_methods")),
                "previous_day_form": None,
                "db_adjustment_observation": deepcopy(db.get("lane_factors", {}).get(str(lane))),
                "observations": [], "unavailable_observations": []}
        for dest, source in (("straight_time", "chokusen"), ("turn_time", "mawariashi"), ("lap_time", "shukai")):
            raw_value = number(preview.get(source), -1, 10000)
            if raw_value in (-1, 0):
                boat["unavailable_observations"].append({"field": dest, "raw_value": raw_value,
                                                         "reason": "source missing/non-timing sentinel"})
                raw_value = None
            boat[dest] = raw_value / 100 if raw_value else None
            if raw_value:
                boat["observations"].append({"field": dest, "raw_field": source,
                                             "raw_value": raw_value, "scale": .01,
                                             "observed_at": record["captured_at"],
                                             "source": "frozen hiyori same-race preview"})
        boats.append(boat)
    card = record["models"]["fusion"]
    picks = list(card.get("main_picks", [])) + list(card.get("cover_picks", []))
    if picks != card["picks"]:
        raise ValueError("Frozen main/cover card differs from picks")
    return {"meta": {"day": record["day"], "jcd": record["jcd"], "rno": record["rno"],
                     "deadline": record["deadline"], "captured_at": record["created_at"],
                     "source_observed_at": record["captured_at"], "db_snapshot_at": db.get("snapshot_at")},
            "boats": boats, "environment": deepcopy(record.get("pre_race_weather") or {}),
            "baseline_picks": picks,
            "baseline_ranking": [r["combination"] for r in record["trifecta"]],
            "source": {"kind": "frozen_fusion_pre_race", "digest": record["digest"],
                       "commit_sha": checkpoint.get("commit_sha"), "committed_at": frozen.isoformat(),
                       "version": record.get("scenario_version"), "code_sha": record.get("code_sha"),
                       "db_snapshot_at": db.get("snapshot_at"),
                       "missing": ["current motor-period identity", "verified prior-day form", "1M video labels"],
                       "timing_note": "capture timestamp is the frozen forecast creation; source measurements retain their earlier timestamp"}}
