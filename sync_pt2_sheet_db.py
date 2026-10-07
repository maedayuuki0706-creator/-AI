"""Refresh PT2's Google-Sheets-backed database snapshot.

Reads the production spreadsheet through the existing service-account secret and
writes stable JSON snapshots under data/sheet_db. The live prediction/delivery
code is not imported, so a sync failure cannot stop Discord delivery.
"""
from __future__ import annotations

from datetime import datetime
import json
import math
import os
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo


SPREADSHEET_ID = os.getenv(
    "BOAT_SHEET_ID",
    "1dbUPyfxjIRaT-G8F_LlGMX7Ld_ZB951UmF4HpW_PYJo",
)
ROOT = Path("data/sheet_db")
JST = ZoneInfo("Asia/Tokyo")

MIN_PLAYERS = int(os.getenv("PT2_DB_MIN_PLAYERS", "1200"))
MIN_MOTORS = int(os.getenv("PT2_DB_MIN_MOTORS", "1000"))
MIN_VENUES = int(os.getenv("PT2_DB_MIN_VENUES", "24"))

PLAYER_HEADERS = {
    "登録番号": "id",
    "選手名": "name",
    "級別": "class",
    "支部": "branch",
    "勝率": "win",
    "1コース1着率": "course1",
    "2コース1着率": "course2",
    "3コース1着率": "course3",
    "4コース1着率": "course4",
    "5コース1着率": "course5",
    "6コース1着率": "course6",
    "逃げ率": "escape",
    "差し率": "sashi",
    "まくり率": "makuri",
    "まくり差し率": "makurisashi",
    "平均ST": "avg_st",
    "元A級": "former_a",
    "得意決まり手": "best_method",
    "総合評価": "overall_grade",
    "モーター整備力": "maintenance_grade",
    "ペラ調整力": "propeller_grade",
    "弱機立て直し力": "weak_motor_recovery",
    "弱機立て直しサンプル数": "weak_motor_samples",
    "整備改善値": "maintenance_improvement",
    "ペラ改善値": "propeller_improvement",
    "整備サンプル数": "maintenance_samples",
    "ペラサンプル数": "propeller_samples",
    "最新調整コメント": "latest_adjustment_comment",
    "メモ": "memo",
}

MOTOR_HEADERS = {
    "場コード": "jcd",
    "ボートレース場": "venue",
    "モーターNo.": "motor",
    "使用開始日": "start",
    "更新基準日": "as_of",
    "勝率": "win",
    "2連率": "top2",
    "3連率": "top3",
    "1着数": "firsts",
    "2着数": "seconds",
    "3着数": "thirds",
    "出走数": "starts",
    "優出回数": "finals",
    "優勝回数": "championships",
    "最高タイム": "best_time",
    "出足評価": "launch",
    "行き足評価": "run",
    "回り足評価": "turn",
    "伸び足評価": "stretch",
    "展示気配評価": "exhibition",
    "総合評価": "grade",
    "直近使用選手": "last_racer",
    "交換部品": "parts_exchange",
    "メモ": "memo",
}

VENUE_HEADERS = {
    "場コード": "jcd",
    "ボートレース場": "name",
    "水質": "water",
    "潮汐影響": "tide",
    "1コース1着率": "course1",
    "2コース1着率": "course2",
    "3コース1着率": "course3",
    "4コース1着率": "course4",
    "5コース1着率": "course5",
    "6コース1着率": "course6",
    "逃げ率": "escape",
    "差し率": "sashi",
    "まくり率": "makuri",
    "まくり差し率": "makurisashi",
    "荒れ指数": "volatility",
    "風の影響": "wind",
    "特徴": "feature",
    "メモ": "memo",
}


def _text(value):
    return str(value or "").strip()


def _number(value):
    s = _text(value).replace(",", "")
    if not s:
        return None
    if s.endswith("%"):
        s = s[:-1]
    try:
        out = float(s)
    except ValueError:
        return None
    return out if math.isfinite(out) else None


def _integer(value):
    n = _number(value)
    return int(n) if n is not None else None


def _record(headers, row):
    return {headers[i]: row[i] if i < len(row) else "" for i in range(len(headers))}


def _compact(value):
    return {k: v for k, v in value.items() if v not in (None, "")}


def _require_headers(headers, required, sheet):
    missing = [name for name in required if name not in headers]
    if missing:
        raise RuntimeError(f"{sheet}: missing required headers: {missing}")


def _parse_players(values):
    if not values:
        return {}
    headers = values[0]
    _require_headers(headers, PLAYER_HEADERS, "選手データ")
    out = {}
    for row in values[1:]:
        raw = _record(headers, row)
        rid = _text(raw.get("登録番号"))
        name = _text(raw.get("選手名"))
        if not rid or not name:
            continue
        course = [_number(raw.get(f"{i}コース1着率")) for i in range(1, 7)]
        item = _compact({
            "name": name,
            "class": _text(raw.get("級別")),
            "branch": _text(raw.get("支部")),
            "win": _number(raw.get("勝率")),
            "course_win": course,
            "escape": _number(raw.get("逃げ率")),
            "sashi": _number(raw.get("差し率")),
            "makuri": _number(raw.get("まくり率")),
            "makurisashi": _number(raw.get("まくり差し率")),
            "avg_st": _number(raw.get("平均ST")),
            # These sparse ratings are used only as small PT2 tie-breaker factors.
            "maintenance_grade": _number(raw.get("モーター整備力")),
            "propeller_grade": _number(raw.get("ペラ調整力")),
            "weak_motor_recovery": _number(raw.get("弱機立て直し力")),
            "weak_motor_samples": _integer(raw.get("弱機立て直しサンプル数")),
            "maintenance_improvement": _number(raw.get("整備改善値")),
            "propeller_improvement": _number(raw.get("ペラ改善値")),
            "maintenance_samples": _integer(raw.get("整備サンプル数")),
            "propeller_samples": _integer(raw.get("ペラサンプル数")),
        })
        out[rid] = item
    return out


def _parse_motors(values):
    if not values:
        return {}
    headers = values[0]
    _require_headers(headers, MOTOR_HEADERS, "モーターデータ")
    out = {}
    for row in values[1:]:
        raw = _record(headers, row)
        jcd = _integer(raw.get("場コード"))
        motor = _integer(raw.get("モーターNo."))
        venue = _text(raw.get("ボートレース場"))
        if jcd is None or motor is None or not venue:
            continue
        key = f"{jcd:02d}:{motor}"
        out[key] = _compact({
            "venue": venue,
            "motor": motor,
            "start": _text(raw.get("使用開始日")),
            "as_of": _text(raw.get("更新基準日")),
            "win": _number(raw.get("勝率")),
            "top2": _number(raw.get("2連率")),
            "top3": _number(raw.get("3連率")),
            "firsts": _integer(raw.get("1着数")),
            "seconds": _integer(raw.get("2着数")),
            "thirds": _integer(raw.get("3着数")),
            "starts": _integer(raw.get("出走数")),
            "finals": _integer(raw.get("優出回数")),
            "championships": _integer(raw.get("優勝回数")),
            "best_time": _text(raw.get("最高タイム")),
            "launch": _text(raw.get("出足評価")).upper(),
            "run": _text(raw.get("行き足評価")).upper(),
            "turn": _text(raw.get("回り足評価")).upper(),
            "stretch": _text(raw.get("伸び足評価")).upper(),
            "exhibition": _text(raw.get("展示気配評価")).upper(),
            "grade": _text(raw.get("総合評価")).upper(),
        })
    return out


def _parse_venues(values):
    if not values:
        return {}
    headers = values[0]
    _require_headers(headers, VENUE_HEADERS, "24場データ")
    out = {}
    for row in values[1:]:
        raw = _record(headers, row)
        jcd = _integer(raw.get("場コード"))
        name = _text(raw.get("ボートレース場"))
        if jcd is None or not name:
            continue
        key = f"{jcd:02d}"
        # 24場データ contains additional venue-coded sections below the
        # canonical first 24-row table. Keep the first complete venue record
        # instead of letting later auxiliary rows overwrite it.
        if key in out:
            continue
        out[key] = {
            "name": name,
            "water": _text(raw.get("水質")),
            "tide": _text(raw.get("潮汐影響")),
            "course_win": [_number(raw.get(f"{i}コース1着率")) for i in range(1, 7)],
            "escape": _number(raw.get("逃げ率")),
            "sashi": _number(raw.get("差し率")),
            "makuri": _number(raw.get("まくり率")),
            "makurisashi": _number(raw.get("まくり差し率")),
            "volatility": _number(raw.get("荒れ指数")),
            "wind": _text(raw.get("風の影響")),
            "feature": _text(raw.get("特徴")),
            "memo": _text(raw.get("メモ")),
        }
    return out


def _validate(players, motors, venues):
    errors = []
    if len(players) < MIN_PLAYERS:
        errors.append(f"players={len(players)} < {MIN_PLAYERS}")
    if len(motors) < MIN_MOTORS:
        errors.append(f"motors={len(motors)} < {MIN_MOTORS}")
    if len(venues) < MIN_VENUES:
        errors.append(f"venues={len(venues)} < {MIN_VENUES}")
    bad_venue_codes = sorted(k for k in venues if not (k.isdigit() and 1 <= int(k) <= 24))
    if bad_venue_codes:
        errors.append(f"invalid venue codes={bad_venue_codes[:10]}")
    if errors:
        raise RuntimeError("PT2 DB snapshot safety check failed: " + "; ".join(errors))


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as tmp:
        tmp.write(payload)
        tmp.flush()
        os.fsync(tmp.fileno())
        temp_name = tmp.name
    os.replace(temp_name, path)


def main():
    import gspread
    from google.oauth2.service_account import Credentials

    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON secret is required")
    info = json.loads(raw)
    creds = Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
    )
    book = gspread.authorize(creds).open_by_key(SPREADSHEET_ID)

    players = _parse_players(book.worksheet("選手データ").get_all_values())
    motors = _parse_motors(book.worksheet("モーターデータ").get_all_values())
    venues = _parse_venues(book.worksheet("24場データ").get_all_values())
    _validate(players, motors, venues)

    snapshot_at = datetime.now(JST).isoformat()
    meta = {
        "source": "Google Sheets 競艇AI データベース",
        "spreadsheet_id": SPREADSHEET_ID,
        "snapshot_at": snapshot_at,
        "scope": "full player/motor/24-venue snapshot",
        "player_count": len(players),
        "motor_count": len(motors),
        "venue_count": len(venues),
        "schema_version": "pt2-sheet-db-v2",
    }

    _write_json(ROOT / "players.json", players)
    _write_json(ROOT / "motors.json", motors)
    _write_json(ROOT / "venues.json", venues)
    _write_json(ROOT / "meta.json", meta)

    print(json.dumps(meta, ensure_ascii=False))


if __name__ == "__main__":
    main()
