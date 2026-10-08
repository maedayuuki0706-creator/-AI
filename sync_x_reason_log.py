"""Sync X-post prediction rationale/results into Google Sheets.

Source of truth:
- data/x_post_delivery/YYYYMMDD.json (what was actually posted to X)
- referenced prediction JSONs (model rationale at posting time)
- data/prototype_scoreboard/YYYYMMDD/results/*.json (official settled result)

This job is reporting-only and must never affect prediction/delivery.
"""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

JST_DATE_FMT = "%Y%m%d"
SPREADSHEET_ID = os.getenv("BOAT_SHEET_ID", "1dbUPyfxjIRaT-G8F_LlGMX7Ld_ZB951UmF4HpW_PYJo")
SHEET_NAME = os.getenv("X_REASON_SHEET", "X予想根拠ログ")
DATA_ROOT = Path("data")

HEADER = [
    "日付","場","R","締切","投稿時刻","X投稿ID","投稿モード","点数","投稿買い目",
    "結果","払戻","的中","万舟","的中買い目","結果投稿ID","結果投稿状態",
    "AI頭1位","AI頭1位確率","AI頭2位","AI頭2位確率","Grade","選定スコア","選定理由",
    "市場タイプ","市場シグナル","頭割れ指数","的中目投稿時オッズ","的中目AI確率","的中目フェアオッズ","的中目EV",
    "的中目区分","展開パターン","攻め艇","攻め圧","イン信頼","根拠詳細","元予想ファイル","検証メモ",
]


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _pct(value):
    try:
        return round(float(value) * 100, 2)
    except (TypeError, ValueError):
        return ""


def _num(value, digits=2):
    if value in (None, ""):
        return ""
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return value


def _top_heads(heads: dict) -> list[tuple[str, float]]:
    items = []
    for lane, value in (heads or {}).items():
        try:
            items.append((str(lane), float(value)))
        except (TypeError, ValueError):
            continue
    return sorted(items, key=lambda x: x[1], reverse=True)


def _prediction_payload(row: dict) -> tuple[dict, str]:
    candidates = []
    for rec in row.get("prediction_records") or []:
        path = rec.get("path")
        if path:
            candidates.append(Path(path))
    for path in reversed(candidates):
        data = _load_json(path)
        if data:
            return data, str(path)
    return {}, ""


def _model_from_prediction(pred: dict) -> dict:
    if isinstance(pred.get("model"), dict):
        return pred["model"]
    models = pred.get("models")
    if isinstance(models, dict):
        for key in ("prototype3", "prototype2", "prototype1"):
            if isinstance(models.get(key), dict):
                return models[key]
        for value in models.values():
            if isinstance(value, dict):
                return value
    return {}


def _official_result(day: str, jcd: str, rno: int) -> tuple[str, int | str, dict]:
    path = DATA_ROOT / "prototype_scoreboard" / day / "results" / f"{day}_{jcd}_{rno:02d}.json"
    data = _load_json(path)
    payouts = ((data.get("official") or {}).get("payouts") or {})
    if payouts:
        # trifecta result file normally contains one winning combination
        winner, payout = next(iter(payouts.items()))
        try:
            payout = int(payout)
        except (TypeError, ValueError):
            pass
        return str(winner), payout, data
    return "", "", data


def _winning_metric(model: dict, winner: str) -> dict:
    if not winner:
        return {}
    for item in model.get("trifecta") or []:
        if str(item.get("combination")) == winner:
            return item
    return {}


def _pick_bucket(model: dict, winner: str, x_picks: list[str]) -> str:
    if not winner:
        return ""
    if winner in (model.get("main_picks") or []):
        return "本線"
    if winner in (model.get("cover_picks") or []):
        return "抑え"
    if winner in (model.get("longshot_picks") or []):
        return "高配当"
    if winner in x_picks:
        return "X投稿内"
    return ""


def _reason_detail(pred: dict, model: dict, winner: str) -> str:
    parts = []
    reasons = ((pred.get("selection") or {}).get("reasons") or [])
    if reasons:
        parts.append("選定=" + " / ".join(map(str, reasons)))
    boat_reasons = model.get("boat_reasons") or {}
    if winner:
        for lane in winner.split("-"):
            reason = boat_reasons.get(str(lane))
            if reason:
                parts.append(f"{lane}号艇:{reason}")
    race_shape = model.get("race_shape") or {}
    if race_shape:
        pattern = race_shape.get("pattern")
        attack_lane = race_shape.get("best_attack_lane")
        method = race_shape.get("best_attack_method")
        if pattern:
            parts.append(f"展開={pattern}")
        if attack_lane:
            parts.append(f"攻め={attack_lane}号艇" + (f"/{method}" if method else ""))
    market = model.get("market_structure") or {}
    if market:
        mt = market.get("market_type")
        if mt:
            parts.append(f"市場={mt}")
        action = market.get("actionability")
        if action:
            parts.append(f"市場判断={action}")
    return "｜".join(parts)


def build_rows(day: str) -> list[list]:
    state_path = DATA_ROOT / "x_post_delivery" / f"{day}.json"
    state = _load_json(state_path)
    receipts = state.get("x_v2_receipts") or {}
    rows = []

    prediction_receipts = []
    for key, receipt in receipts.items():
        if not str(key).startswith("prediction:") or receipt.get("status") != "sent":
            continue
        row = receipt.get("row") or {}
        if str(row.get("day") or "") != day:
            continue
        prediction_receipts.append((key, receipt, row))

    prediction_receipts.sort(key=lambda x: (str(x[2].get("jcd") or ""), int(x[2].get("rno") or 0)))

    for _, receipt, xrow in prediction_receipts:
        jcd = str(xrow.get("jcd") or "").zfill(2)
        rno = int(xrow.get("rno") or 0)
        venue = str(xrow.get("venue") or "")
        x_picks = [str(x) for x in (xrow.get("picks") or [])]
        winner, payout, scoreboard = _official_result(day, jcd, rno)
        hit = bool(winner and winner in x_picks)
        manshu = bool(hit and isinstance(payout, int) and payout >= 10000)

        pred, pred_path = _prediction_payload(xrow)
        model = _model_from_prediction(pred)
        heads = _top_heads(model.get("heads") or {})
        top1 = heads[0] if len(heads) >= 1 else ("", "")
        top2 = heads[1] if len(heads) >= 2 else ("", "")
        selection = pred.get("selection") or {}
        market = model.get("market_structure") or {}
        metric = _winning_metric(model, winner)
        race_shape = model.get("race_shape") or {}

        result_key = f"result:{day}:{jcd}:{rno}"
        result_receipt = receipts.get(result_key) or {}
        result_post_id = result_receipt.get("post_id") or (state.get("x_result_post_ids") or {}).get(f"{day}:{jcd}:{rno}") or ""
        result_status = result_receipt.get("status") or ((state.get("x_result_attempts") or {}).get(f"{day}:{jcd}:{rno}") or {}).get("status") or ("sent" if result_post_id else "")

        rows.append([
            day, venue, rno, xrow.get("deadline") or "", xrow.get("sent_at") or receipt.get("sent_at") or "",
            receipt.get("post_id") or "", xrow.get("source") or "", len(x_picks), " ".join(x_picks),
            winner, payout, "○" if hit else ("×" if winner else ""), "○" if manshu else ("×" if winner else ""),
            winner if hit else "", result_post_id, result_status,
            top1[0], _pct(top1[1]) if top1[0] else "", top2[0], _pct(top2[1]) if top2[0] else "",
            model.get("grade") or selection.get("grade") or "", _num(selection.get("score"), 1),
            " / ".join(map(str, selection.get("reasons") or [])),
            market.get("market_type") or "", _num(market.get("signal_score"), 1), _num(market.get("split_index"), 1),
            _num(metric.get("odds"), 1), _pct(metric.get("probability")), _num(metric.get("fair_odds"), 2), _num(metric.get("expected_value"), 3),
            _pick_bucket(model, winner, x_picks) if hit else "",
            race_shape.get("pattern") or "", race_shape.get("best_attack_lane") or "",
            _num(race_shape.get("attack_pressure"), 1), _num(race_shape.get("inside_trust"), 1),
            _reason_detail(pred, model, winner), pred_path,
            ("万舟的中" if manshu else "的中" if hit else "ハズレ" if winner else "未確定"),
        ])
    return rows


def main() -> int:
    day = os.getenv("TARGET_DAY") or datetime.now().strftime(JST_DATE_FMT)
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON secret is required")
    creds = Credentials.from_service_account_info(
        json.loads(raw), scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    book = gspread.authorize(creds).open_by_key(SPREADSHEET_ID)
    ws = book.worksheet(SHEET_NAME)

    rows = build_rows(day)
    existing = ws.get_all_values()
    keep = [HEADER]
    for row in existing[1:] if existing else []:
        if row and str(row[0]).strip() and str(row[0]).strip() != day:
            keep.append(row[:len(HEADER)])

    final = keep + rows
    ws.clear()
    if len(final) + 20 > ws.row_count:
        ws.add_rows(len(final) + 20 - ws.row_count)
    ws.update(final, "A1", raw=True)
    print(json.dumps({"ok": True, "day": day, "rows": len(rows)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
