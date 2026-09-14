from collections import defaultdict
from datetime import datetime
from pathlib import Path
import json

import daily_report as dr
import direct_discord_notify as base
from prediction_recap import post_confirmed, report_destination_key

# This file is intentionally safe to re-run.  Each run refreshes only races whose
# deadlines have passed and reports settled 3連単 results available at that moment.
REQUEST_ID = "20260914-1700"


def _winning_combos(result):
    return set((result or {}).get("payouts") or {})


def _hit_bucket(row, result):
    winners = _winning_combos(result)
    if not winners:
        return None
    disclosed = set(dr.disclosed_picks(row))
    hit_winners = disclosed & winners
    if not hit_winners:
        return None
    # A hit paying 10,000 yen or more is surfaced as a true 万舟 hit first.
    if any((result["payouts"].get(combo) or 0) >= 10000 for combo in hit_winners):
        return "man"
    if set(row.get("main") or []) & winners:
        return "main"
    return "mid"


def _uniform_settle(row, result):
    picks = dr.disclosed_picks(row)
    return dr.settle(
        {
            **row,
            "main": picks,
            "cover": [],
            "outsiders": [],
            "virtual_bets": [{"combination": pick, "units": 1} for pick in picks],
            "virtual_total_units": len(picks),
            "virtual_unit_yen": 100,
        },
        result,
    )


def _pct(n, d):
    return "—" if not d else f"{n / d * 100:.1f}%"


def _yen(value):
    return f"¥{int(value):,}"


def build_payload():
    now = datetime.now(base.JST)
    day = now.strftime("%Y%m%d")
    predictions = dr.read_jsonl(base.LOG_PATH)
    chosen, _ = dr.latest_predictions(predictions, day)
    results = dr.collect_results(day, chosen)

    settled = []
    venue_rows = defaultdict(list)
    for key, row in sorted(chosen.items()):
        result = results.get(key) or {"status": "pending", "payouts": {}, "refund_lanes": []}
        if result.get("status") != "settled":
            continue
        actual = dr.settle(row, result)
        uniform = _uniform_settle(row, result)
        bucket = _hit_bucket(row, result)
        payouts = list((result.get("payouts") or {}).values())
        max_payout = max(payouts) if payouts else 0
        item = {
            "row": row,
            "result": result,
            "actual": actual,
            "uniform": uniform,
            "bucket": bucket,
            "hit": bool(actual["prediction_hit"]),
            "payout": max_payout,
        }
        settled.append(item)
        venue_rows[row.get("venue") or str(row.get("jcd"))].append(item)

    hits = sum(x["hit"] for x in settled)
    main_hits = sum(x["bucket"] == "main" for x in settled)
    mid_hits = sum(x["bucket"] == "mid" for x in settled)
    man_hits = sum(x["bucket"] == "man" for x in settled)

    final_rows = [x for x in settled if x["row"].get("phase") == "final"]
    prelim_rows = [x for x in settled if x["row"].get("phase") != "final"]
    final_hits = sum(x["hit"] for x in final_rows)
    prelim_hits = sum(x["hit"] for x in prelim_rows)

    uniform_stake = sum(x["uniform"]["stake_yen"] for x in settled)
    uniform_return = sum(x["uniform"]["return_yen"] for x in settled)
    uniform_roi = uniform_return / uniform_stake * 100 if uniform_stake else None

    virtual_rows = [x for x in settled if x["actual"]["stake_yen"] > 0]
    virtual_stake = sum(x["actual"]["stake_yen"] for x in virtual_rows)
    virtual_return = sum(x["actual"]["return_yen"] for x in virtual_rows)
    virtual_roi = virtual_return / virtual_stake * 100 if virtual_stake else None

    missed_man = [x for x in settled if x["payout"] >= 10000 and not x["hit"]]
    missed_man.sort(key=lambda x: x["payout"], reverse=True)

    lines = [
        f"📊 **9/14 {now.strftime('%H:%M')} JST 中間報告**",
        f"結果確定 **{len(settled)}R**｜的中 **{hits}/{len(settled)}R（{_pct(hits, len(settled))}）**",
        f"本線 **{main_hits}R**｜中穴 **{mid_hits}R**｜万舟 **{man_hits}R**",
        f"直前更新 **{final_hits}/{len(final_rows)}R（{_pct(final_hits, len(final_rows))}）**｜暫定のまま **{prelim_hits}/{len(prelim_rows)}R（{_pct(prelim_hits, len(prelim_rows))}）**",
        f"全買い均等100円：投資 **{_yen(uniform_stake)}** → 回収 **{_yen(uniform_return)}**｜回収率 **{uniform_roi:.1f}%**" if uniform_roi is not None else "全買い均等100円：集計待ち",
        f"EV仮想投票：投資 **{_yen(virtual_stake)}** → 回収 **{_yen(virtual_return)}**｜回収率 **{virtual_roi:.1f}%**" if virtual_roi is not None else "EV仮想投票：集計待ち",
        "━━━━━━━━━━━━━━━━━━",
    ]

    preferred_order = ["戸田", "平和島", "浜名湖", "蒲郡", "常滑", "津", "三国", "びわこ", "住之江", "徳山", "下関", "若松", "芦屋", "福岡"]
    for venue in preferred_order:
        rows = venue_rows.get(venue, [])
        if not rows:
            # Still show the venue if today's prediction log contains it.
            sent = sum(1 for r in chosen.values() if r.get("venue") == venue)
            if sent:
                lines.append(f"**{venue}**　配信 {sent}R｜結果待ち")
            continue
        sent = sum(1 for r in chosen.values() if r.get("venue") == venue)
        vhits = sum(x["hit"] for x in rows)
        vm = sum(x["bucket"] == "main" for x in rows)
        vi = sum(x["bucket"] == "mid" for x in rows)
        vv = sum(x["bucket"] == "man" for x in rows)
        lines.append(f"**{venue}**　配信 {sent}R｜結果 {len(rows)}R｜的中 **{vhits}/{len(rows)}**｜本 {vm}・中 {vi}・万 {vv}")

    if missed_man:
        lines += ["━━━━━━━━━━━━━━━━━━", f"🎯 **万舟取り逃し {len(missed_man)}R**"]
        for x in missed_man[:5]:
            row = x["row"]
            result = x["result"]
            combo = max(result["payouts"], key=result["payouts"].get)
            lines.append(f"{row.get('venue')} {row.get('rno')}R｜{combo} **{_yen(result['payouts'][combo])}**")
    else:
        lines += ["━━━━━━━━━━━━━━━━━━", "🎯 **万舟取り逃し 0R**"]

    lines += [
        "",
        "※結果確定分のみ。未確定は分母外。",
        "※万舟＝3連単払戻1万円以上。本線/中穴は万舟を除いた的中を予想セクションで分類。",
    ]

    payload = {
        "embeds": [{
            "title": f"9/14 {now.strftime('%H:%M')}時点｜全場中間報告",
            "description": "\n".join(lines),
            "color": 0x176B87,
            "footer": {"text": "確定結果だけを自動集計。暫定予想と展示後の直前更新を分離集計。"},
        }],
        "allowed_mentions": {"parse": []},
    }
    meta = {
        "day": day,
        "as_of": now.strftime("%H:%M JST"),
        "confirmed_races": len(settled),
        "hits": hits,
        "hit_rate": (hits / len(settled) * 100) if settled else None,
        "main_hits": main_hits,
        "mid_hits": mid_hits,
        "man_hits": man_hits,
        "uniform_stake_yen": uniform_stake,
        "uniform_return_yen": uniform_return,
        "uniform_roi": uniform_roi,
        "virtual_stake_yen": virtual_stake,
        "virtual_return_yen": virtual_return,
        "virtual_roi": virtual_roi,
        "missed_man": len(missed_man),
    }
    return payload, meta


def main():
    payload, meta = build_payload()
    msg = post_confirmed(payload)
    Path("data").mkdir(exist_ok=True)
    with Path("data/interim_report_deliveries.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            **meta,
            "request_id": REQUEST_ID,
            "destination": report_destination_key(),
            "message_id": msg["id"],
            "sent_at": datetime.now(base.JST).isoformat(),
        }, ensure_ascii=False) + "\n")
    print(json.dumps(meta, ensure_ascii=False, sort_keys=True))
    print("Interim report acknowledged")


if __name__ == "__main__":
    main()
