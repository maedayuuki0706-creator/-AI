"""Live PT1-PT3 scoreboard for actually delivered Discord predictions.

Only predictions with a matching delivery receipt are counted. Official trifecta
results are fetched after the race, scored at a flat 100 yen per pick, and
persisted so hit rate / ROI can be read without rebuilding the whole day.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import json
from pathlib import Path

import daily_report
import direct_discord_notify as base
import four_way_prototype as trial

UNIT_YEN = 100
STREAMS = ("prototype1", "prototype2", "prototype3")
LABELS = {
    "prototype1": "PT1（PT3ベース・日和本線4点＋中穴迎え6点）",
    "prototype2": "PT2（PT3ベース・日和本線6点＋中穴迎え4点）",
    "prototype3": "新人予想家 ゆうき（日和本線＋中穴抑え）",
}
PT2_NEW_VERSION = "new-pt2-full-sheet-db-v2"
PT2_LEGACY_VERSION = "legacy-pt2-pre-full-db"
PT2_VERSION_LABELS = {
    PT2_LEGACY_VERSION: "旧PT2",
    PT2_NEW_VERSION: "新PT2",
}
PT2_ROLLOUT_COMMIT = "4a54ebb113ae8dbb938f9724d34290f0b0c249ba"
P12_ROOT = Path("data/prototype12_delivery")
P3_ROOT = Path("data/prototype3_delivery")
ROOT = Path("data/prototype_scoreboard")


def read_json(path: Path, default=None):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value
    except (OSError, ValueError):
        return default


def write_json_if_changed(path: Path, value) -> bool:
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)
    return True


def prediction_files(day: str, root: Path):
    folder = root / "predictions"
    return sorted(folder.glob(f"{day}_*.json")) if folder.exists() else []


def receipt_path(stream: str, key: str) -> Path:
    if stream == "prototype3":
        return P3_ROOT / "deliveries" / f"{key}.json"
    return P12_ROOT / "deliveries" / stream / f"{key}.json"


def matching_receipt(stream: str, key: str, digest: str):
    receipt = read_json(receipt_path(stream, key))
    if not isinstance(receipt, dict):
        return None
    if receipt.get("prediction_digest") != digest:
        return None
    return receipt


def collect_delivered(day: str):
    races = {}
    predicted = {stream: 0 for stream in STREAMS}
    delivered = {stream: 0 for stream in STREAMS}

    for path in prediction_files(day, P12_ROOT):
        record = read_json(path)
        if not isinstance(record, dict) or record.get("day") != day:
            continue
        key = record.get("key")
        digest = record.get("digest")
        models = record.get("models") or {}
        if not key or not digest:
            continue
        race = races.setdefault(key, {
            "key": key,
            "day": day,
            "jcd": str(record.get("jcd") or "").zfill(2),
            "rno": int(record.get("rno") or 0),
            "venue": record.get("venue"),
            "deadline": record.get("deadline"),
            "prediction_created_at": record.get("created_at"),
            "models": {},
            "receipts": {},
            "digests": {},
        })
        for stream in ("prototype1", "prototype2"):
            model = models.get(stream)
            if not isinstance(model, dict):
                continue
            predicted[stream] += 1
            receipt = matching_receipt(stream, key, digest)
            if receipt is None:
                continue
            delivered[stream] += 1
            race["models"][stream] = model
            race["receipts"][stream] = receipt
            race["digests"][stream] = digest

    for path in prediction_files(day, P3_ROOT):
        record = read_json(path)
        if not isinstance(record, dict) or record.get("day") != day:
            continue
        key = record.get("key")
        digest = record.get("digest")
        model = record.get("model")
        if not key or not digest or not isinstance(model, dict):
            continue
        predicted["prototype3"] += 1
        race = races.setdefault(key, {
            "key": key,
            "day": day,
            "jcd": str(record.get("jcd") or "").zfill(2),
            "rno": int(record.get("rno") or 0),
            "venue": record.get("venue"),
            "deadline": record.get("deadline"),
            "prediction_created_at": record.get("created_at"),
            "models": {},
            "receipts": {},
            "digests": {},
        })
        if not race.get("venue"):
            race["venue"] = record.get("venue")
        if not race.get("deadline"):
            race["deadline"] = record.get("deadline")
        receipt = matching_receipt("prototype3", key, digest)
        if receipt is None:
            continue
        delivered["prototype3"] += 1
        race["models"]["prototype3"] = model
        race["receipts"]["prototype3"] = receipt
        race["digests"]["prototype3"] = digest

    races = {key: race for key, race in races.items() if race["models"]}
    return races, predicted, delivered


def score_model(model: dict, result: dict) -> dict | None:
    status = result.get("status")
    if status not in {"settled", "void", "special"}:
        return None
    picks = []
    for pick in model.get("picks") or []:
        if pick in trial.COMBINATIONS and pick not in picks:
            picks.append(pick)
    if not picks:
        return None

    payouts = result.get("payouts") or {}
    refunds = set(map(int, result.get("refund_lanes") or []))
    active = []
    returned = 0
    refunded = 0
    for pick in picks:
        lanes = set(map(int, pick.split("-")))
        if status == "void" or lanes & refunds:
            returned += UNIT_YEN
            refunded += UNIT_YEN
        elif status == "special":
            returned += int(result.get("special_per_100") or 0)
        else:
            active.append(pick)
            returned += int(payouts.get(pick, 0) or 0)

    winning = [pick for pick in active if int(payouts.get(pick, 0) or 0) > 0]
    stake = len(picks) * UNIT_YEN
    main = set(model.get("main_picks") or [])
    cover = set(model.get("cover_picks") or [])
    return {
        "eligible": status == "settled" and bool(active),
        "hit": bool(winning),
        "winning_picks": winning,
        "main_hit": any(pick in main for pick in winning),
        "cover_hit": any(pick in cover for pick in winning),
        "point_count": len(picks),
        "stake_yen": stake,
        "return_yen": returned,
        "refund_yen": refunded,
        "profit_yen": returned - stake,
        "roi": 100 * returned / stake if stake else None,
        "manshu": any(int(payouts.get(pick, 0) or 0) >= 10000 for pick in winning),
        "torigami": bool(winning) and returned < stake,
    }


def result_cache_path(day: str, key: str) -> Path:
    return ROOT / day / "official" / f"{key}.json"


def fetch_official(day: str, race: dict, refresh_settled: bool = False):
    cache = result_cache_path(day, race["key"])
    saved = read_json(cache)
    if isinstance(saved, dict) and saved.get("status") in {"settled", "void", "special"} and not refresh_settled:
        return saved

    deadline = race.get("deadline")
    if not deadline:
        return None
    try:
        close = trial.close_time(day, deadline)
    except (TypeError, ValueError):
        return None
    if datetime.now(base.JST) < close:
        return None

    url = base.official_url("raceresult", day, race["jcd"], race["rno"])
    try:
        parsed = daily_report.parse_payout(base.fetch(url))
    except Exception as exc:
        print(f"official pending {race['key']}: {type(exc).__name__}", flush=True)
        return None
    if parsed.get("status") == "pending":
        return None

    value = {
        **parsed,
        "source_url": url,
        "checked_at": datetime.now(base.JST).isoformat(),
    }
    write_json_if_changed(cache, value)
    return value


def score_race(day: str, race: dict, result: dict):
    models = {}
    model_metadata = {}
    for stream, model in race["models"].items():
        score = score_model(model, result)
        if score is not None:
            models[stream] = score
            if stream == "prototype2":
                db = model.get("database") or {}
                model_metadata[stream] = {
                    "model_version": model.get("model_version") or PT2_LEGACY_VERSION,
                    "version_label": model.get("version_label") or PT2_VERSION_LABELS[PT2_LEGACY_VERSION],
                    "rollout_commit": model.get("rollout_commit"),
                    "db_snapshot_at": db.get("snapshot_at"),
                    "db_schema_version": db.get("schema_version"),
                    "db_player_matches": db.get("player_matches"),
                    "db_motor_matches": db.get("motor_matches"),
                    "db_enabled": bool(db.get("enabled")),
                }
    if not models:
        return None
    return {
        "key": race["key"],
        "day": day,
        "jcd": race["jcd"],
        "rno": race["rno"],
        "venue": race.get("venue"),
        "deadline": race.get("deadline"),
        "prediction_created_at": race.get("prediction_created_at"),
        "prediction_digests": race["digests"],
        "delivered_at": {
            stream: receipt.get("delivered_at")
            for stream, receipt in race["receipts"].items()
        },
        "model_metadata": model_metadata,
        "official": result,
        "models": models,
    }


def aggregate(rows):
    resolved = [row for row in rows if row]
    judged = [row for row in resolved if row.get("eligible")]
    hits = sum(bool(row.get("hit")) for row in judged)
    stake = sum(int(row.get("stake_yen") or 0) for row in resolved)
    returned = sum(int(row.get("return_yen") or 0) for row in resolved)
    return {
        "resolved": len(resolved),
        "judged": len(judged),
        "hits": hits,
        "hit_rate": 100 * hits / len(judged) if judged else None,
        "stake_yen": stake,
        "return_yen": returned,
        "profit_yen": returned - stake,
        "roi": 100 * returned / stake if stake else None,
        "manshu": sum(bool(row.get("manshu")) for row in judged),
        "torigami": sum(bool(row.get("torigami")) for row in judged),
        "main_hits": sum(bool(row.get("main_hit")) for row in judged),
        "cover_hits": sum(bool(row.get("cover_hit")) for row in judged),
        "avg_points": (
            sum(int(row.get("point_count") or 0) for row in resolved) / len(resolved)
            if resolved else None
        ),
    }


def build_summary(day: str, races: dict, predicted: dict, delivered: dict):
    result_dir = ROOT / day / "results"
    result_rows = []
    if result_dir.exists():
        for path in sorted(result_dir.glob("*.json")):
            row = read_json(path)
            if isinstance(row, dict):
                result_rows.append(row)

    totals = {}
    by_venue = {}
    for stream in STREAMS:
        scores = [row["models"][stream] for row in result_rows if stream in (row.get("models") or {})]
        stats = aggregate(scores)
        stats.update({
            "label": LABELS[stream],
            "predicted": predicted[stream],
            "delivered": delivered[stream],
            "pending": max(0, delivered[stream] - stats["resolved"]),
        })
        totals[stream] = stats

    venues = sorted({row.get("venue") for row in result_rows if row.get("venue")})
    for venue in venues:
        venue_rows = [row for row in result_rows if row.get("venue") == venue]
        by_venue[venue] = {}
        for stream in STREAMS:
            by_venue[venue][stream] = aggregate([
                row["models"][stream] for row in venue_rows if stream in (row.get("models") or {})
            ])

    common_rows = [
        row for row in result_rows
        if all(stream in (row.get("models") or {}) and row["models"][stream].get("eligible")
               for stream in STREAMS)
    ]
    common_totals = {
        stream: aggregate([row["models"][stream] for row in common_rows])
        for stream in STREAMS
    }
    pairs = {}
    for i, a in enumerate(STREAMS):
        for b in STREAMS[i + 1:]:
            pairs[f"{a}_vs_{b}"] = {
                "both": sum(row["models"][a]["hit"] and row["models"][b]["hit"] for row in common_rows),
                "a_only": [row["key"] for row in common_rows
                           if row["models"][a]["hit"] and not row["models"][b]["hit"]],
                "b_only": [row["key"] for row in common_rows
                           if row["models"][b]["hit"] and not row["models"][a]["hit"]],
                "neither": sum(not row["models"][a]["hit"] and not row["models"][b]["hit"]
                               for row in common_rows),
            }

    pt2_delivery_rows = []
    for race in races.values():
        model = (race.get("models") or {}).get("prototype2")
        receipt = (race.get("receipts") or {}).get("prototype2")
        if not isinstance(model, dict) or not isinstance(receipt, dict):
            continue
        version = model.get("model_version") or PT2_LEGACY_VERSION
        pt2_delivery_rows.append({
            "version": version,
            "version_label": model.get("version_label") or PT2_VERSION_LABELS.get(version, version),
            "key": race.get("key"),
            "venue": race.get("venue"),
            "rno": race.get("rno"),
            "prediction_created_at": race.get("prediction_created_at"),
            "delivered_at": receipt.get("delivered_at"),
            "db_snapshot_at": (model.get("database") or {}).get("snapshot_at"),
        })

    pt2_versions = {}
    versions = sorted({
        row["version"] for row in pt2_delivery_rows
    } | {
        ((row.get("model_metadata") or {}).get("prototype2") or {}).get("model_version", PT2_LEGACY_VERSION)
        for row in result_rows
        if "prototype2" in (row.get("models") or {})
    })
    for version in versions:
        version_scores = [
            row["models"]["prototype2"]
            for row in result_rows
            if "prototype2" in (row.get("models") or {})
            and (((row.get("model_metadata") or {}).get("prototype2") or {}).get("model_version")
                 or PT2_LEGACY_VERSION) == version
        ]
        stats = aggregate(version_scores)
        delivered_rows = [row for row in pt2_delivery_rows if row["version"] == version]
        delivered_rows.sort(key=lambda row: str(row.get("delivered_at") or ""))
        stats.update({
            "label": PT2_VERSION_LABELS.get(version, delivered_rows[0]["version_label"] if delivered_rows else version),
            "model_version": version,
            "delivered": len(delivered_rows),
            "pending": max(0, len(delivered_rows) - stats["resolved"]),
            "first_delivery": delivered_rows[0] if delivered_rows else None,
            "last_delivery": delivered_rows[-1] if delivered_rows else None,
        })
        pt2_versions[version] = stats

    new_stats = pt2_versions.get(PT2_NEW_VERSION) or {}
    old_stats = pt2_versions.get(PT2_LEGACY_VERSION) or {}
    pt2_comparison = {
        "baseline_version": PT2_LEGACY_VERSION,
        "new_version": PT2_NEW_VERSION,
        "rollout_commit": PT2_ROLLOUT_COMMIT,
        "first_new_delivery": new_stats.get("first_delivery"),
        "versions": pt2_versions,
        "delta_new_minus_old": {
            "hit_rate_points": (
                new_stats["hit_rate"] - old_stats["hit_rate"]
                if new_stats.get("hit_rate") is not None and old_stats.get("hit_rate") is not None
                else None
            ),
            "roi_points": (
                new_stats["roi"] - old_stats["roi"]
                if new_stats.get("roi") is not None and old_stats.get("roi") is not None
                else None
            ),
            "avg_points": (
                new_stats["avg_points"] - old_stats["avg_points"]
                if new_stats.get("avg_points") is not None and old_stats.get("avg_points") is not None
                else None
            ),
        },
    }

    latest_checked = max(
        (str((row.get("official") or {}).get("checked_at") or "") for row in result_rows),
        default="",
    ) or None
    return {
        "day": day,
        "unit_yen": UNIT_YEN,
        "mode": "delivered_predictions_flat_100",
        "point_policy": {
            "prototype1": "10点（日和本線4＋中穴迎え6）",
            "prototype2": "10点（日和本線6＋中穴迎え4）",
            "prototype3": "日和本線＋中穴抑え・可変点数",
        },
        "updated_at": latest_checked,
        "race_keys_with_any_delivery": len(races),
        "totals": totals,
        "pt2_version_comparison": pt2_comparison,
        "common_cohort": {
            "judged_races": len(common_rows),
            "keys": [row["key"] for row in common_rows],
            "totals": common_totals,
            "pairs": pairs,
        },
        "by_venue": by_venue,
    }


def run(day: str, refresh_settled: bool = False, max_workers: int = 8):
    datetime.strptime(day, "%Y%m%d")
    base.fetch.cache_clear()
    races, predicted, delivered = collect_delivered(day)

    due = list(races.values())
    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        jobs = {
            pool.submit(fetch_official, day, race, refresh_settled): race
            for race in due
        }
        for future in as_completed(jobs):
            race = jobs[future]
            try:
                official = future.result()
            except Exception as exc:
                print(f"scoreboard result pending {race['key']}: {type(exc).__name__}", flush=True)
                continue
            if not official:
                continue
            row = score_race(day, race, official)
            if row:
                write_json_if_changed(ROOT / day / "results" / f"{race['key']}.json", row)

    summary = build_summary(day, races, predicted, delivered)
    write_json_if_changed(ROOT / day / "summary.json", summary)
    write_json_if_changed(ROOT / "latest.json", summary)

    compact = []
    for stream in STREAMS:
        stats = summary["totals"][stream]
        hit = "—" if stats["hit_rate"] is None else f"{stats['hit_rate']:.1f}%"
        roi = "—" if stats["roi"] is None else f"{stats['roi']:.1f}%"
        compact.append(
            f"{stream}: {stats['hits']}/{stats['judged']} hit={hit} roi={roi} "
            f"delivered={stats['delivered']} pending={stats['pending']}"
        )
    print(" | ".join(compact), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--day")
    parser.add_argument("--refresh-settled", action="store_true")
    parser.add_argument("--max-workers", type=int, default=8)
    args = parser.parse_args()
    now = datetime.now(base.JST)
    target = now - timedelta(days=1) if now.hour < 6 else now
    day = args.day or target.strftime("%Y%m%d")
    run(day, args.refresh_settled, args.max_workers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
