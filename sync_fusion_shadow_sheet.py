"""Independent projection of frozen research logs into the existing four tabs.

No prediction creation, production state writes, Discord API or X API calls.
Original reference rows and B3/E3/filter formulas are never rewritten here.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import fusion_shadow as core
from discord_formation import compress_picks

BOOK_ID = "1dbUPyfxjIRaT-G8F_LlGMX7Ld_ZB951UmF4HpW_PYJo"
RACE_TAB = "🧪 新ゆうき予想_LOG"
BOAT_TAB = "🧭 新ゆうき艇別LOG"
REVIEW_TAB = "🔎 新ゆうき予想｜見直し"
OPTIONS_TAB = "新ゆうき絞込候補"
URL_ROOT = "https://github.com/maedayuuki0706-creator/-AI/blob/research-fusion-shadow-state/data/fusion_shadow"


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _join(items):
    return "／".join(str(x) for x in items if x is not None) or "未取得"


def _value(value):
    return "未取得" if value is None else str(value)


def _check(value):
    return "未確認" if value is None else "一致" if value else "不一致"


def weather_text(record):
    p = record.get("pre_race_weather") or {}
    tide = p.get("tide") or {}
    tide_label = (json.dumps(tide, ensure_ascii=False, sort_keys=True) if tide.get("available") else
                  "未取得("+str(tide.get("status", "missing"))+")")
    return (f"風速{_value(p.get('wind_speed'))}m／波高{_value(p.get('wave_cm'))}cm／"
            f"潮位・潮向{tide_label}／風向未取得／"
            f"場DB={record.get('database', {}).get('venue_volatility', '未取得')}")


def review_text(record, outcome):
    if not outcome:
        return "結果待ち。締切前固定。予想は変更しない"
    if outcome.get("excluded_reason"):
        return "採点除外: "+outcome["excluded_reason"]
    score = outcome["models"]["fusion"]
    verdict = "○ 的中" if score["hit"] else "× 不的中" if score["eligible_race"] else "判定対象外"
    review = outcome.get("scenario_review") or {}
    misses = _join(x["combination"]+":"+x["reason"] for x in review.get("miss_reasons", []))
    checks = _join(f"{x['lane']}号艇:決まり手整合={_check(x['method_matches_win_hypothesis'])},事前負け条件={_check(x['pre_loss_condition_observed'])}"
                   for x in review.get("boats", []))
    if review.get("abnormal_race_detected"):
        checks += "\n事故・失格等を含むため通常の展開学習から除外"
    elif review.get("abnormal_race_detected") is None:
        checks += "\n事故・失格の情報未取得。通常の展開学習にはまだ採用しない"
    return (f"{verdict}／仮想投資{score['stake_yen']}円／払戻{score['return_yen']}円／"
            f"回収率{100*score['return_yen']/score['stake_yen']:.1f}%\n"
            f"見落とし区分={misses}\n{checks}\n次回:{_join(review.get('next_hypotheses', []))}\n"
            "映像未照合。公式データとの整合確認であり因果は未確定")


def rows_for(record, outcome=None):
    core._verify_record(record)
    if len(record.get("boat_scenarios", [])) != 6:
        raise ValueError("Only the new six-boat research engine is projected")
    if outcome and not outcome.get("excluded_reason") and outcome.get("prediction_digest") != record["digest"]:
        raise ValueError("Evaluation changed its frozen prediction")
    log_id = record["key"]+":"+record["version"]
    day = record["day"]
    date = f"{day[:4]}-{day[4:6]}-{day[6:]}"
    model, scenarios = record["models"]["fusion"], record["boat_scenarios"]
    link = f"{URL_ROOT}/predictions/{day}/{record['key']}.json"
    wins = "\n".join(f"{s['lane']}号艇：{_join(s['win_paths'])}。条件：{_join(s['win_conditions'])}" for s in scenarios)
    losses = "\n".join(f"{s['lane']}号艇：{_join(s['loss_paths'])}" for s in scenarios)
    reasons = []
    for combo, reason in record["ticket_reasons"].items():
        p2, p3 = reason["second_given_head"], reason["third_given_head_second"]
        reasons.append(f"{combo} {'本線' if reason['bucket']=='main' else '抑え'}／確率{reason['probability']:.2%}／"
                       f"頭条件付き2着{p2:.1%}・頭+2着条件付き3着{p3:.1%}／"
                       f"支持={_join(reason['support_families'])}／{_join(reason['head_win_path'])}")
    result = "結果待ち"
    if outcome and not outcome.get("excluded_reason"):
        official = outcome["official_result"]
        result = _join(f"{c}（{yen}円）" for c, yen in official.get("payouts", {}).items())
        if not official.get("payouts"):
            result = official["status"]
    missing = "\n".join(f"{s['lane']}号艇:{_join(s['missing_fields'])}" for s in scenarios)
    leaders = sorted(record["head_probabilities"], key=lambda l: -record["head_probabilities"][l])
    race_row = [date, record["venue"], f"{record['rno']}R", log_id,
        "新ロジック（事前固定）／"+record["version"],
        record["created_at"]+"\n締切:"+record["deadline_at"],
        "\n".join(item["text"] for item in compress_picks(model["main_picks"])),
        "\n".join(item["text"] for item in compress_picks(model["cover_picks"])),
        str(model["point_count"]), leaders[0]+"号艇",
        " / ".join(f"{l}={record['head_probabilities'][l]:.2%}" for l in sorted(leaders)),
        wins, losses, "\n".join(reasons),
        "\n".join(f"{s['lane']}号艇:{s['axis_decision']}／{s['axis_reason']}" for s in scenarios),
        "欠損:\n"+missing+"\n"+weather_text(record)+"\n確率・研究係数は未校正",
        result, review_text(record, outcome), link]
    reviews = {r["lane"]: r for r in (outcome or {}).get("scenario_review", {}).get("boats", [])} if (outcome or {}).get("scenario_review") else {}
    boat_rows = []
    for s in scenarios:
        e = s["evidence"]
        review = reviews.get(s["lane"])
        conclusion = "新ロジック・事前仮説／"+record["version"]
        if review:
            conclusion += f"\n結果:頭={'1着' if review['won'] else '1着以外'}／本番ST={_value(review['actual_st'])}／決まり手整合={_check(review['method_matches_win_hypothesis'])}／事前負け条件={_check(review['pre_loss_condition_observed'])}"
        boat_rows.append([date, record["venue"], f"{record['rno']}R", log_id,
            str(s["lane"])+"号艇", f"{s['head_probability']:.2%}",
            _join(s["win_paths"])+"\n成立条件:"+_join(s["win_conditions"]), _join(s["loss_paths"]),
            s["axis_decision"]+f" {len(s['head_tickets'])}点", s["axis_reason"]+"\n"+_join(s["evidence_notes"]),
            _value(e["average_st"]), _value(e["exhibition_st"]), _value(e["motor_top2_rate"]),
            json.dumps(e["previous_day_form"], ensure_ascii=False) if e["previous_day_form"] else "未取得（今節の全成績は未接続）",
            weather_text(record), "欠損:"+_join(s["missing_fields"])+"／DB取得:"+str(e["db_snapshot_at"]),
            conclusion, link])
    return race_row, boat_rows


def _cells(values):
    return [{"userEnteredValue": {"stringValue": str(v)}} for v in values]


def _update(sheet_id, row_index, values, col=0):
    return {"updateCells": {"range": {"sheetId": sheet_id, "startRowIndex": row_index,
        "endRowIndex": row_index+1, "startColumnIndex": col, "endColumnIndex": col+len(values)},
        "rows": [{"values": _cells(values)}], "fields": "userEnteredValue"}}


def make_plan(records, current_races, current_boats, race_id, boat_id, race_capacity=2500, boat_capacity=7000):
    def pad(row, width):
        return [str(v) for v in row]+[""]*max(0, width-len(row))
    races = [pad(r, 19) for r in current_races]
    boats = [pad(r, 18) for r in current_boats]
    def positions(rows, boat=False):
        found = {}
        for i, row in enumerate(rows):
            if not row[3]:
                continue
            key = row[3]+("|"+row[4] if boat else "")
            if key in found:
                raise ValueError("Existing duplicate log ID; no overwrite is safe")
            found[key] = i+3
        return found
    race_positions, boat_positions = positions(races), positions(boats, True)
    race_next = 3+max((i+1 for i,r in enumerate(races) if any(r)), default=0)
    boat_next = 3+max((i+1 for i,r in enumerate(boats) if any(r)), default=0)
    requests, new_races, new_boats, updates = [], 0, 0, 0
    for record, outcome in records:
        race_row, boat_rows = rows_for(record, outcome)
        log_id = race_row[3]
        if log_id in race_positions:
            index = race_positions[log_id]
            old = races[index-3]
            if old[:16] != race_row[:16] or old[18] != race_row[18]:
                raise ValueError("Frozen research projection differs from its original inputs")
            if old[16:18] != race_row[16:18]:
                requests.append(_update(race_id, index, race_row[16:18], 16))
                updates += 1
        else:
            if race_next >= race_capacity:
                raise ValueError("Research log capacity reached; existing filter bounds must be extended explicitly")
            requests += [{"copyPaste": {"source": {"sheetId":race_id,"startRowIndex":3,"endRowIndex":4,"startColumnIndex":0,"endColumnIndex":19},
                "destination": {"sheetId":race_id,"startRowIndex":race_next,"endRowIndex":race_next+1,"startColumnIndex":0,"endColumnIndex":19},
                "pasteType":"PASTE_FORMAT"}}, _update(race_id, race_next, race_row)]
            race_positions[log_id] = race_next
            while len(races) <= race_next-3:
                races.append([""]*19)
            races[race_next-3] = race_row
            race_next += 1
            new_races += 1
        for row in boat_rows:
            bkey = log_id+"|"+row[4]
            if bkey in boat_positions:
                index = boat_positions[bkey]
                old = boats[index-3]
                if old[:16] != row[:16] or old[17] != row[17]:
                    raise ValueError("Frozen six-boat projection changed")
                if old[16] != row[16]:
                    requests.append(_update(boat_id, index, [row[16]], 16))
            else:
                if boat_next >= boat_capacity:
                    raise ValueError("Six-boat log capacity reached")
                requests += [{"copyPaste": {"source": {"sheetId":boat_id,"startRowIndex":3,"endRowIndex":4,"startColumnIndex":0,"endColumnIndex":18},
                    "destination": {"sheetId":boat_id,"startRowIndex":boat_next,"endRowIndex":boat_next+1,"startColumnIndex":0,"endColumnIndex":18},
                    "pasteType":"PASTE_FORMAT"}}, _update(boat_id, boat_next, row)]
                boat_positions[bkey] = boat_next
                while len(boats) <= boat_next-3:
                    boats.append([""]*18)
                boats[boat_next-3] = row
                boat_next += 1
                new_boats += 1
    return requests, {"new_races":new_races,"new_boats":new_boats,"result_updates":updates}


def frozen_records(root):
    root = Path(root)
    records = []
    for path in sorted((root/"predictions").glob("*/*.json")):
        record = _read(path)
        if record.get("version") != core.VERSION:
            continue
        checkpoint_path = root/"checkpoints"/path.parent.name/path.name
        if not checkpoint_path.exists():
            continue
        checkpoint = _read(checkpoint_path)
        if checkpoint["prediction_digest"] != record["digest"]:
            raise ValueError("Frozen checkpoint digest mismatch")
        if not checkpoint.get("eligible_checkpoint"):
            continue
        if not core.aware(record["created_at"]) <= core.aware(checkpoint["prediction_committed_at"]) < core.aware(record["deadline_at"]):
            raise ValueError("Research projection has no valid pre-deadline save time")
        outcome_path = root/"evaluations"/path.parent.name/path.name
        outcome = _read(outcome_path) if outcome_path.exists() else None
        supplement_path = root/"official_verifications"/path.parent.name/path.name
        if supplement_path.exists():
            supplement = _read(supplement_path)
            if supplement["prediction_digest"] != record["digest"] or not outcome or supplement["original_evaluation_digest"] != core.digest(outcome):
                raise ValueError("Later official verification does not match the frozen forecast and first result")
            outcome = supplement["evaluation"]
        records.append((record, outcome))
    return records


def sync(root):
    import gspread
    from google.oauth2.service_account import Credentials
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not raw:
        raise RuntimeError("Research sheet sync needs the existing Sheets service account secret")
    creds = Credentials.from_service_account_info(json.loads(raw), scopes=["https://www.googleapis.com/auth/spreadsheets"])
    book = gspread.authorize(creds).open_by_key(BOOK_ID)
    # Metadata lookup grounds exact tabs; no sheet creation or rename.
    race, boats = book.worksheet(RACE_TAB), book.worksheet(BOAT_TAB)
    review, options = book.worksheet(REVIEW_TAB), book.worksheet(OPTIONS_TAB)
    if race.get('A3:D3') != [['日付','場','R','ログID']] or boats.get('A3:D3') != [['日付','場','R','ログID']]:
        raise ValueError("Existing research tab headers changed; no automatic rewrite")
    if review.acell("B3").value is None or review.acell("E3").value is None:
        raise ValueError("Existing review controls are missing")
    race_data = race.get(f"A4:S{min(2500,race.row_count)}")
    boat_data = boats.get(f"A4:R{min(7000,boats.row_count)}")
    requests, report = make_plan(frozen_records(root), race_data, boat_data, race.id, boats.id,
                                 min(2500,race.row_count),min(7000,boats.row_count))
    if requests:
        book.batch_update({"requests":requests})
    report.update(research_only=True, spreadsheet_id=BOOK_ID, legacy_rows_preserved=True,
                  date_dropdown="B3", venue_dropdown="E3", requests=len(requests))
    core.write_report(Path(root)/"sheet_sync.json", report)
    print(json.dumps(report, ensure_ascii=False))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    sync(args.root)


if __name__ == "__main__":
    main()
