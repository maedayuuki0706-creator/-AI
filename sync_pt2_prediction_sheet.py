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

import pt2_strategy_cards

SPREADSHEET_ID = os.getenv(
    "BOAT_SHEET_ID",
    "1dbUPyfxjIRaT-G8F_LlGMX7Ld_ZB951UmF4HpW_PYJo",
)
SHEET_NAME = os.getenv("PT2_VIEW_SHEET", "PT2予想シート")
HELPER_SHEET_NAME = os.getenv("PT2_VIEW_HELPER_SHEET", "PT2予想候補")
LOG_SHEET_NAME = os.getenv("PT2_VIEW_LOG_SHEET", "PT2予想ログ")
PREDICTION_ROOT = Path("data/prototype12_delivery/predictions")
JST = ZoneInfo("Asia/Tokyo")
LOG_HEADERS = [
    "保存日時", "開催日", "場", "R", "締切", "key",
    "1号艇指数", "2号艇指数", "3号艇指数", "4号艇指数", "5号艇指数", "6号艇指数",
    "総合型", "本命型", "妙味型", "高配当型",
    "激絞り", "穴特化", "逃げ穴", "BOX型",
    "軸候補", "相手上位", "穴警戒", "DB一致度", "AI一致度", "万舟候補",
    "model_version", "strategy_version",
    "結果", "払戻", "総合型的中", "本命型的中", "妙味型的中", "高配当型的中",
    "予想生成時刻",
]

HELPER_HEADERS = [
    "選択", "key", "締切", "更新", "荒れ指数",
    "1号艇指数", "2号艇指数", "3号艇指数", "4号艇指数", "5号艇指数", "6号艇指数",
    "総合型", "本命型", "妙味型", "高配当型",
    "激絞り", "穴特化", "逃げ穴", "BOX型",
    "軸候補", "相手上位", "穴警戒", "DB一致度", "AI一致度", "万舟候補",
    "model_version", "strategy_version", "created_at",
]


def _load(path: Path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def _deadline_at(record):
    day = str(record.get("day") or "")
    deadline = str(record.get("deadline") or "")
    try:
        return datetime.strptime(f"{day} {deadline}", "%Y%m%d %H:%M").replace(tzinfo=JST)
    except (TypeError, ValueError):
        return None


def _all_prediction_records():
    """Return every valid PT2 prediction currently persisted on disk.

    This is intentionally independent of deadline state so the permanent
    prediction log can backfill a race even when the Sheets refresh runs late.
    """
    out = []
    if not PREDICTION_ROOT.exists():
        return out
    for path in PREDICTION_ROOT.glob("*.json"):
        record = _load(path)
        if not record:
            continue
        model = ((record.get("models") or {}).get("prototype2") or {})
        if not model:
            continue
        created = str(record.get("created_at") or "")
        try:
            created_at = datetime.fromisoformat(created).astimezone(JST)
        except (TypeError, ValueError):
            continue
        out.append((created_at, str(record.get("key") or ""), record))
    out.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in out]


def _active_records(now=None):
    now = now or datetime.now(JST)
    out = []
    for record in _all_prediction_records():
        created = str(record.get("created_at") or "")
        created_at = datetime.fromisoformat(created).astimezone(JST)
        deadline_at = _deadline_at(record)
        if deadline_at is None:
            continue
        # Only races whose prediction already exists and whose deadline has not
        # passed are selectable.
        if created_at <= now < deadline_at:
            out.append((deadline_at, created_at, str(record.get("key") or ""), record))
    out.sort(key=lambda item: (item[0], item[1], item[2]))
    return [item[3] for item in out]


def _latest_record():
    active = _active_records()
    if active:
        return active[0]
    candidates = []
    if not PREDICTION_ROOT.exists():
        return None
    for path in PREDICTION_ROOT.glob("*.json"):
        record = _load(path)
        if not record:
            continue
        model = ((record.get("models") or {}).get("prototype2") or {})
        if not model:
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


def _strategy_cards(model):
    existing = ((model.get("strategy_cards") or {}).get("cards") or {})
    if existing:
        return existing

    # Backfill the first live view from pre-multi-strategy predictions using the
    # DB audit that already stores the adjusted probability delta for all 120
    # combinations. This does not alter the archived prediction.
    db = model.get("database") or {}
    audit = db.get("probability_audit") or {}
    base = audit.get("base_probability") or {}
    delta = audit.get("probability_delta_pp") or {}
    odds = {
        str(row.get("combination")): _safe_float(row.get("odds"))
        for row in model.get("trifecta") or []
        if row.get("combination")
    }
    rows = []
    for combo, base_p in base.items():
        try:
            probability = float(base_p) + float(delta.get(combo, 0.0)) / 100.0
        except (TypeError, ValueError):
            continue
        if probability <= 0:
            continue
        odd = odds.get(str(combo))
        rows.append({
            "combination": str(combo),
            "probability": probability,
            "odds": odd,
            "expected_value": probability * odd if odd is not None else None,
        })
    if not rows:
        return {}
    return pt2_strategy_cards.build_strategy_cards(
        {"trifecta": rows},
        model,
    ).get("cards") or {}


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
    non_axis_holes = [(lane, count) for lane, count in head_counts.most_common() if lane != axis]
    hole_lane = non_axis_holes[0][0] if non_axis_holes else ranked[3]

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
    box = f"{''.join(map(str, top3))}BOX"

    return {
        "squeeze": _mini_text(squeeze, len(squeeze)),
        "hole": _mini_text(hole, len(hole)),
        "escape": _mini_text(escape, len(escape)),
        "box": f"{box}\n\n計6点",
    }


def build_payload(record):
    model = ((record.get("models") or {}).get("prototype2") or {})
    cards = _strategy_cards(model)
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

    selector = f"{record.get('venue', '—')} {record.get('rno', '—')}R｜{record.get('deadline') or '—'}"
    strategy_version = str(((model.get("strategy_cards") or {}).get("version") or ""))
    return {
        "key": record.get("key"),
        "selector": selector,
        "deadline_at": _deadline_at(record),
        "values": {
            "A3": selector,
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
            "N3": strategy_version,
        },
        "helper_row": [
            selector,
            str(record.get("key") or ""),
            str(record.get("deadline") or ""),
            updated,
            volatility_text,
            *[str(value) for value in summary["scores"]],
            _card_text(cards.get("balanced") or {}),
            _card_text(cards.get("probability") or {}),
            _card_text(cards.get("value") or {}),
            _card_text(cards.get("longshot") or {}),
            sides["squeeze"],
            sides["hole"],
            sides["escape"],
            sides["box"],
            summary["axis"],
            summary["opponents"],
            summary["hole"],
            summary["db"],
            summary["ai"],
            summary["manshu"],
            str(model.get("model_version") or ""),
            strategy_version,
            created,
        ],
    }


def _lookup_formula(index):
    return f'=IFERROR(VLOOKUP($A$3,\'{HELPER_SHEET_NAME}\'!$A$2:$AB$100,{index},FALSE),"—")'


def _ensure_helper(book):
    import gspread

    try:
        helper = book.worksheet(HELPER_SHEET_NAME)
    except gspread.WorksheetNotFound:
        helper = book.add_worksheet(title=HELPER_SHEET_NAME, rows=120, cols=len(HELPER_HEADERS))
        try:
            helper.hide()
        except Exception:
            pass
    return helper


def _ensure_log(book):
    import gspread

    try:
        log = book.worksheet(LOG_SHEET_NAME)
    except gspread.WorksheetNotFound:
        log = book.add_worksheet(title=LOG_SHEET_NAME, rows=5000, cols=len(LOG_HEADERS))
        log.update([LOG_HEADERS], "A1", raw=True)
    return log


def _prediction_log_row(record, payload, saved_at=None):
    saved_at = saved_at or datetime.now(JST)
    row = payload["helper_row"]
    return [
        saved_at.strftime("%Y-%m-%d %H:%M:%S"),
        str(record.get("day") or ""),
        str(record.get("venue") or ""),
        str(record.get("rno") or ""),
        str(record.get("deadline") or ""),
        str(record.get("key") or ""),
        *row[5:11],
        *row[11:15],
        *row[15:19],
        *row[19:25],
        row[25],
        row[26],
        "", "", "", "", "", "",
        row[27],
    ]


def _append_prediction_logs(log_ws, records):
    existing_keys = {
        str(value).strip()
        for value in log_ws.col_values(6)[1:]
        if str(value).strip()
    }
    rows = []
    now = datetime.now(JST)
    for record in records:
        key = str(record.get("key") or "").strip()
        if not key or key in existing_keys:
            continue
        payload = build_payload(record)
        rows.append(_prediction_log_row(record, payload, saved_at=now))
        existing_keys.add(key)
    if rows:
        log_ws.append_rows(rows, value_input_option="RAW")
    return len(rows)


def _install_selector_formulas(book, ws, helper):
    formulas = {
        "D3": '="締切："&' + _lookup_formula(3).lstrip("="),
        "G3": '="荒れ指数："&' + _lookup_formula(5).lstrip("="),
        "J3": '="最終更新："&' + _lookup_formula(4).lstrip("="),
        "A5": _lookup_formula(6),
        "C5": _lookup_formula(7),
        "E5": _lookup_formula(8),
        "G5": _lookup_formula(9),
        "I5": _lookup_formula(10),
        "K5": _lookup_formula(11),
        "B7": _lookup_formula(12),
        "B12": _lookup_formula(13),
        "B17": _lookup_formula(14),
        "B22": _lookup_formula(15),
        "J7": _lookup_formula(16),
        "J12": _lookup_formula(17),
        "J17": _lookup_formula(18),
        "J22": _lookup_formula(19),
        "A29": _lookup_formula(20),
        "C29": _lookup_formula(21),
        "E29": _lookup_formula(22),
        "G29": _lookup_formula(23),
        "I29": _lookup_formula(24),
        "K29": _lookup_formula(25),
        "N1": _lookup_formula(2),
        "N2": _lookup_formula(26),
        "N3": _lookup_formula(27),
    }
    ws.batch_update(
        [{"range": cell, "values": [[formula]]} for cell, formula in formulas.items()],
        raw=False,
    )

    options = [str(value) for value in helper.col_values(1)[1:] if str(value).strip()]
    condition_values = [{"userEnteredValue": value} for value in options]
    if condition_values:
        book.batch_update({
            "requests": [
                {
                    "setDataValidation": {
                        "range": {
                            "sheetId": ws.id,
                            "startRowIndex": 2,
                            "endRowIndex": 3,
                            "startColumnIndex": 0,
                            "endColumnIndex": 1,
                        },
                        "rule": {
                            "condition": {
                                "type": "ONE_OF_LIST",
                                "values": condition_values,
                            },
                            "strict": True,
                            "showCustomUi": True,
                        },
                    }
                }
            ]
        })


def publish():
    import gspread
    from google.oauth2.service_account import Credentials

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
    helper = _ensure_helper(book)
    log_ws = _ensure_log(book)

    records = _active_records()
    payloads = [build_payload(record) for record in records]
    # Permanent logging is not limited to races that are still selectable.
    # This backfills predictions that were generated correctly but missed a
    # delayed Sheets refresh after their deadline.
    logged_count = _append_prediction_logs(log_ws, _all_prediction_records())

    rows = [HELPER_HEADERS]
    if payloads:
        rows.extend(payload["helper_row"] for payload in payloads)
    else:
        rows.append(["現在選択可能な予想なし"] + [""] * (len(HELPER_HEADERS) - 1))

    helper.clear()
    helper.update(rows, "A1", raw=True)
    try:
        helper.hide()
    except Exception:
        pass

    _install_selector_formulas(book, ws, helper)

    options = [payload["selector"] for payload in payloads]
    current = (ws.acell("A3").value or "").strip()
    if not options:
        desired = "現在選択可能な予想なし"
    elif current in options:
        desired = current
    else:
        # Default to the race with the nearest remaining deadline.
        desired = options[0]
    if current != desired:
        ws.update_acell("A3", desired)

    # Keep implementation/debug metadata out of the visible prediction board.
    try:
        ws.hide_columns(13, 20)
    except Exception:
        pass

    print(json.dumps({
        "updated": True,
        "active_count": len(payloads),
        "selected": desired,
        "options": options,
        "sheet": SHEET_NAME,
        "logged_count": logged_count,
        "log_sheet": LOG_SHEET_NAME,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(publish())
