"""Build small, read-only viewer assets from already collected public data.

Never imports prediction, delivery, or Sheets-writing code. New races continue
to use the public main-branch files when no bundled snapshot exists.
"""
from datetime import datetime, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "viewer" / "data"


def compact_prediction(record):
    model = (record.get("models") or {}).get("prototype2")
    if not model:
        return None
    cards = {}
    for key, card in ((model.get("strategy_cards") or {}).get("cards") or {}).items():
        if key in {"balanced", "probability", "value", "longshot"}:
            cards[key] = {k: card[k] for k in ("main_picks", "cover_picks", "point_count", "selection_policy") if k in card}
    result = {k: record.get(k) for k in ("day", "jcd", "rno", "venue", "deadline", "created_at", "digest")}
    result["models"] = {"prototype2": {"grade": model.get("grade"), "heads": model.get("heads"), "strategy_cards": {"cards": cards}}}
    return result


def compact_card(request):
    boats = (request.get("official") or {}).get("inputs")
    if not isinstance(boats, list) or len(boats) != 6:
        return None
    if {b.get("lane") for b in boats} != set(range(1, 7)):
        return None
    fields = ("lane", "racer_id", "name", "current_class", "win_rate", "avg_st", "motor_number", "motor_top2_rate", "local_win_rate", "flying")
    return {"captured_at": request.get("captured_at"), "day": request.get("day"), "jcd": request.get("jcd"), "rno": request.get("rno"), "deadline": request.get("deadline"), "boats": [{k: b.get(k) for k in fields} for b in sorted(boats, key=lambda b: b["lane"])]}


def main():
    start = (datetime.now(ZoneInfo("Asia/Tokyo")) - timedelta(days=7)).strftime("%Y%m%d")
    packs = {}
    old_bytes = 0
    for file in (ROOT / "data/prototype12_delivery/predictions").glob("*.json"):
        if file.stem[:8] < start:
            continue
        record = json.loads(file.read_text())
        prediction = compact_prediction(record)
        if prediction:
            packs[file.stem] = {"prediction": prediction}
            old_bytes += file.stat().st_size
    for file in (ROOT / "data/hiyori/requests").glob("*.json"):
        if file.stem[:8] < start:
            continue
        request = json.loads(file.read_text())
        card = compact_card(request)
        if card:
            packs.setdefault(file.stem, {})["race"] = card
    OUT.mkdir(exist_ok=True)
    days = {}
    # Browsers download only the selected race, rather than an entire day's data.
    for key, pack in packs.items():
        day, venue, race = key.split("_")
        days.setdefault(day, set()).add(venue)
        target = OUT / "races" / (key + ".json")
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(pack, ensure_ascii=False, separators=(",", ":")) + "\n")
    manifest = {"built_at": datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(), "days": {d: sorted(v) for d, v in days.items()}, "keys": sorted(packs)}
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")) + "\n")
    new_bytes = sum((OUT / "races" / (key + ".json")).stat().st_size for key in packs)
    print(json.dumps({"race_count": len(packs), "original_prediction_bytes": old_bytes, "viewer_pack_bytes": new_bytes}))


if __name__ == "__main__":
    main()
