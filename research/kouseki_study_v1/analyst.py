"""航跡 BOAT LAB / analyst v0.1 (read-only research).

Run from repository root:
  python research/kouseki_study_v1/analyst.py --archive data/exhibition_log --target PATH --out research/output/analyst.json

No network, automatic picks, odds ranking, notifications, live model changes,
or writes to archived data. Only creates a new JSON in research/output.
The source comparison counts completed finishes, not all starts.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from analytics import build_report
from analyst_context import build_context

MIN_N = 20  # descriptive review threshold, not statistical validation


def make_brief(report, target):
    raw = {b["lane"]: b for b in target["rows"]}
    boats = []
    for b in report["racers"]:
        assumed = b["assumed_course"]
        c = next(c for c in b["courses"] if c["course"] == assumed)
        year, recent, local = c["year_observed"], c["recent10"], c["local_year_observed"]
        sources = {
            "course": "exhibition_course" if raw[b["lane"]].get("exhibition_course") == assumed else "lane_fallback",
            "history": report["source"],
        }
        boats.append({
            "lane": b["lane"], "name": b["name"], "racer_id": b["racer_id"],
            "assumed_course": assumed, "sources": sources,
            "year_observed": year, "recent10": recent, "local_year_observed": local,
            "venue_course_benchmark": c["venue_course_benchmark"],
            "evidence_status": "limited" if year["n"] < MIN_N else "descriptive_only",
            "signals": c["signals"],
            "all_courses": b["courses"],
        })
    courses = [b["assumed_course"] for b in boats]
    complete_exhibition = all(b["sources"]["course"] == "exhibition_course" for b in boats)
    questions = [
        {"topic": "1コースの逃げ", "question": "同コース実績と当地実績に差はあるか。逃げ率・逃がし率は別途必要。"},
        {"topic": "スタート隊形", "question": "各コースの本番ST実績とばらつきはどうか。展示STから本番STを断定しない。"},
        {"topic": "相互関係", "question": "内艇の壁、攻め起点と外艇の連動を検証できる決まり手・相手データはあるか。"},
    ]
    return {
        "schema": "kouseki/analyst-brief-v0.1",
        "research_only": True,
        "date": report["date"], "venue": report["venue"], "race_no": report["race_no"],
        "history_as_of": report["as_of_rule"],
        "collection_coverage": report["collection_coverage"],
        "course_assumption": "exhibition_unconfirmed" if complete_exhibition and sorted(courses) == list(range(1, 7)) else "unverified_or_inconsistent",
        "boats": boats,
        "review_questions": questions,
        "unavailable_in_this_version": [
            "決まり手別の逃げ・逃がし・攻められ方", "相手条件別の連動・類似レース",
            "モーター出足・伸び・回り足推移", "潮位・風波を含む水面分析",
            "オリジナル展示の時系列・取得時刻の照合", "校正済み予測確率",
        ],
        "caution": "収録済みの完走成績の記述統計。母数の小さい差は不確か。展示進入は本番進入を保証しない。対象レースの結果は利用しない。予想・買い目・利益保証なし。",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=Path("data/exhibition_log"))
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    root = (Path.cwd() / "research" / "output").resolve()
    if not out.is_relative_to(root) or out.suffix != ".json":
        parser.error("--out must be a new JSON under research/output")
    if out.exists():
        parser.error("refusing to overwrite existing output")
    report = build_report(args.archive, args.target)
    target = json.loads(args.target.read_text(encoding="utf-8"))
    brief = make_brief(report, target)
    brief['schema'] = 'kouseki/analyst-brief-v0.2'
    brief['historical_context'] = build_context(args.archive, target)
    brief['unavailable_in_this_version'] = [
        'モーター周期・出足/伸び/回り足分析', '風向・潮位',
        'オリジナル展示分割タイム・締切前原本照合', '相手条件別の因果分析・校正済み確率',
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8") as f:
        json.dump(brief, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"analyst report: {out}")


if __name__ == "__main__":
    main()
