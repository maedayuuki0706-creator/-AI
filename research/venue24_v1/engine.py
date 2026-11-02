"""Research-only 24-venue data mart. No betting, X/Discord, or production imports."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from hashlib import sha256
from pathlib import Path
import argparse
import json
import math
import re

# Original exhibition measurements vary by venue. Do not substitute one metric for another.
NAMES = (
    "桐生", "戸田", "江戸川", "平和島", "多摩川", "浜名湖",
    "蒲郡", "常滑", "津", "三国", "びわこ", "住之江",
    "尼崎", "鳴門", "丸亀", "児島", "宮島", "徳山",
    "下関", "若松", "芦屋", "福岡", "唐津", "大村",
)
# This is a source-availability registry, NOT a statement that scraping works for 23 venues.
NO_ORIGINAL = {"03"}
NO_STRAIGHT = {"12", "13", "18"}
HALF_LAP = {"01"}
METRICS = ("half_lap_time", "lap_time", "turn_time", "straight_time")
ORIGINAL_SOURCES_VERIFIED = {"23": "boatrace-karatsu.jp"}
MIN_VENUE_COURSE_RACES = 30
MIN_PLAYER_VENUE_RACES = 5

VENUES = {
    f"{i:02d}": {
        "name": name,
        "ai_name": name + "くん",
        "original_supported": f"{i:02d}" not in NO_ORIGINAL,
        "expected_metrics": (
            (["half_lap_time"] if f"{i:02d}" in HALF_LAP else ["lap_time"])
            + ["turn_time"]
            + ([] if f"{i:02d}" in NO_STRAIGHT else ["straight_time"])
            if f"{i:02d}" not in NO_ORIGINAL else []
        ),
        "automatic_original_source_verified": f"{i:02d}" in ORIGINAL_SOURCES_VERIFIED,
    }
    for i, name in enumerate(NAMES, 1)
}


def canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode()


def digest(value):
    return sha256(canonical(value)).hexdigest()


def as_time(value):
    if not value:
        return None
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Timezone-aware receipt required")
    return dt


def positive_number(value, low, high):
    if value is None or isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return round(n, 3) if math.isfinite(n) and low <= n <= high else None


def race_id(day, venue_code, rno):
    if not re.fullmatch(r"\d{8}", str(day)) or venue_code not in VENUES or not 1 <= int(rno) <= 12:
        raise ValueError("Invalid day, venue or race number")
    datetime.strptime(str(day), "%Y%m%d")
    return f"{day}_{venue_code}_{int(rno):02d}"


def valid_six(rows, id_key):
    if not isinstance(rows, list) or len(rows) != 6:
        raise ValueError("Six boat records required")
    lanes = [int(row["lane"]) for row in rows]
    if sorted(lanes) != list(range(1, 7)):
        raise ValueError("Six unique lanes required")
    if len({str(row[id_key]) for row in rows}) != 6 or not all(str(row[id_key]).isdigit() for row in rows):
        raise ValueError("Six unique racer IDs required")


def normalize_official(raw):
    """Existing data/exhibition_log/YYYYMMDD/CC_RR.json, recorded by production read-only."""
    day = str(raw["day"])
    code = str(raw["jcd"]).zfill(2)
    key = race_id(day, code, raw["rno"])
    valid_six(raw["rows"], "racer_id")
    rows = []
    for old in sorted(raw["rows"], key=lambda b: int(b["lane"])):
        rows.append({
            "lane": int(old["lane"]),
            "racer_id": str(old["racer_id"]),
            "racer_name": str(old.get("name") or ""),
            "motor_number": old.get("motor_number"),
            "boat_number": old.get("boat_number"),
            "exhibition_time": positive_number(old.get("exhibition_time"), 5, 10),
            "exhibition_st": positive_number(old.get("exhibition_st"), -1, 2),
            "exhibition_course": old.get("exhibition_course"),
            "tilt": old.get("tilt"),
            "original": None,
            "outcome": {
                "actual_course": old.get("actual_course"),
                "actual_st": old.get("actual_st"),
                "finish": old.get("finish"),
                "method": old.get("method"),
            } if raw.get("settled") else None,
        })
    return {
        "schema": "venue24/research-v1", "race_id": key, "day": day,
        "venue_code": code, "venue": VENUES[code]["name"],
        "captured_at": raw.get("captured_at"), "deadline": raw.get("deadline"),
        "settled": bool(raw.get("settled")), "rows": rows,
        "original_status": "not_yet_joined",
        "official_digest": digest(raw),
    }


def normalize_original(original, official):
    """Join by ALL six racer IDs, lane and motor numbers; never join by lane alone."""
    if not original:
        return None, "not_collected"
    if original.get("race_id") != official["race_id"]:
        return None, "race_identity_mismatch"
    if original.get("status") != "ok":
        return None, "source_" + str(original.get("status") or "unknown")
    obs = original.get("rows", original.get("data"))
    if not isinstance(obs, list):
        return None, "no_six_rows"
    try:
        valid_six(obs, "racer_id")
    except (KeyError, ValueError, TypeError):
        return None, "invalid_six_boats"
    by_lane = {int(row["lane"]): row for row in obs}
    for row in official["rows"]:
        found = by_lane[row["lane"]]
        if str(found["racer_id"]) != row["racer_id"]:
            return None, "racer_identity_mismatch"
        if str(found.get("motor_number")) != str(row["motor_number"]):
            return None, "motor_identity_mismatch"
    acquisition = original.get("acquisition") or {}
    taken_at = acquisition.get("retrieved_at")
    try:
        captured = as_time(taken_at)
        deadline = as_time(official["day"][:4] + "-" + official["day"][4:6] + "-" + official["day"][6:8] + "T" + official["deadline"] + ":00+09:00")
    except (ValueError, TypeError):
        return None, "timestamp_unverifiable"
    if captured > deadline:
        return None, "captured_after_deadline"
    metrics = set(VENUES[official["venue_code"]]["expected_metrics"])
    normalized = {}
    for lane, row in by_lane.items():
        values = {}
        for metric in METRICS:
            if metric in metrics:
                values[metric] = positive_number(row.get(metric), 2, 80)
            else:
                values[metric] = None
        normalized[lane] = values
    if all(all(item.get(metric) is None for metric in metrics) for item in normalized.values()):
        return None, "all_original_fields_missing"
    return {
        "captured_at": taken_at, "url": acquisition.get("url"),
        "source_sha256": acquisition.get("sha256"),
        "source_published_at": acquisition.get("published_at"),
        "source_publish_time_verified": bool(acquisition.get("published_at")),
        "scoring_connected": False,
        "rows_by_lane": normalized,
    }, ("retrospective_secondary_source" if acquisition.get("source_family") == "BoatraceCSV_secondary" else "captured_before_deadline")


def join_official_original(raw, original=None):
    official = normalize_official(raw)
    original_data, status = normalize_original(original, official)
    official["original_status"] = status if VENUES[official["venue_code"]]["original_supported"] else "not_published_at_venue"
    if original_data:
        official["original_acquisition"] = {k: v for k, v in original_data.items() if k != "rows_by_lane"}
        for row in official["rows"]:
            row["original"] = original_data["rows_by_lane"][row["lane"]]
    return official


def original_index(folder):
    """Latest valid version chosen independently for each race; no fabricated backfill."""
    records = defaultdict(list)
    if not folder:
        return records
    for p in sorted(Path(folder).rglob("*.json")):
        try:
            item = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(item, dict):
                continue
            key = item.get("race_id")
            if key and re.fullmatch(r"\d{8}_\d{2}_\d{2}", key):
                records[key].append(item)
        except (OSError, json.JSONDecodeError):
            continue
    return records


def find_original(variants, official):
    acceptable = []
    failures = []
    for candidate in variants:
        norm, reason = normalize_original(candidate, official)
        if norm is not None:
            source_priority = 0 if candidate.get("acquisition", {}).get("source_family") == "BoatraceCSV_secondary" else 1
            acceptable.append((source_priority, as_time(norm["captured_at"]), candidate))
        else:
            failures.append(reason)
    if acceptable:
        return max(acceptable, key=lambda item: (item[0], item[1]))[2]
    return variants[-1] if variants else None


def build_records(official_dir, original_dir=None, through=None):
    orig = original_index(original_dir)
    records = {}
    for path in sorted(Path(official_dir).glob("[0-9]" * 8 + "/[0-9][0-9]_[0-9][0-9].json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            record = normalize_official(raw)
            if through and record["day"] > through:
                continue
            match = find_original(orig.get(record["race_id"], []), record)
            record = join_official_original(raw, match)
            records[record["race_id"]] = record
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            # Invalid records are excluded, never transformed into clean zeroes.
            continue
    return [records[key] for key in sorted(records)]


def fit_venue_profiles(records, as_of):
    """Fit strictly on earlier *calendar days*, avoiding intraday result leakage."""
    training = [r for r in records if r["day"] < as_of and r["settled"]]
    profiles = {}
    for code, venue in VENUES.items():
        subset = [r for r in training if r["venue_code"] == code]
        by_course = defaultdict(lambda: {"races": 0, "wins": 0})
        by_player = defaultdict(lambda: {"races": 0, "wins": 0, "original": defaultdict(list)})
        sample_races = 0
        for race in subset:
            rows = race["rows"]
            if any(not row["outcome"] or not isinstance(row["outcome"].get("finish"), int)
                   or not isinstance(row["outcome"].get("actual_course"), int)
                   for row in rows):
                continue
            if sorted(row["outcome"]["finish"] for row in rows) != list(range(1, 7)):
                continue
            sample_races += 1
            for row in rows:
                course = row["exhibition_course"]
                if not isinstance(course, int) or not 1 <= course <= 6:
                    continue
                win = row["outcome"]["finish"] == 1
                stats = by_course[course]
                stats["races"] += 1
                stats["wins"] += int(win)
                player = by_player[row["racer_id"]]
                player["races"] += 1
                player["wins"] += int(win)
                for metric, value in (row["original"] or {}).items():
                    if metric in METRICS and value is not None:
                        player["original"][metric].append(value)
        profiles[code] = {
            "schema": "venue24/model-v1", "ai_name": venue["ai_name"],
            "venue_code": code, "venue": venue["name"], "trained_through": as_of,
            "training_races": sample_races, "no_betting_or_dispatch": True,
            "original_supported": venue["original_supported"],
            "source_status": "original_source_verified" if venue["automatic_original_source_verified"]
                             else ("not_published" if not venue["original_supported"] else "adapter_unverified"),
            "course_observations": {
                str(i): {
                    **by_course[i],
                    "observed_win_rate": round(by_course[i]["wins"] / by_course[i]["races"], 4)
                    if by_course[i]["races"] >= MIN_VENUE_COURSE_RACES else None,
                    "status": "observed" if by_course[i]["races"] >= MIN_VENUE_COURSE_RACES else "insufficient_sample",
                } for i in range(1, 7)
            },
            "racer_observations": {
                racer: {
                    "races": values["races"],
                    "wins": values["wins"],
                    "observed_win_rate": round(values["wins"] / values["races"], 4)
                    if values["races"] >= MIN_PLAYER_VENUE_RACES else None,
                    "original_means": {
                        metric: round(sum(data) / len(data), 3) if len(data) >= MIN_PLAYER_VENUE_RACES else None
                        for metric, data in values["original"].items()
                    },
                    "original_sample_counts": {metric: len(data) for metric, data in values["original"].items()},
                } for racer, values in sorted(by_player.items())
            },
        }
    return profiles


def predict_research(profile, record):
    """Per-venue observed course + player evidence; never call it a probability."""
    if profile["venue_code"] != record["venue_code"] or profile["trained_through"] > record["day"]:
        raise ValueError("Venue/date mismatch or future-trained profile")
    scored = []
    for row in record["rows"]:
        course = row["exhibition_course"]
        course_obs = profile["course_observations"].get(str(course), {})
        player_obs = profile["racer_observations"].get(row["racer_id"], {})
        cr = course_obs.get("observed_win_rate")
        pr = player_obs.get("observed_win_rate")
        # Fixed, explicitly uncalibrated research index; no optimistic fill on missing data.
        index = round(.75 * cr + .25 * pr, 4) if cr is not None and pr is not None else None
        scored.append({
            "lane": row["lane"], "racer_id": row["racer_id"],
            "research_index": index,
            "course_sample_size": course_obs.get("races", 0),
            "player_sample_size": player_obs.get("races", 0),
            "original_observed": row["original"] is not None,
            "original_used_in_score": False,
        })
    return {
        "race_id": record["race_id"], "venue_ai": profile["ai_name"],
        "model_date_cutoff": profile["trained_through"],
        "status": "research_rank_only" if any(x["research_index"] is not None for x in scored)
                  else "insufficient_verified_history",
        "not_calibrated_probability": True, "does_not_generate_bets": True,
        "boats": scored,
    }


def immutable_json(path, value):
    """Never overwrite a frozen race; re-run of identical content is idempotent."""
    path = Path(path)
    body = canonical(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(body)
        return True
    except FileExistsError:
        if path.read_bytes() != body:
            raise ValueError("Immutable archive conflict: " + str(path))
        return False


def build(official_dir, original_dir, output_dir, through):
    datetime.strptime(through, "%Y%m%d")
    records = build_records(official_dir, original_dir, through=through)
    out = Path(output_dir)
    statuses = defaultdict(int)
    players = defaultdict(list)
    for rec in records:
        immutable_json(out / "races" / rec["day"] / (rec["race_id"] + ".json"), rec)
        statuses[rec["original_status"]] += 1
        for row in rec["rows"]:
            players[(rec["venue_code"], row["racer_id"])].append({
                "race_id": rec["race_id"], "day": rec["day"], "lane": row["lane"],
                "exhibition_time": row["exhibition_time"], "original": row["original"],
                "original_status": rec["original_status"],
                "outcome": row["outcome"],
            })
    for (code, racer), rows in players.items():
        immutable_json(out / "players" / code / (racer + ".json"), {
            "venue_code": code, "racer_id": racer, "races": rows,
        })
    profiles = fit_venue_profiles(records, through)
    for code, profile in profiles.items():
        immutable_json(out / "models" / through / (code + ".json"), profile)
    summary = {
        "as_of": through, "all_24_models_created": len(profiles) == 24,
        "official_races_archived": len(records),
        "original_status_counts": dict(sorted(statuses.items())),
        "players_with_venue_history": len(players),
        "trained_only_before": through,
        "research_only": True,
        "original_source_verified_venues": sorted(ORIGINAL_SOURCES_VERIFIED),
        "original_absence_not_fabricated": True,
        "production_changed": False,
    }
    immutable_json(out / "reports" / through / "build.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description="24 venue independent research archive builder")
    parser.add_argument("--official-dir", type=Path, required=True)
    parser.add_argument("--original-dir", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--through", required=True, help="YYYYMMDD as-of date; train strictly before date")
    args = parser.parse_args()
    print(json.dumps(build(args.official_dir, args.original_dir, args.out, args.through), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
