"""Unified historical learner for every active BOAT RACE prediction stream.

This job backfills only races that were actually delivered and already have an
official settled result in the local cache. It turns historical logs into a
shared evidence layer for every AI stream.

Important safety rule:
- collect and score evidence automatically
- recommend changes only after sample-size gates
- never mutate live model weights from this job
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import live_status

JST = ZoneInfo("Asia/Tokyo")
OUT = Path("data/all_ai_learning")
OBS_PATH = OUT / "observations.jsonl"
STATE_PATH = OUT / "state.json"
RECOMMENDATION_PATH = OUT / "recommendation.json"

STREAMS = tuple(live_status.LABELS)
MIN_GLOBAL_SAMPLES = 50
MIN_VENUE_SAMPLES = 24
MIN_BAND_SAMPLES = 30
MIN_DAYS = 3


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        if path.read_text(encoding="utf-8") == text:
            return
    except OSError:
        pass
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _valid_combo(value) -> bool:
    return live_status.valid_pick(value)


def _parts(value):
    if not _valid_combo(value):
        return None
    return tuple(int(x) for x in str(value).split("-"))


def _winning_combos(official: dict) -> list[str]:
    if not isinstance(official, dict) or official.get("status") != "settled":
        return []
    out = []
    for combo, payout in (official.get("payouts") or {}).items():
        try:
            amount = int(payout or 0)
        except (TypeError, ValueError):
            amount = 0
        if amount > 0 and _valid_combo(combo):
            out.append(str(combo))
    return sorted(set(out))


def _structure_metrics(picks: list[str], winner: str) -> dict:
    actual = _parts(winner)
    parsed = [p for p in (_parts(x) for x in picks) if p is not None]
    if actual is None or not parsed:
        return {
            "exact_hit": False,
            "head_covered": False,
            "second_position_covered": False,
            "third_position_covered": False,
            "ordered_top2_hit": False,
            "same_three_set_hit": False,
            "max_position_matches": 0,
            "miss_type": "no_valid_picks",
        }

    exact = actual in parsed
    head = any(p[0] == actual[0] for p in parsed)
    second = any(p[1] == actual[1] for p in parsed)
    third = any(p[2] == actual[2] for p in parsed)
    ordered_top2 = any(p[:2] == actual[:2] for p in parsed)
    same_three = any(set(p) == set(actual) for p in parsed)
    max_matches = max(sum(p[i] == actual[i] for i in range(3)) for p in parsed)

    if exact:
        miss_type = "hit"
    elif same_three:
        miss_type = "same_three_wrong_order"
    elif ordered_top2:
        miss_type = "ordered_top2_third_miss"
    elif head and max_matches >= 2:
        miss_type = "head_right_one_slot_miss"
    elif head:
        miss_type = "head_right_tail_miss"
    elif max_matches >= 2:
        miss_type = "two_positions_match_head_miss"
    elif max_matches == 1:
        miss_type = "one_position_match"
    else:
        miss_type = "full_miss"

    return {
        "exact_hit": exact,
        "head_covered": head,
        "second_position_covered": second,
        "third_position_covered": third,
        "ordered_top2_hit": ordered_top2,
        "same_three_set_hit": same_three,
        "max_position_matches": max_matches,
        "miss_type": miss_type,
    }


def _best_structure(picks: list[str], winners: list[str]) -> dict:
    rows = [_structure_metrics(picks, winner) | {"winner": winner} for winner in winners]
    if not rows:
        return _structure_metrics(picks, "")
    return max(
        rows,
        key=lambda row: (
            int(bool(row["exact_hit"])),
            int(row["max_position_matches"]),
            int(bool(row["same_three_set_hit"])),
            int(bool(row["ordered_top2_hit"])),
            int(bool(row["head_covered"])),
        ),
    )


def _point_band(points: int) -> str:
    if points <= 8:
        return "<=8"
    if points <= 10:
        return "9-10"
    if points <= 12:
        return "11-12"
    if points <= 14:
        return "13-14"
    return "15+"


def _records_for_day(day: str) -> dict[str, dict]:
    main, selected = live_status.base_streams(day)
    opportunity = live_status.opportunity_streams(day)
    prototypes = live_status.prototype_streams(day)
    return {
        "main": main,
        "mid_odds": opportunity["mid_odds"],
        "longshot": opportunity["longshot"],
        "selected": selected,
        "hiyori": live_status.hiyori_stream(day),
        "prototype1": prototypes["prototype1"],
        "prototype2": prototypes["prototype2"],
        "prototype3": prototypes["prototype3"],
    }


def collect_observations() -> list[dict]:
    rows = []
    days = sorted(path.stem for path in live_status.OFFICIAL_DIR.glob("20*.json"))
    for day in days:
        official_by_key = live_status.load_official_cache(day)
        if not official_by_key:
            continue
        streams = _records_for_day(day)
        for stream, records in streams.items():
            for key, record in sorted(records.items()):
                official = official_by_key.get(key)
                score = live_status.score_one(record, official)
                if not isinstance(score, dict) or not score.get("eligible"):
                    continue
                winners = _winning_combos(official)
                if not winners:
                    continue
                picks = live_status.unique_picks(record.get("picks") or [])
                structure = _best_structure(picks, winners)
                profit = int(score.get("profit_yen") or 0)
                if score.get("hit") and profit > 0:
                    outcome = "profitable_hit"
                elif score.get("hit") and profit < 0:
                    outcome = "torigami_hit"
                elif score.get("hit"):
                    outcome = "break_even_hit"
                else:
                    outcome = "miss"
                rows.append({
                    "day": day,
                    "stream": stream,
                    "label": live_status.LABELS.get(stream, stream),
                    "key": key,
                    "jcd": str(record.get("jcd") or "").zfill(2),
                    "rno": int(record.get("rno") or 0),
                    "venue": record.get("venue"),
                    "point_count": int(score.get("point_count") or len(picks)),
                    "point_band": _point_band(int(score.get("point_count") or len(picks))),
                    "picks": picks,
                    "winning_combos": winners,
                    "hit": bool(score.get("hit")),
                    "stake_yen": int(score.get("stake_yen") or 0),
                    "return_yen": int(score.get("return_yen") or 0),
                    "profit_yen": profit,
                    "roi": (
                        100 * int(score.get("return_yen") or 0) / int(score.get("stake_yen") or 1)
                    ),
                    "torigami": bool(score.get("torigami")),
                    "manshu": bool(score.get("manshu")),
                    "outcome": outcome,
                    "model_version": record.get("model_version"),
                    **structure,
                })
    return rows


def _summary(rows: list[dict]) -> dict:
    samples = len(rows)
    hits = sum(bool(r.get("hit")) for r in rows)
    stake = sum(int(r.get("stake_yen") or 0) for r in rows)
    returned = sum(int(r.get("return_yen") or 0) for r in rows)
    torigami = sum(bool(r.get("torigami")) for r in rows)
    manshu = sum(bool(r.get("manshu")) for r in rows)
    misses = [r for r in rows if not r.get("hit")]
    miss_types = Counter(str(r.get("miss_type") or "unknown") for r in misses)
    return {
        "samples": samples,
        "days": len({r.get("day") for r in rows}),
        "hits": hits,
        "hit_rate": 100 * hits / samples if samples else None,
        "profitable_hits": sum(r.get("outcome") == "profitable_hit" for r in rows),
        "torigami": torigami,
        "torigami_rate_of_hits": 100 * torigami / hits if hits else None,
        "manshu": manshu,
        "stake_yen": stake,
        "return_yen": returned,
        "profit_yen": returned - stake,
        "roi": 100 * returned / stake if stake else None,
        "avg_points": (
            sum(int(r.get("point_count") or 0) for r in rows) / samples if samples else None
        ),
        "head_coverage_rate": (
            100 * sum(bool(r.get("head_covered")) for r in rows) / samples if samples else None
        ),
        "ordered_top2_rate": (
            100 * sum(bool(r.get("ordered_top2_hit")) for r in rows) / samples if samples else None
        ),
        "same_three_set_rate": (
            100 * sum(bool(r.get("same_three_set_hit")) for r in rows) / samples if samples else None
        ),
        "miss_types": dict(sorted(miss_types.items())),
    }


def _group_summary(rows: list[dict], field: str) -> dict:
    groups = defaultdict(list)
    for row in rows:
        groups[str(row.get(field) or "unknown")].append(row)
    return {name: _summary(group) for name, group in sorted(groups.items())}


def _recent_split(rows: list[dict], count: int = 3) -> tuple[list[dict], list[dict]]:
    days = sorted({str(r.get("day")) for r in rows if r.get("day")})
    recent_days = set(days[-count:])
    return (
        [r for r in rows if r.get("day") not in recent_days],
        [r for r in rows if r.get("day") in recent_days],
    )


def _complementarity(rows: list[dict]) -> dict:
    by_race = defaultdict(dict)
    for row in rows:
        by_race[(row["day"], row["key"])][row["stream"]] = row

    exclusive = Counter()
    unique_profit = Counter()
    pair = defaultdict(lambda: {"common": 0, "both_hit": 0, "a_only": 0, "b_only": 0, "neither": 0})
    streams = list(STREAMS)

    for race_rows in by_race.values():
        hit_streams = [s for s, r in race_rows.items() if r.get("hit")]
        if len(hit_streams) == 1:
            winner = hit_streams[0]
            exclusive[winner] += 1
            unique_profit[winner] += int(race_rows[winner].get("profit_yen") or 0)

        for i, a in enumerate(streams):
            for b in streams[i + 1:]:
                if a not in race_rows or b not in race_rows:
                    continue
                bucket = pair[f"{a}_vs_{b}"]
                bucket["common"] += 1
                ah = bool(race_rows[a].get("hit"))
                bh = bool(race_rows[b].get("hit"))
                if ah and bh:
                    bucket["both_hit"] += 1
                elif ah:
                    bucket["a_only"] += 1
                elif bh:
                    bucket["b_only"] += 1
                else:
                    bucket["neither"] += 1

    return {
        "exclusive_hits": dict(exclusive),
        "exclusive_hit_profit_yen": dict(unique_profit),
        "pairwise": dict(pair),
    }


def _action_for(stream: str, stats: dict) -> list[dict]:
    samples = int(stats.get("samples") or 0)
    if samples < MIN_GLOBAL_SAMPLES:
        return [{"action": "collect_more", "reason": f"sample<{MIN_GLOBAL_SAMPLES}"}]

    out = []
    roi = float(stats.get("roi") or 0)
    hit_rate = float(stats.get("hit_rate") or 0)
    torigami_rate = float(stats.get("torigami_rate_of_hits") or 0)
    miss = stats.get("miss_types") or {}
    miss_total = sum(int(v or 0) for v in miss.values())

    if hit_rate >= 45 and roi < 95 and torigami_rate >= 25:
        out.append({
            "action": "compress_low_value_points",
            "reason": "hit rate is useful but too many winning races still lose money",
        })
    if roi >= 115 and int(stats.get("manshu") or 0) >= 2:
        out.append({
            "action": "preserve_high_payout_role",
            "reason": "positive ROI with repeated manshu evidence; avoid diluting selectivity",
        })
    if hit_rate < 30 and roi >= 120:
        out.append({
            "action": "preserve_selectivity",
            "reason": "low hit rate is acceptable because payout efficiency is strong",
        })

    if miss_total:
        third_miss = int(miss.get("ordered_top2_third_miss") or 0)
        order_miss = int(miss.get("same_three_wrong_order") or 0)
        head_miss = (
            int(miss.get("two_positions_match_head_miss") or 0)
            + int(miss.get("one_position_match") or 0)
            + int(miss.get("full_miss") or 0)
        )
        if third_miss / miss_total >= 0.16:
            out.append({
                "action": "review_third_place_coverage",
                "reason": "a material share of misses already had the ordered top two",
            })
        if order_miss / miss_total >= 0.12:
            out.append({
                "action": "review_order_reversal_cover",
                "reason": "same three boats were found but order was wrong often enough to study",
            })
        if head_miss / miss_total >= 0.45:
            out.append({
                "action": "review_head_selection",
                "reason": "too many misses begin with the winner axis itself",
            })

    return out or [{"action": "keep_collecting", "reason": "no robust change signal yet"}]


def build_state(rows: list[dict]) -> dict:
    by_stream = {}
    recommendations = {}
    for stream in STREAMS:
        srows = [r for r in rows if r["stream"] == stream]
        prior, recent = _recent_split(srows, 3)
        venues = _group_summary(srows, "venue")
        bands = _group_summary(srows, "point_band")
        by_stream[stream] = {
            "label": live_status.LABELS.get(stream, stream),
            "overall": _summary(srows),
            "prior": _summary(prior),
            "recent_3_days": _summary(recent),
            "by_day": _group_summary(srows, "day"),
            "by_venue": venues,
            "by_point_band": bands,
        }

        positive_venues = []
        weak_venues = []
        for venue, stats in venues.items():
            if int(stats.get("samples") or 0) < MIN_VENUE_SAMPLES or int(stats.get("days") or 0) < MIN_DAYS:
                continue
            roi = stats.get("roi")
            if roi is not None and roi >= 115 and int(stats.get("profit_yen") or 0) > 0:
                positive_venues.append({"venue": venue, **stats})
            elif roi is not None and roi <= 75:
                weak_venues.append({"venue": venue, **stats})
        positive_venues.sort(key=lambda x: (x.get("roi") or 0, x.get("samples") or 0), reverse=True)
        weak_venues.sort(key=lambda x: (x.get("roi") or 999, -(x.get("samples") or 0)))

        efficient_bands = []
        wasteful_bands = []
        for band, stats in bands.items():
            if int(stats.get("samples") or 0) < MIN_BAND_SAMPLES:
                continue
            roi = stats.get("roi")
            if roi is not None and roi >= 110:
                efficient_bands.append({"point_band": band, **stats})
            elif roi is not None and roi <= 85:
                wasteful_bands.append({"point_band": band, **stats})

        recommendations[stream] = {
            "label": live_status.LABELS.get(stream, stream),
            "actions": _action_for(stream, by_stream[stream]["overall"]),
            "positive_venue_candidates": positive_venues[:8],
            "weak_venue_candidates": weak_venues[:8],
            "efficient_point_bands": efficient_bands,
            "wasteful_point_bands": wasteful_bands,
        }

    return {
        "updated_at": datetime.now(JST).isoformat(),
        "learning_version": "all-ai-historical-v1",
        "definition": "actually delivered predictions only; settled official results; flat 100 yen per disclosed pick",
        "safety": {
            "live_weights_mutated": False,
            "minimum_global_samples": MIN_GLOBAL_SAMPLES,
            "minimum_venue_samples": MIN_VENUE_SAMPLES,
            "minimum_point_band_samples": MIN_BAND_SAMPLES,
            "minimum_days": MIN_DAYS,
            "rule": "Historical evidence becomes a candidate signal first. Live promotion requires separate validation.",
        },
        "observation_count": len(rows),
        "days": sorted({r["day"] for r in rows}),
        "streams": by_stream,
        "complementarity": _complementarity(rows),
        "recommendations": recommendations,
    }


def main() -> int:
    rows = collect_observations()
    state = build_state(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    OBS_PATH.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    daily_dir = OUT / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)
    by_day_rows = defaultdict(list)
    for row in rows:
        by_day_rows[str(row.get("day") or "unknown")].append(row)
    for day, day_rows in sorted(by_day_rows.items()):
        (daily_dir / f"{day}.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in day_rows),
            encoding="utf-8",
        )
    _write_json(STATE_PATH, state)
    _write_json(RECOMMENDATION_PATH, {
        "updated_at": state["updated_at"],
        "learning_version": state["learning_version"],
        "safety": state["safety"],
        "recommendations": state["recommendations"],
        "complementarity": state["complementarity"],
    })

    compact = []
    for stream in STREAMS:
        stats = state["streams"][stream]["overall"]
        compact.append(
            f"{live_status.LABELS.get(stream, stream)}:"
            f"{stats['hits']}/{stats['samples']} "
            f"hit={stats['hit_rate']:.1f}% roi={stats['roi']:.1f}% "
            f"torigami={stats['torigami']}"
            if stats["samples"] and stats["hit_rate"] is not None and stats["roi"] is not None
            else f"{live_status.LABELS.get(stream, stream)}:no-data"
        )
    print(" | ".join(compact))
    print(f"historical observations={len(rows)} days={len(state['days'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
