"""Publish the latest multi-strategy PT2 prediction into Google Sheets.

This is a presentation-only writer. It does not change prediction logic.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

SPREADSHEET_ID = os.getenv(
    "BOAT_SHEET_ID",
    "1dbUPyfxjIRaT-G8F_LlGMX7Ld_ZB951UmF4HpW_PYJo",
)
SHEET_NAME = os.getenv("PT2_VIEW_SHEET", "PT2予想シート")
PREDICTION_ROOT = Path("data/prototype12_delivery/predictions")
JST = ZoneInfo("Asia/Tokyo")


def _load(path: Path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def _latest_record():
    candidates = []
    if not PREDICTION_ROOT.exists():
        return None
    for path in PREDICTION_ROOT.glob("*.json"):
        record = _load(path)
        if not record:
            continue
        model = ((record.get("models") or {}).get("prototype2") or {})
        cards = ((model.get("strategy_cards") or {}).get("cards") or {})
        if not cards:
            continue
        created = str(record.get("created_at") or "")
        candidates.append((created, path.name, record))
    if not candidates:
        return None
    candidates.sort()
    return candidates[-1][2]


def _compact_formations(picks):
    groups = defaultdict(list)
    singles = []
    order = []
    for combo in picks or []:
        bits = str(combo).split("-")
        if len(bits) != 3:
            singles.append(str(combo))
            continue
        first, second, third = bits
        key = (first, second)
        if key not in groups:
            order.append(key)
        if third not in groups[key]:
            groups[key].append(third)
    out = []
    for first, second in order:
        thirds = groups[(first, second)]
        if len(thirds) >= 2:
            out.append(f"{first}-{second}-{''.join(thirds)}")
        else:
            out.append(f"{first}-{second}-{thirds[0]}")
    out.extend(singles)
    return out


def _card_text(card, main_limit=4, cover_limit=6):
    main = list(card.get("main_picks") or [])
    cover = list(card.get("cover_picks") or [])
    if not main and card.get("picks"):
        main = list(card.get("picks") or [])[:main_limit]
        cover = list(card.get("picks") or [])[main_limit:]
    main_lines = _compact_formations(main[:main_limit])
    cover_lines = _compact_formations(cover[:cover_limit])
    lines = ["本線"]
    lines.extend(main_lines or ["—"])
    if cover:
        lines += ["", "抑え"]
        lines.extend(cover_lines or ["—"])
    lines += ["", f"計{int(card.get('point_count') or len(card.get('picks') or []))}点"]
    return "\n".join(lines)


def _mini_text(picks, point_count=None, label=None):
    compact = _compact_formations(picks)
    lines = []
    if label:
        lines.append(label)
    lines.extend(compact or ["—"])
    lines += ["", f"計{point_count if point_count is not None else len(picks or [])}点"]
    return "\n".join(lines)


def _boat_scores(model):
    db = model.get("database") or {}
    audit = db.get("probability_audit") or {}
    heads = audit.get("adjusted_heads") or model.get("heads") or {}
    values = []
    for lane in range(1, 7):
        value = heads.get(str(lane), heads.get(lane))
        try:
            probability = float(value)
        except (TypeError, ValueError):
            probability = 1 / 6
        # Center on an equal 1/6 field. This is a display index, not a calibrated
        # probability replacement.
        score = round((probability - (1 / 6)) * 100)
        values.append(score)
    return values, heads


def _summary(cards, model):
    scores, heads = _boat_scores(model)
    ranked = sorted(range(1, 7), key=lambda lane: scores[lane - 1], reverse=True)
    axis = ranked[0]
    opponents = ranked[1:3]

    longshot = cards.get("longshot") or {}
    longshot_picks = list(longshot.get("picks") or [])
    head_counts = Counter(
        int(str(pick).split("-")[0])
        for pick in longshot_picks
        if str(pick)[:1].isdigit()
    )
    hole_lane = head_counts.most_common(1)[0][0] if head_counts else ranked[3]

    balanced = cards.get("balanced") or {}
    top_pick = (balanced.get("picks") or [None])[0]
    agreeing = 0
    for card in cards.values():
        if top_pick and top_pick in (card.get("picks") or []):
            agreeing += 1

    db = model.get("database") or {}
    db_match = f"{db.get('player_matches', 0)}/6 選手\n{db.get('motor_matches', 0)}/6 M"

    metrics = longshot.get("pick_metrics") or []
    manshu = [
        row.get("combination")
        for row in metrics
        if row.get("combination") and (row.get("odds") or 0) >= 100
    ][:2]
    if not manshu:
        manshu = longshot_picks[:2]

    return {
        "axis": f"{axis}号艇",
        "opponents": "・".join(map(str, opponents)),
        "hole": f"{hole_lane}号艇",
        "db": db_match,
        "ai": f"{agreeing}/4",
        "manshu": "\n".join(manshu) if manshu else "—",
        "ranked": ranked,
        "scores": scores,
    }


def _side_cards(cards, summary):
    probability = cards.get("probability") or {}
    value = cards.get("value") or {}
    longshot = cards.get("longshot") or {}

    squeeze = list(probability.get("picks") or [])[:5]
    hole = list(longshot.get("picks") or [])[:4]

    escape = []
    for pick in list(value.get("picks") or []) + list(longshot.get("picks") or []):
        if str(pick).startswith("1-") and pick not in escape:
            escape.append(pick)
        if len(escape) >= 7:
            break

    top3 = summary["ranked"][:3]
    box = [f"{''.join(map(str, top3))}BOX"]

    return {
        "squeeze": _mini_text(squeeze, len(squeeze)),
        "hole": _mini_text(hole, len(hole)),
        "escape": _mini_text(escape, len(escape)),
        "box": _mini_text(box, 6),
    }


def build_payload(record):
    model = ((record.get("models") or {}).get("prototype2") or {})
    cards = ((model.get("strategy_cards") or {}).get("cards") or {})
    summary = _summary(cards, model)
    sides = _side_cards(cards, summary)
    db = model.get("database") or {}
    volatility = db.get("venue_volatility")
    try:
        volatility_text = f"{float(volatility):.1f}"
    except (TypeError, ValueError):
        volatility_text = "—"

    created = str(record.get("created_at") or "")
    try:
        dt = datetime.fromisoformat(created).astimezone(JST)
        updated = dt.strftime("%m/%d %H:%M")
    except Exception:
        updated = created[-8:] if created else "—"

    return {
        "key": record.get("key"),
        "values": {
            "A3": f"場・R：{record.get('venue', '—')} {record.get('rno', '—')}R",
            "D3": f"締切：{record.get('deadline') or '—'}",
            "G3": f"荒れ指数：{volatility_text}",
            "J3": f"最終更新：{updated}",
            "A5": str(summary["scores"][0]),
            "C5": str(summary["scores"][1]),
            "E5": str(summary["scores"][2]),
            "G5": str(summary["scores"][3]),
            "I5": str(summary["scores"][4]),
            "K5": str(summary["scores"][5]),
            "B7": _card_text(cards.get("balanced") or {}),
            "B12": _card_text(cards.get("probability") or {}),
            "B17": _card_text(cards.get("value") or {}),
            "B22": _card_text(cards.get("longshot") or {}),
            "J7": sides["squeeze"],
            "J12": sides["hole"],
            "J17": sides["escape"],
            "J22": sides["box"],
            "A29": summary["axis"],
            "C29": summary["opponents"],
            "E29": summary["hole"],
            "G29": summary["db"],
            "I29": summary["ai"],
            "K29": summary["manshu"],
            "N1": str(record.get("key") or ""),
            "N2": str(model.get("model_version") or ""),
            "N3": str(((model.get("strategy_cards") or {}).get("version") or "")),
        },
    }


def publish():
    import gspread
    from google.oauth2.service_account import Credentials

    record = _latest_record()
    if record is None:
        print("No multi-strategy PT2 prediction available yet.")
        return 0

    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON secret is required")
    info = json.loads(raw)
    creds = Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    book = gspread.authorize(creds).open_by_key(SPREADSHEET_ID)
    ws = book.worksheet(SHEET_NAME)

    payload = build_payload(record)
    current_key = (ws.acell("N1").value or "").strip()
    if current_key == str(payload["key"] or ""):
        print(f"PT2 prediction sheet already current: {current_key}")
        return 0

    updates = [
        {"range": cell, "values": [[value]]}
        for cell, value in payload["values"].items()
    ]
    ws.batch_update(updates, raw=True)

    # Keep implementation/debug metadata out of the visible prediction board.
    try:
        ws.hide_columns(13, 20)
    except Exception:
        pass

    print(json.dumps({
        "updated": True,
        "key": payload["key"],
        "venue": record.get("venue"),
        "rno": record.get("rno"),
        "sheet": SHEET_NAME,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(publish())
