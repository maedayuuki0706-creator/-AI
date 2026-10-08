"""Sync real-time AI performance into Google Sheets.

Reads settled prototype scoreboard JSONs and writes:
- hidden リアルタイムAI成績ログ: one settled race x AI/strategy per row
- visible リアルタイムAI成績: current-day aggregate leaderboard

Reporting only; never changes prediction/delivery behavior.
"""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials

JST = ZoneInfo("Asia/Tokyo")
SPREADSHEET_ID = os.getenv("BOAT_SHEET_ID", "1dbUPyfxjIRaT-G8F_LlGMX7Ld_ZB951UmF4HpW_PYJo")
LOG_SHEET = os.getenv("LIVE_AI_LOG_SHEET", "リアルタイムAI成績ログ")
VIEW_SHEET = os.getenv("LIVE_AI_VIEW_SHEET", "リアルタイムAI成績")
ROOT = Path("data/prototype_scoreboard")

LOG_HEADER = [
    "日付","更新時刻","場","R","AI名","AI区分","点数","投資額","払戻額","収支",
    "的中","本線的中","抑え的中","万舟","トリガミ","結果","配当(倍)","race_key","データソース","モデルVersion",
]
VIEW_HEADER = ["順位","AI名","区分","確定R","的中","的中率","投資額","払戻額","回収率","収支","万舟","最高配当","本線的中","抑え的中","直近結果"]

MODEL_LABELS = {
    "prototype1": ("PT1", "PT"),
    "prototype2": ("PT2", "PT"),
    "prototype3": ("PT3／ゆうき", "PT"),
}
LEGACY_LABELS = {"main": "メインくん", "mid_odds": "中穴くん", "longshot": "穴くん"}
VENUE_NAMES = ["桐生","戸田","江戸川","平和島","多摩川","浜名湖","蒲郡","常滑","津","三国","びわこ","住之江","尼崎","鳴門","丸亀","児島","宮島","徳山","下関","若松","芦屋","福岡","唐津","大村"]
STRATEGY_LABELS = {
    "balanced": ("PT2 総合型", "PT2戦略"),
    "probability": ("PT2 本命型", "PT2戦略"),
    "value": ("PT2 妙味型", "PT2戦略"),
    "longshot": ("PT2 高配当型", "PT2戦略"),
}


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def result_files(day: str):
    folder = ROOT / day / "results"
    return sorted(folder.glob(f"{day}_*.json")) if folder.exists() else []


def model_version(data: dict, model_key: str) -> str:
    meta = (data.get("model_metadata") or {}).get(model_key) or {}
    return str(meta.get("version_label") or meta.get("model_version") or "")


def make_row(day: str, data: dict, ai_name: str, ai_type: str, m: dict, version: str) -> list:
    official = data.get("official") or {}
    payouts = official.get("payouts") or {}
    if payouts:
        winner, payout = next(iter(payouts.items()))
    else:
        winner, payout = "", 0
    try:
        payout = int(payout)
    except (TypeError, ValueError):
        payout = 0

    checked = str(official.get("checked_at") or data.get("prediction_created_at") or "")
    stake = int(m.get("stake_yen") or 0)
    ret = int(m.get("return_yen") or 0)
    hit = bool(m.get("hit"))
    main_hit = bool(m.get("main_hit"))
    cover_hit = bool(m.get("cover_hit"))
    manshu = bool(m.get("manshu"))
    torigami = bool(m.get("torigami"))
    points = int(m.get("point_count") or 0)

    return [
        day, checked, str(data.get("venue") or ""), int(data.get("rno") or 0),
        ai_name, ai_type, points, stake, ret, ret - stake,
        "○" if hit else "×", "○" if main_hit else "×", "○" if cover_hit else "×",
        "○" if manshu else "×", "○" if torigami else "×",
        winner, round(payout / 100.0, 1) if payout else 0,
        str(data.get("key") or ""), "prototype_scoreboard", version,
    ]


def build_legacy_rows(day: str) -> list[list]:
    """Score existing Discord main/mid-odds/longshot against confirmed official payouts.

    No predictions are generated or sent here. Race-level journal entries are
    compared with the already persisted official-results cache. Missing or
    unresolved races are excluded; zero deliveries are never reported as 0% ROI.
    """
    import live_status

    main, _ = live_status.base_streams(day)
    opportunities = live_status.opportunity_streams(day)
    official = live_status.load_official_cache(day)
    streams = {
        "main": main,
        "mid_odds": opportunities["mid_odds"],
        "longshot": opportunities["longshot"],
    }
    rows = []
    for stream, records in streams.items():
        for record in records.values():
            result = official.get(record["key"])
            score = live_status.score_one(record, result)
            if not score or not score["eligible"]:
                continue
            payouts = result.get("payouts") or {}
            if not payouts:
                continue
            winner, payout = max(payouts.items(), key=lambda item: int(item[1]))
            ret = int(score["return_yen"])
            stake = int(score["stake_yen"])
            jcd = str(record["jcd"]).zfill(2)
            rno = int(record["rno"])
            venue = record.get("venue") or live_status.base.VENUES.get(jcd) or jcd
            rows.append([
                day, result.get("checked_at") or record.get("sent_at") or "",
                venue, rno, LEGACY_LABELS[stream], "既存AI",
                score["point_count"], stake, ret, ret - stake,
                "○" if score["hit"] else "×", "—", "—",
                "○" if score["manshu"] else "×",
                "○" if score["torigami"] else "×",
                winner, round(int(payout) / 100, 1),
                f"{day}_{jcd}_{rno:02d}", "live_status_official", "既存AI",
            ])
    return rows


def build_day_rows(day: str) -> list[list]:
    rows = []
    for path in result_files(day):
        data = load_json(path)
        official = data.get("official") or {}
        if official.get("status") != "settled":
            continue
        models = data.get("models") or {}
        for key, (name, ai_type) in MODEL_LABELS.items():
            m = models.get(key) or {}
            if not m or m.get("eligible") is False:
                continue
            rows.append(make_row(day, data, name, ai_type, m, model_version(data, key)))
            if key == "prototype2":
                for skey, (sname, stype) in STRATEGY_LABELS.items():
                    sm = (m.get("strategies") or {}).get(skey) or {}
                    if not sm or sm.get("eligible") is False:
                        continue
                    rows.append(make_row(day, data, sname, stype, sm, model_version(data, key)))
    rows.extend(build_legacy_rows(day))
    rows.sort(key=lambda r: (r[1], r[2], r[3], r[4]))
    return rows


def aggregate(rows: list[list]) -> list[list]:
    by_ai = {}
    for r in rows:
        ai = r[4]
        a = by_ai.setdefault(ai, {
            "type": r[5], "races": 0, "hits": 0, "stake": 0, "ret": 0, "manshu": 0,
            "max_odds": 0.0, "main": 0, "cover": 0, "latest_time": "", "latest": "",
        })
        a["races"] += 1
        a["hits"] += 1 if r[10] == "○" else 0
        a["stake"] += int(r[7] or 0)
        a["ret"] += int(r[8] or 0)
        a["manshu"] += 1 if r[13] == "○" else 0
        if r[10] == "○":
            a["max_odds"] = max(a["max_odds"], float(r[16] or 0))
        a["main"] += 1 if r[11] == "○" else 0
        a["cover"] += 1 if r[12] == "○" else 0
        if str(r[1]) >= a["latest_time"]:
            a["latest_time"] = str(r[1])
            a["latest"] = f'{r[2]} {r[3]}R {r[10]} {r[15]}'

    ranked = []
    for ai, a in by_ai.items():
        hit_rate = a["hits"] / a["races"] if a["races"] else 0
        roi = a["ret"] / a["stake"] if a["stake"] else 0
        ranked.append({
            "ai": ai, **a, "hit_rate": hit_rate, "roi": roi, "profit": a["ret"] - a["stake"]
        })
    ranked.sort(key=lambda a: (a["roi"], a["hit_rate"], a["ret"]), reverse=True)

    out = []
    for idx, a in enumerate(ranked, 1):
        out.append([
            idx, a["ai"], a["type"], a["races"], a["hits"], a["hit_rate"],
            a["stake"], a["ret"], a["roi"], a["profit"], a["manshu"], a["max_odds"],
            a["main"] if a["type"] != "既存AI" else "",
            a["cover"] if a["type"] != "既存AI" else "", a["latest"],
        ])
    return out



RECENT_AI_ORDER = ["メインくん","中穴くん","穴くん","PT1","PT2","PT3／ゆうき","PT2 総合型","PT2 本命型","PT2 妙味型","PT2 高配当型"]


def build_recent_races(rows: list[list], limit: int = 20) -> list[list]:
    races = {}
    for r in rows:
        key = r[17]
        item = races.setdefault(key, {
            "time": r[1], "venue": r[2], "rno": r[3], "result": r[15],
            "odds": r[16], "ais": {},
        })
        if str(r[1]) > str(item["time"]):
            item["time"] = r[1]
        item["ais"][r[4]] = r[10]
    ordered = sorted(races.values(), key=lambda x: str(x["time"]), reverse=True)[:limit]
    out = []
    for x in ordered:
        time_text = str(x["time"])
        if "T" in time_text:
            time_text = time_text.split("T", 1)[1][:5]
        out.append([
            time_text, x["venue"], x["rno"], x["result"], x["odds"],
            *[x["ais"].get(ai, "") for ai in RECENT_AI_ORDER],
        ])
    return out


def write_log(ws, day: str, rows: list[list]) -> None:
    old = ws.get_all_values()
    keep = [LOG_HEADER]
    for row in old[1:] if old else []:
        if row and str(row[0]).strip() and str(row[0]).strip() != day:
            keep.append(row[:len(LOG_HEADER)])
    final = keep + rows
    ws.clear()
    if len(final) + 20 > ws.row_count:
        ws.add_rows(len(final) + 20 - ws.row_count)
    ws.update(final, "A1", raw=True)


def write_view(ws, day: str, rows: list[list], summary: list[list]) -> None:
    now = datetime.now(JST).isoformat()
    recent = build_recent_races(rows)
    # The venue selector / formula table lives below row 64. Never clear it.
    ws.batch_clear(["A7:O35", "A42:O61"])
    ws.update([[f"{day[:4]}/{day[4:6]}/{day[6:]}"]], "B3", raw=True)
    ws.update([[now]], "E3", raw=True)
    if summary:
        ws.update(summary, f"A7:O{6+len(summary)}", raw=True)
    if recent:
        ws.update(recent, f"A42:O{41+len(recent)}", raw=True)


def main() -> int:
    day = os.getenv("TARGET_DAY") or datetime.now(JST).strftime("%Y%m%d")
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON secret is required")
    creds = Credentials.from_service_account_info(
        json.loads(raw), scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    book = gspread.authorize(creds).open_by_key(SPREADSHEET_ID)
    rows = build_day_rows(day)
    summary = aggregate(rows)
    write_log(book.worksheet(LOG_SHEET), day, rows)
    write_view(book.worksheet(VIEW_SHEET), day, rows, summary)
    print(json.dumps({"ok": True, "day": day, "log_rows": len(rows), "ai_count": len(summary)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
