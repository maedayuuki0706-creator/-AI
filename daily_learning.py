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
UA = "Boat-AI-Navi-Learner/1.0"
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


def evaluate_prediction(row: dict, result: list[int]) -> dict:
    combo = "-".join(map(str, result))
    main = row.get("main") or []
    cover = row.get("cover") or []
    # Only combinations actually displayed in Discord count as delivered picks.
    all_picks = list(dict.fromkeys(main + cover + (row.get("outsiders") or [])))
    top_pick = all_picks[0] if all_picks else None
    top_first = int(top_pick.split("-")[0]) if isinstance(top_pick, str) and re.match(r"^[1-6]-", top_pick) else None
    return {
        **row,
        "result": combo,
        "main_hit": combo in main,
        "cover_hit": combo in cover,
        "any_hit": combo in all_picks,
        "winner_read_hit": top_first == result[0] if top_first else False,
        "evaluated_at": datetime.now(JST).isoformat(),
    }


def aggregate(rows: list[dict]) -> dict:
    # Morning and final updates are one race, not two independent observations.
    latest = {}
    for row in rows:
        key = (row.get("day"), row.get("jcd"), row.get("rno"))
        if key not in latest or (row.get('sent_at', ''), row.get('phase', 'final') == 'final') >= (latest[key].get('sent_at', ''), latest[key].get('phase', 'final') == 'final'):
            latest[key] = row
    rows = list(latest.values())
    total = len(rows)
    def pct(n: int) -> float:
        return round(n / total, 4) if total else 0.0
    state = {
        "updated_at": datetime.now(JST).isoformat(),
        "samples": total,
        "overall": {
            "main_hits": sum(bool(r.get("main_hit")) for r in rows),
            "cover_hits": sum(bool(r.get("cover_hit")) for r in rows),
            "any_hits": sum(bool(r.get("any_hit")) for r in rows),
            "winner_read_hits": sum(bool(r.get("winner_read_hit")) for r in rows),
        },
        "by_source": {},
        "by_venue": {},
        "guidance": {
            "minimum_samples_before_weight_change": 50,
            "rule": "Record daily; do not change prediction weights from small samples. Recalibrate only after enough independent races.",
        },
    }
    for key, target in (("source", "by_source"), ("venue", "by_venue")):
        groups = defaultdict(list)
        for r in rows:
            groups[str(r.get(key) or "unknown")].append(r)
        for name, grp in groups.items():
            n = len(grp)
            state[target][name] = {
                "samples": n,
                "main_hit_rate": round(sum(bool(x.get("main_hit")) for x in grp) / n, 4),
                "any_hit_rate": round(sum(bool(x.get("any_hit")) for x in grp) / n, 4),
                "winner_read_rate": round(sum(bool(x.get("winner_read_hit")) for x in grp) / n, 4),
            }
    state["overall"].update({
        "main_hit_rate": pct(state["overall"]["main_hits"]),
        "any_hit_rate": pct(state["overall"]["any_hits"]),
        "winner_read_rate": pct(state["overall"]["winner_read_hits"]),
    })
    return state


def main() -> int:
    predictions = load_jsonl(LOG_PATH)
    evaluated = []
    previous = {(r.get('day'), race_key(r), r.get('sent_at')): r for r in load_jsonl(RESULTS_PATH)}
    for day in sorted({r.get('day') for r in predictions if r.get('day')}):
        chosen, _ = latest_predictions(predictions, day)
        path = RESULT_DIR / f'{day}.json'
        official = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        for key, row in chosen.items():
            result = official.get(key, {})
            combos = list(result.get('payouts', {})) if result.get('status') == 'settled' else []
            # A dead heat has multiple winning combinations. Match all of them.
            if combos:
                observations = [evaluate_prediction(row, list(map(int, combo.split('-')))) for combo in combos]
                record = observations[0]
                for name in ('main_hit', 'cover_hit', 'any_hit', 'winner_read_hit'):
                    record[name] = any(x[name] for x in observations)
                record['official_results'] = combos
                evaluated.append(record)
            elif not result and (day, key, row.get('sent_at')) in previous:
                evaluated.append(previous[(day, key, row.get('sent_at'))])
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(''.join(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n' for r in evaluated), encoding='utf-8')
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(aggregate(evaluated), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"daily learning complete: independent_pre_close_races={len(evaluated)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
