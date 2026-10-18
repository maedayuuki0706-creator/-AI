"""Manually refresh public display snapshots using GET only.

Writes ONLY viewer/data/public. Never imports live, prediction, delivery, Sheets,
or research code. No workflow or scheduler is installed by this command.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
REMOTE = "https://raw.githubusercontent.com/maedayuuki0706-creator/-AI/main/data/"
FIELDS = ("label", "judged", "hits", "hit_rate", "stake_yen", "return_yen", "roi",
          "profit_yen", "manshu", "torigami", "pending", "resolved", "delivered", "avg_points")
PLAYER_FIELDS = ("name", "class", "branch", "win", "avg_st", "course_win", "escape",
                 "sashi", "makuri", "makurisashi", "best_method", "course_samples",
                 "sample_count", "period", "as_of")
MOTOR_FIELDS = ("motor", "venue", "grade", "stretch", "launch", "turn", "run",
                "top2", "top3", "win", "starts", "firsts", "seconds", "thirds",
                "start", "as_of", "finals", "championships")


def fetch(path):
    request = Request(REMOTE + path, headers={"User-Agent": "BoatAiNavi-ReadOnlyDisplay/1.0"})
    with urlopen(request, timeout=35) as response:
        return json.load(response)


def pick(record, fields):
    return {key: record[key] for key in fields if key in record}


def main():
    names = ["sheet_db/meta.json", "sheet_db/motors.json", "sheet_db/players.json", "live_status/latest.json"]
    with ThreadPoolExecutor(max_workers=4) as executor:
        meta, motors, players, stats = list(executor.map(fetch, names))
    assert len(motors) == meta["motor_count"] and len(players) == meta["player_count"]
    assert stats["unit_yen"] == 100 and stats["streams"]
    out = ROOT / "data/public"
    out.mkdir(parents=True, exist_ok=True)
    retrieved = datetime.now(timezone.utc).isoformat()
    documents = {
        "meta.json": {**pick(meta, ("snapshot_at", "motor_count", "player_count", "venue_count", "source", "schema_version")), "retrieved_at": retrieved},
        "motors.json": {"snapshot_at": meta["snapshot_at"], "data": {key: pick(value, MOTOR_FIELDS) for key, value in motors.items()}},
        "players.json": {"snapshot_at": meta["snapshot_at"], "data": {key: pick(value, PLAYER_FIELDS) for key, value in players.items()}},
        "stats.json": {
            "day": stats["day"], "generated_at": stats["generated_at"], "unit_yen": 100,
            "basis": stats["basis"],
            "source": REMOTE + "live_status/latest.json", "retrieved_at": retrieved,
            "streams": {key: pick(value, FIELDS) for key, value in stats["streams"].items()},
            "venues": {venue: {key: pick(value, FIELDS) for key, value in values.items()} for venue, values in stats.get("venues", {}).items()},
        },
    }
    for name, document in documents.items():
        (out / name).write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps({"snapshot_at": meta["snapshot_at"], "stats_day": stats["day"], "players": len(players), "motors": len(motors), "ai_count": len(stats["streams"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
