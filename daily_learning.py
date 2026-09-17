"""Compare logged predictions with official BOAT RACE results and update learning stats."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from race_context import clean
from daily_report import latest_predictions, RESULT_DIR, race_key

JST = ZoneInfo("Asia/Tokyo")
BASE = "https://www.boatrace.jp/owpc/pc/race"
UA = "Boat-AI-Navi-Learner/1.1"
LOG_PATH = Path("data/prediction_log.jsonl")
RESULTS_PATH = Path("data/evaluated_results.jsonl")
STATE_PATH = Path("data/learning_state.json")


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja-JP,ja;q=0.9"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", errors="replace")


def official_result_url(day: str, jcd: str, rno: int) -> str:
    q = urllib.parse.urlencode({"hd": day, "jcd": jcd, "rno": str(rno)})
    return f"{BASE}/raceresult?{q}"


def parse_finish_order(raw: str) -> list[int]:
    # Official result pages include lane numbers next to 1st/2nd/3rd finish rows.
    text = clean(raw)
    patterns = [
        r"1着\s*([1-6]).{0,120}?2着\s*([1-6]).{0,120}?3着\s*([1-6])",
        r"着順.{0,300}?\b1\b\s+([1-6]).{0,120}?\b2\b\s+([1-6]).{0,120}?\b3\b\s+([1-6])",
    ]
    for pat in patterns:
        m = re.search(pat, text, flags=re.S)
        if m:
            order = [int(m.group(1)), int(m.group(2)), int(m.group(3))]
            if len(set(order)) == 3:
                return order
    # Fallback: find a compact official 3連単 result such as 1-3-4 near the payout label.
    m = re.search(r"3連単.{0,100}?([1-6])\s*[-－]\s*([1-6])\s*[-－]\s*([1-6])", text, flags=re.S)
    if m:
        order = [int(m.group(1)), int(m.group(2)), int(m.group(3))]
        if len(set(order)) == 3:
            return order
    return []


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
        except Exception:
            pass
    return rows


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _parse_pick(pick: object) -> tuple[int, int, int] | None:
    if not isinstance(pick, str) or not re.fullmatch(r"[1-6]-[1-6]-[1-6]", pick):
        return None
    values = tuple(int(x) for x in pick.split("-"))
    if len(set(values)) != 3:
        return None
    return values


def _near_miss_metrics(all_picks: list[str], result: list[int]) -> dict:
    actual = tuple(result)
    parsed = [p for p in (_parse_pick(pick) for pick in all_picks) if p is not None]
    if not parsed:
        return {
            "first_position_covered": False,
            "second_position_covered": False,
            "third_position_covered": False,
            "ordered_top2_hit": False,
            "same_three_set_hit": False,
            "one_slot_away": False,
            "same_three_wrong_order": False,
            "bridge_rescuable": False,
            "max_position_matches": 0,
            "near_miss_type": "no_valid_picks",
        }

    first_position_covered = any(p[0] == actual[0] for p in parsed)
    second_position_covered = any(p[1] == actual[1] for p in parsed)
    third_position_covered = any(p[2] == actual[2] for p in parsed)
    ordered_top2_hit = any(p[:2] == actual[:2] for p in parsed)
    same_three_set_hit = any(set(p) == set(actual) for p in parsed)
    max_position_matches = max(sum(p[i] == actual[i] for i in range(3)) for p in parsed)
    exact_hit = actual in parsed
    one_slot_away = (not exact_hit) and max_position_matches == 2
    same_three_wrong_order = (not exact_hit) and same_three_set_hit
    bridge_rescuable = one_slot_away or same_three_wrong_order

    if exact_hit:
        near_miss_type = "hit"
    elif same_three_wrong_order:
        near_miss_type = "same_three_boats_wrong_order"
    elif ordered_top2_hit:
        near_miss_type = "ordered_top2_third_miss"
    elif one_slot_away:
        near_miss_type = "two_positions_match"
    elif max_position_matches == 1:
        near_miss_type = "one_position_match"
    else:
        near_miss_type = "other_miss"

    return {
        "first_position_covered": first_position_covered,
        "second_position_covered": second_position_covered,
        "third_position_covered": third_position_covered,
        "ordered_top2_hit": ordered_top2_hit,
        "same_three_set_hit": same_three_set_hit,
        "one_slot_away": one_slot_away,
        "same_three_wrong_order": same_three_wrong_order,
        "bridge_rescuable": bridge_rescuable,
        "max_position_matches": max_position_matches,
        "near_miss_type": near_miss_type,
    }


def evaluate_prediction(row: dict, result: list[int]) -> dict:
    combo = "-".join(map(str, result))
    main = row.get("main") or []
    cover = row.get("cover") or []
    # Only combinations actually displayed in Discord count as delivered picks.
    all_picks = list(dict.fromkeys(main + cover + (row.get("outsiders") or [])))
    top_pick = all_picks[0] if all_picks else None
    top_first = int(top_pick.split("-")[0]) if isinstance(top_pick, str) and re.match(r"^[1-6]-", top_pick) else None
    miss_metrics = _near_miss_metrics(all_picks, result)
    return {
        **row,
        "result": combo,
        "main_hit": combo in main,
        "cover_hit": combo in cover,
        "any_hit": combo in all_picks,
        "winner_read_hit": top_first == result[0] if top_first else False,
        **miss_metrics,
        "evaluated_at": datetime.now(JST).isoformat(),
    }


def _rate(rows: list[dict], key: str) -> float:
    return round(sum(bool(r.get(key)) for r in rows) / len(rows), 4) if rows else 0.0


def _group_metrics(grp: list[dict]) -> dict:
    n = len(grp)
    misses = [r for r in grp if not r.get("any_hit")]
    bridge_misses = sum(bool(r.get("bridge_rescuable")) for r in misses)
    return {
        "samples": n,
        "main_hit_rate": _rate(grp, "main_hit"),
        "any_hit_rate": _rate(grp, "any_hit"),
        "winner_read_rate": _rate(grp, "winner_read_hit"),
        "first_position_coverage_rate": _rate(grp, "first_position_covered"),
        "second_position_coverage_rate": _rate(grp, "second_position_covered"),
        "third_position_coverage_rate": _rate(grp, "third_position_covered"),
        "ordered_top2_rate": _rate(grp, "ordered_top2_hit"),
        "same_three_set_rate": _rate(grp, "same_three_set_hit"),
        "bridge_rescuable_misses": bridge_misses,
        "bridge_rescue_rate_of_misses": round(bridge_misses / len(misses), 4) if misses else 0.0,
        "one_slot_away_misses": sum(bool(r.get("one_slot_away")) for r in misses),
        "same_three_wrong_order_misses": sum(bool(r.get("same_three_wrong_order")) for r in misses),
    }


def aggregate(rows: list[dict]) -> dict:
    # Morning and final updates are one race, not two independent observations.
    latest = {}
    for row in rows:
        key = (row.get("day"), row.get("jcd"), row.get("rno"))
        candidate_rank = (row.get("sent_at", ""), row.get("phase", "final") == "final")
        current = latest.get(key)
        current_rank = (
            (current.get("sent_at", ""), current.get("phase", "final") == "final")
            if current else ("", False)
        )
        if current is None or candidate_rank >= current_rank:
            latest[key] = row
    rows = list(latest.values())

    misses = [r for r in rows if not r.get("any_hit")]
    overall = {
        "main_hits": sum(bool(r.get("main_hit")) for r in rows),
        "cover_hits": sum(bool(r.get("cover_hit")) for r in rows),
        "any_hits": sum(bool(r.get("any_hit")) for r in rows),
        "winner_read_hits": sum(bool(r.get("winner_read_hit")) for r in rows),
        **_group_metrics(rows),
    }

    state = {
        "updated_at": datetime.now(JST).isoformat(),
        "learning_version": "near-miss-v2",
        "samples": len(rows),
        "overall": overall,
        "by_source": {},
        "by_venue": {},
        "by_grade": {},
        "by_point_count": {},
        "by_day": {},
        "near_miss_types": dict(sorted(
            (
                name,
                sum(1 for r in misses if r.get("near_miss_type") == name),
            )
            for name in {str(r.get("near_miss_type") or "unknown") for r in misses}
        )),
        "guidance": {
            "minimum_samples_before_weight_change": 50,
            "minimum_group_samples_before_weight_change": 30,
            "rule": (
                "Record result structure separately from exact hits. Prefer reducing one-slot-away "
                "and same-three-boats wrong-order misses before widening point counts. Do not change "
                "venue/model weights from one day or a small group."
            ),
            "bridge_policy": (
                "A bridge miss means the delivered picks were one position away from the result or "
                "already contained the same three boats in a different order. Use this for conservative "
                "cover reallocation, not unlimited point expansion."
            ),
        },
    }

    for key, target in (
        ("source", "by_source"),
        ("venue", "by_venue"),
        ("grade", "by_grade"),
        ("point_count", "by_point_count"),
        ("day", "by_day"),
    ):
        groups = defaultdict(list)
        for r in rows:
            groups[str(r.get(key) if r.get(key) is not None else "unknown")].append(r)
        for name, grp in groups.items():
            state[target][name] = _group_metrics(grp)

    return state


def main() -> int:
    predictions = load_jsonl(LOG_PATH)
    evaluated = []
    previous = {(r.get("day"), race_key(r), r.get("sent_at")): r for r in load_jsonl(RESULTS_PATH)}
    for day in sorted({r.get("day") for r in predictions if r.get("day")}):
        chosen, _ = latest_predictions(predictions, day)
        path = RESULT_DIR / f"{day}.json"
        official = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        for key, row in chosen.items():
            result = official.get(key, {})
            combos = list(result.get("payouts", {})) if result.get("status") == "settled" else []
            # A dead heat has multiple winning combinations. Keep the observation
            # that best matches the delivered pre-close prediction.
            if combos:
                observations = [evaluate_prediction(row, list(map(int, combo.split("-")))) for combo in combos]
                record = max(
                    observations,
                    key=lambda x: (
                        bool(x.get("any_hit")),
                        int(x.get("max_position_matches") or 0),
                        bool(x.get("same_three_set_hit")),
                    ),
                )
                record["official_results"] = combos
                evaluated.append(record)
            elif not result and (day, key, row.get("sent_at")) in previous:
                evaluated.append(previous[(day, key, row.get("sent_at"))])
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in evaluated),
        encoding="utf-8",
    )
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(aggregate(evaluated), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"daily learning complete: independent_pre_close_races={len(evaluated)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
