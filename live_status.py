"""Build a live, comparable scoreboard for every active prediction stream.

The file data/live_status/latest.json is the single fast-read source for
"今どう？". Only actually delivered predictions are counted. Metrics use a
common flat 100 yen per disclosed pick so streams can be compared fairly.
Pending races never enter hit-rate or ROI denominators.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import json
from pathlib import Path
import re

import daily_report
import direct_discord_notify as base
import prototype_scoreboard
from selected_metrics import selected_record

ROOT = Path("data/live_status")
OFFICIAL_DIR = ROOT / "official"
UNIT_YEN = 100

LABELS = {
    "main": "メイン",
    "mid_odds": "中穴",
    "longshot": "穴",
    "selected": "厳選くん",
    "hiyori": "日和",
    "prototype1": "PT1",
    "prototype2": "PT2",
    "prototype3": "PT3",
}


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def read_jsonl(path: Path):
    rows = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    except OSError:
        pass
    return rows


def write_json_if_changed(path: Path, value) -> bool:
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return True


def race_key(jcd, rno) -> str:
    return f"{str(jcd).zfill(2)}:{int(rno)}"


def valid_pick(value) -> bool:
    return bool(re.fullmatch(r"[1-6]-[1-6]-[1-6]", str(value or ""))) and len(set(str(value).split("-"))) == 3


def unique_picks(values):
    out = []
    seen = set()
    for value in values or []:
        pick = str(value or "").strip()
        if valid_pick(pick) and pick not in seen:
            seen.add(pick)
            out.append(pick)
    return out


def base_streams(day: str):
    predictions = daily_report.read_jsonl(Path("data/prediction_log.jsonl"))
    latest, _ = daily_report.latest_predictions(predictions, day)

    main = {}
    selected = {}
    for key, row in latest.items():
        picks = unique_picks(daily_report.disclosed_picks(row))
        if not picks:
            continue
        item = {
            "key": key,
            "day": day,
            "jcd": str(row.get("jcd") or "").zfill(2),
            "rno": int(row.get("rno") or 0),
            "venue": row.get("venue"),
            "deadline": row.get("deadline"),
            "picks": picks,
        }
        main[key] = item
        if selected_record(row, 75):
            selected[key] = {**item, "selection_score": int(row.get("selection_score") or 0)}
    return main, selected


def opportunity_streams(day: str):
    rows = read_jsonl(Path("data/opportunity_alert_deliveries.jsonl"))
    chosen = {"mid_odds": {}, "longshot": {}}
    for row in rows:
        if str(row.get("day") or "") != day:
            continue
        stream = str(row.get("stream") or "")
        if stream not in chosen:
            continue
        # Longshot sniper skips are journal-only and were never sent to Discord.
        if row.get("status") == "sniper_skip" or not row.get("delivery_env"):
            continue
        jcd = str(row.get("jcd") or "").zfill(2)
        try:
            rno = int(row.get("rno") or 0)
        except (TypeError, ValueError):
            continue
        if not re.fullmatch(r"\d{2}", jcd) or not 1 <= rno <= 12:
            continue
        picks = unique_picks(
            item.get("combination")
            for item in (row.get("picks") or [])
            if isinstance(item, dict)
        )
        if not picks:
            continue
        key = race_key(jcd, rno)
        item = {
            "key": key,
            "day": day,
            "jcd": jcd,
            "rno": rno,
            "venue": row.get("venue"),
            "deadline": row.get("deadline"),
            "picks": picks,
            "sent_at": row.get("sent_at"),
        }
        old = chosen[stream].get(key)
        if old is None or str(item.get("sent_at") or "") >= str(old.get("sent_at") or ""):
            chosen[stream][key] = item
    return chosen


def hiyori_stream(day: str):
    out = {}
    folder = Path("data/hiyori/deliveries")
    if not folder.exists():
        return out
    for path in sorted(folder.glob(f"{day}_*.json")):
        row = read_json(path)
        if not isinstance(row, dict) or str(row.get("day") or "") != day:
            continue
        jcd = str(row.get("jcd") or "").zfill(2)
        try:
            rno = int(row.get("rno") or 0)
        except (TypeError, ValueError):
            continue
        picks = unique_picks(row.get("all_picks") or [])
        if not picks:
            continue
        key = race_key(jcd, rno)
        out[key] = {
            "key": key,
            "day": day,
            "jcd": jcd,
            "rno": rno,
            "venue": row.get("venue") or base.VENUES.get(jcd),
            "deadline": row.get("deadline"),
            "picks": picks,
            "sent_at": row.get("sent_at"),
        }
    return out


def prototype_streams(day: str):
    races, _predicted, _delivered = prototype_scoreboard.collect_delivered(day)
    out = {"prototype1": {}, "prototype2": {}, "prototype3": {}}
    for key, race in races.items():
        for stream, model in (race.get("models") or {}).items():
            if stream not in out or not isinstance(model, dict):
                continue
            picks = unique_picks(model.get("picks") or [])
            if not picks:
                continue
            out[stream][key] = {
                "key": key,
                "day": day,
                "jcd": str(race.get("jcd") or "").zfill(2),
                "rno": int(race.get("rno") or 0),
                "venue": race.get("venue"),
                "deadline": race.get("deadline"),
                "picks": picks,
                "sent_at": (race.get("receipts") or {}).get(stream, {}).get("delivered_at"),
            }
    return out


def parse_close(day: str, deadline):
    try:
        return datetime.strptime(f"{day} {deadline}", "%Y%m%d %H:%M").replace(tzinfo=base.JST)
    except (TypeError, ValueError):
        return None


def load_official_cache(day: str):
    value = read_json(OFFICIAL_DIR / f"{day}.json", {})
    return value if isinstance(value, dict) else {}


def refresh_official(day: str, streams: dict[str, dict]):
    cache = load_official_cache(day)
    now = datetime.now(base.JST)
    races = {}
    for records in streams.values():
        for key, row in records.items():
            races.setdefault(key, row)

    base.fetch.cache_clear()
    changed = False
    due = {}
    for key, row in sorted(races.items()):
        saved = cache.get(key)
        if isinstance(saved, dict) and saved.get("status") in {"settled", "void", "special"}:
            continue
        close = parse_close(day, row.get("deadline"))
        if close is not None and now < close:
            continue
        due[key] = row

    def fetch_one(item):
        key, row = item
        url = base.official_url("raceresult", day, row["jcd"], row["rno"])
        try:
            raw = base.fetch(url)
            result = daily_report.parse_payout(raw)
        except Exception as exc:
            result = {
                "status": "pending",
                "payouts": {},
                "refund_lanes": [],
                "error_type": type(exc).__name__,
            }
        return key, url, result

    with ThreadPoolExecutor(max_workers=16) as pool:
        jobs = [pool.submit(fetch_one, item) for item in due.items()]
        for future in as_completed(jobs):
            key, url, result = future.result()
            if result.get("status") == "pending":
                continue
            cache[key] = {
                **result,
                "checked_at": now.isoformat(),
                "source_url": url,
            }
            changed = True

    if changed or not (OFFICIAL_DIR / f"{day}.json").exists():
        write_json_if_changed(OFFICIAL_DIR / f"{day}.json", cache)
    return cache


def score_one(record: dict, official: dict | None):
    if not isinstance(official, dict):
        return None
    status = official.get("status")
    if status not in {"settled", "void", "special"}:
        return None

    picks = unique_picks(record.get("picks") or [])
    if not picks:
        return None

    payouts = official.get("payouts") or {}
    refunds = set(map(int, official.get("refund_lanes") or []))
    returned = 0
    active = []
    for pick in picks:
        lanes = set(map(int, pick.split("-")))
        if status == "void" or lanes & refunds:
            returned += UNIT_YEN
        elif status == "special":
            returned += int(official.get("special_per_100") or 0)
        else:
            active.append(pick)
            returned += int(payouts.get(pick, 0) or 0)

    winning = [pick for pick in active if int(payouts.get(pick, 0) or 0) > 0]
    stake = len(picks) * UNIT_YEN
    return {
        "status": status,
        "eligible": status == "settled" and bool(active),
        "hit": bool(winning),
        "winning_picks": winning,
        "point_count": len(picks),
        "stake_yen": stake,
        "return_yen": returned,
        "profit_yen": returned - stake,
        "manshu": any(int(payouts.get(pick, 0) or 0) >= 10000 for pick in winning),
        "torigami": bool(winning) and returned < stake,
    }


def aggregate(stream: str, records: dict, official: dict):
    scored = []
    hit_races = []
    for key, record in sorted(records.items()):
        score = score_one(record, official.get(key))
        if score is None:
            continue
        scored.append(score)
        if score["hit"]:
            hit_races.append({
                "key": key,
                "venue": record.get("venue"),
                "rno": record.get("rno"),
                "winning_picks": score["winning_picks"],
                "return_yen": score["return_yen"],
                "stake_yen": score["stake_yen"],
            })

    judged = [row for row in scored if row["eligible"]]
    hits = sum(bool(row["hit"]) for row in judged)
    stake = sum(int(row["stake_yen"]) for row in scored)
    returned = sum(int(row["return_yen"]) for row in scored)
    delivered = len(records)
    resolved = len(scored)
    return {
        "label": LABELS[stream],
        "delivered": delivered,
        "resolved": resolved,
        "pending": max(0, delivered - resolved),
        "judged": len(judged),
        "hits": hits,
        "hit_rate": 100 * hits / len(judged) if judged else None,
        "stake_yen": stake,
        "return_yen": returned,
        "profit_yen": returned - stake,
        "roi": 100 * returned / stake if stake else None,
        "manshu": sum(bool(row["manshu"]) for row in judged),
        "torigami": sum(bool(row["torigami"]) for row in judged),
        "avg_points": (
            sum(int(row["point_count"]) for row in scored) / len(scored)
            if scored else None
        ),
        "hit_races": hit_races,
    }


def build(day: str):
    datetime.strptime(day, "%Y%m%d")

    main, selected = base_streams(day)
    opportunity = opportunity_streams(day)
    prototypes = prototype_streams(day)
    streams = {
        "main": main,
        "mid_odds": opportunity["mid_odds"],
        "longshot": opportunity["longshot"],
        "selected": selected,
        "hiyori": hiyori_stream(day),
        "prototype1": prototypes["prototype1"],
        "prototype2": prototypes["prototype2"],
        "prototype3": prototypes["prototype3"],
    }

    official = refresh_official(day, streams)
    metrics = {name: aggregate(name, records, official) for name, records in streams.items()}

    venues = {}
    venue_names = sorted({
        str(record.get("venue") or base.VENUES.get(str(record.get("jcd") or "").zfill(2)) or "")
        for records in streams.values()
        for record in records.values()
        if record.get("venue") or record.get("jcd")
    })
    for venue in venue_names:
        if not venue:
            continue
        venues[venue] = {}
        for name, records in streams.items():
            subset = {
                key: record for key, record in records.items()
                if str(record.get("venue") or base.VENUES.get(str(record.get("jcd") or "").zfill(2)) or "") == venue
            }
            venues[venue][name] = aggregate(name, subset, official)

    generated_at = datetime.now(base.JST).isoformat()
    result = {
        "ok": True,
        "day": day,
        "generated_at": generated_at,
        "basis": "delivered predictions only; flat 100 yen per disclosed pick; pending excluded",
        "unit_yen": UNIT_YEN,
        "streams": metrics,
        "venues": venues,
        "totals": {
            "stream_count": len(metrics),
            "delivered": sum(item["delivered"] for item in metrics.values()),
            "resolved": sum(item["resolved"] for item in metrics.values()),
            "pending": sum(item["pending"] for item in metrics.values()),
        },
    }
    write_json_if_changed(ROOT / f"{day}.json", result)
    write_json_if_changed(ROOT / "latest.json", result)

    compact = []
    for name in ("main", "mid_odds", "longshot", "selected", "hiyori", "prototype1", "prototype2", "prototype3"):
        item = metrics[name]
        hit = "—" if item["hit_rate"] is None else f"{item['hit_rate']:.1f}%"
        roi = "—" if item["roi"] is None else f"{item['roi']:.1f}%"
        compact.append(
            f"{LABELS[name]} {item['hits']}/{item['judged']} hit={hit} roi={roi} "
            f"resolved={item['resolved']} pending={item['pending']}"
        )
    print(" | ".join(compact), flush=True)
    return result


def default_day():
    now = datetime.now(base.JST)
    if now.hour < 6:
        now -= timedelta(days=1)
    return now.strftime("%Y%m%d")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", default=default_day())
    args = parser.parse_args()
    build(args.day)
