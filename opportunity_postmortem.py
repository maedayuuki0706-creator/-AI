"""Postmortem analysis for 中穴AI / 穴AI calibration streams.

Reads the latest same-day opportunity predictions and settled official results,
classifies hits/near-misses separately for mid-odds and longshot streams, and
writes machine-readable + markdown reports for later threshold tuning.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import argparse
import json
from pathlib import Path

LOG_PATH = Path("data/opportunity_alert_deliveries.jsonl")
RESULT_DIR = Path("data/official_results")
OUT_DIR = Path("data/opportunity_postmortems")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _latest(day: str) -> dict[tuple[str, str, int], dict]:
    chosen = {}
    for row in _read_jsonl(LOG_PATH):
        if str(row.get("day")) != day:
            continue
        stream = str(row.get("stream") or "")
        if stream not in {"mid_odds", "longshot"}:
            continue
        jcd = str(row.get("jcd") or "").zfill(2)
        rno = int(row.get("rno") or 0)
        key = (stream, jcd, rno)
        if key not in chosen or str(row.get("sent_at") or "") >= str(chosen[key].get("sent_at") or ""):
            chosen[key] = row
    return chosen


def _winner(result: dict) -> tuple[str | None, int | None]:
    payouts = result.get("payouts") or {}
    if not payouts:
        return None, None
    combo, payout = max(payouts.items(), key=lambda item: int(item[1]))
    return str(combo), int(payout)


def _parts(combo: str) -> tuple[str, str, str] | None:
    bits = str(combo or "").split("-")
    if len(bits) != 3 or len(set(bits)) != 3:
        return None
    return bits[0], bits[1], bits[2]


def _classify(stream: str, winner: str, payout: int, picks: list[str]) -> dict:
    actual = _parts(winner)
    parsed = [p for p in (_parts(combo) for combo in picks) if p is not None]
    exact = winner in picks
    prefix = bool(actual and any(p[:2] == actual[:2] for p in parsed))
    same_three = bool(actual and any(set(p) == set(actual) and p != actual for p in parsed))
    head = bool(actual and any(p[0] == actual[0] for p in parsed))
    max_pos = 0
    max_boats = 0
    if actual:
        for p in parsed:
            max_pos = max(max_pos, sum(a == b for a, b in zip(p, actual)))
            max_boats = max(max_boats, len(set(p) & set(actual)))

    if stream == "mid_odds":
        in_band = 1200 <= payout < 8000
        if exact:
            label = "hit"
        elif prefix:
            label = "prefix_right_third_miss"
        elif same_three:
            label = "same_three_order_miss"
        elif in_band and head:
            label = "mid_band_head_right_ticket_miss"
        elif in_band and max_boats >= 2:
            label = "mid_band_two_boats_overlap"
        elif in_band:
            label = "mid_band_read_right_ticket_wrong"
        else:
            label = "mid_band_read_wrong"
    else:
        in_band = payout >= 5000
        manshu = payout >= 10000
        if exact:
            label = "hit"
        elif prefix:
            label = "prefix_right_third_miss"
        elif same_three:
            label = "same_three_order_miss"
        elif manshu and head:
            label = "manshu_head_right_ticket_miss"
        elif in_band and head:
            label = "longshot_head_right_ticket_miss"
        elif in_band and max_boats >= 2:
            label = "longshot_two_boats_overlap"
        elif in_band:
            label = "longshot_read_right_ticket_wrong"
        else:
            label = "longshot_trigger_wrong"

    return {
        "label": label,
        "hit": exact,
        "target_band": in_band,
        "prefix_match": prefix,
        "same_three_order_miss": same_three,
        "head_match": head,
        "max_position_matches": max_pos,
        "max_boat_overlap": max_boats,
    }


def _score_band(score: int) -> str:
    if score >= 85:
        return "85+"
    if score >= 75:
        return "75-84"
    if score >= 60:
        return "60-74"
    return "<60"


def _stats(rows: list[dict]) -> dict:
    n = len(rows)
    hits = sum(1 for r in rows if r["hit"])
    stake = sum(int(r.get("point_count") or 0) * 100 for r in rows)
    returned = sum(int(r["payout"]) for r in rows if r["hit"])
    labels = Counter(r["label"] for r in rows)
    bands = {}
    for band in ("85+", "75-84", "60-74", "<60"):
        sample = [r for r in rows if r["score_band"] == band]
        if sample:
            bh = sum(1 for r in sample if r["hit"])
            bs = sum(int(r.get("point_count") or 0) * 100 for r in sample)
            br = sum(int(r["payout"]) for r in sample if r["hit"])
            bands[band] = {
                "races": len(sample), "hits": bh,
                "hit_rate": round(bh / len(sample) * 100, 1),
                "roi": round(br / bs * 100, 1) if bs else None,
            }
    return {
        "races": n,
        "hits": hits,
        "hit_rate": round(hits / n * 100, 1) if n else 0.0,
        "stake_all_picks_100": stake,
        "return_all_picks_100": returned,
        "roi_all_picks_100": round(returned / stake * 100, 1) if stake else None,
        "target_band_races": sum(1 for r in rows if r["target_band"]),
        "prefix_misses": sum(1 for r in rows if not r["hit"] and r["prefix_match"]),
        "same_three_order_misses": sum(1 for r in rows if not r["hit"] and r["same_three_order_miss"]),
        "head_match_misses": sum(1 for r in rows if not r["hit"] and r["head_match"]),
        "labels": dict(labels),
        "score_bands": bands,
    }


def build(day: str) -> dict:
    result_path = RESULT_DIR / f"{day}.json"
    if not result_path.exists():
        raise FileNotFoundError(result_path)
    official = json.loads(result_path.read_text(encoding="utf-8"))
    rows = []
    for (stream, jcd, rno), pred in sorted(_latest(day).items()):
        result = official.get(f"{jcd}:{rno}") or {}
        if result.get("status") != "settled":
            continue
        winner, payout = _winner(result)
        if not winner or payout is None:
            continue
        picks = [str(p.get("combination") or "") for p in (pred.get("picks") or []) if p.get("combination")]
        cls = _classify(stream, winner, payout, picks)
        rows.append({
            "day": day,
            "stream": stream,
            "jcd": jcd,
            "venue": pred.get("venue"),
            "rno": rno,
            "score": int(pred.get("score") or 0),
            "score_band": _score_band(int(pred.get("score") or 0)),
            "confidence": pred.get("confidence"),
            "selected": bool(pred.get("selected")),
            "point_count": int(pred.get("point_count") or len(picks)),
            "winner": winner,
            "payout": payout,
            "picks": picks,
            **cls,
        })

    by_stream = {
        stream: _stats([r for r in rows if r["stream"] == stream])
        for stream in ("mid_odds", "longshot")
    }
    selected_mid = [r for r in rows if r["stream"] == "mid_odds" and r.get("selected")]
    by_stream["mid_odds"]["selected_only"] = _stats(selected_mid)

    # Useful near-miss shortlist: prioritize exact prefix, then same-three, then head+target-band.
    priority = {
        "prefix_right_third_miss": 4,
        "same_three_order_miss": 3,
        "manshu_head_right_ticket_miss": 2,
        "mid_band_head_right_ticket_miss": 2,
        "longshot_head_right_ticket_miss": 2,
        "mid_band_two_boats_overlap": 1,
        "longshot_two_boats_overlap": 1,
    }
    near = [r for r in rows if not r["hit"] and priority.get(r["label"], 0) > 0]
    near.sort(key=lambda r: (priority.get(r["label"], 0), r["payout"], r["score"]), reverse=True)

    return {
        "day": day,
        "generated_at": datetime.now().astimezone().isoformat(),
        "version": "opportunity-postmortem-v1",
        "summary": by_stream,
        "near_misses": near[:30],
        "rows": rows,
    }


def _pct(value):
    return "-" if value is None else f"{value:.1f}%"


def markdown(report: dict) -> str:
    day = report["day"]
    lines = [f"# 中穴・穴AI 反省レポート｜{day}", ""]
    for stream, title in (("mid_odds", "中穴AI"), ("longshot", "穴AI")):
        s = report["summary"][stream]
        lines += [
            f"## {title}",
            f"- 対象 {s['races']}R / 的中 {s['hits']}R / 的中率 {s['hit_rate']:.1f}%",
            f"- 全買い目各100円試算：{s['stake_all_picks_100']:,}円 → {s['return_all_picks_100']:,}円 / ROI {_pct(s['roi_all_picks_100'])}",
            f"- 狙い配当帯の実決着 {s['target_band_races']}R",
            f"- 1・2着一致→3着抜け {s['prefix_misses']}R / 同じ3艇で順番違い {s['same_three_order_misses']}R / 頭一致の不的中 {s['head_match_misses']}R",
            "",
            "### スコア帯別",
        ]
        for band in ("85+", "75-84", "60-74", "<60"):
            b = s["score_bands"].get(band)
            if b:
                lines.append(f"- {band}: {b['hits']}/{b['races']}R = {b['hit_rate']:.1f}% / ROI {_pct(b['roi'])}")
        if stream == "mid_odds":
            sel = s["selected_only"]
            lines += ["", f"### 厳選中穴だけ", f"- {sel['hits']}/{sel['races']}R = {sel['hit_rate']:.1f}% / ROI {_pct(sel['roi_all_picks_100'])}"]
        lines.append("")

    lines += ["## 惜しい外れ（学習優先）", ""]
    for r in report["near_misses"][:20]:
        label = "中穴" if r["stream"] == "mid_odds" else "穴"
        lines.append(
            f"- {label}｜{r['venue']} {r['rno']}R｜結果 {r['winner']} {r['payout']:,}円｜score {r['score']}｜{r['label']}"
        )
    lines += [
        "",
        "## 学習方針",
        "- 中穴は、狙い配当帯に入ったレースでの『頭一致』『1・2着一致』『同じ3艇』を分けて追う。",
        "- 穴は、的中率だけでなく『50倍以上を読めたか』『万舟で頭まで読めたか』を別指標にする。",
        "- 点数をむやみに増やさず、prefix / same-three の惜しい外れが多い時だけ既存点の入替候補にする。",
        "- 1日だけで閾値は変更せず、スコア帯別成績を数日蓄積してから調整する。",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", required=True)
    args = parser.parse_args()
    report = build(args.day)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{args.day}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT_DIR / f"{args.day}.md").write_text(markdown(report), encoding="utf-8")
    print(markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
