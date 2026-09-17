"""Precision-focused postmortem for the 中穴 stream.

This does not change live picks. It measures whether the middle-odds stream is
actually becoming a higher-confidence betting feed and separates model-reading
quality from ticket-ordering misses.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from datetime import datetime

POST_DIR = Path("data/opportunity_postmortems")
OUT_DIR = Path("data/mid_precision_reviews")


def pct(num, den):
    return round(num / den * 100, 1) if den else 0.0


def roi(rows):
    stake = sum(int(r.get("point_count") or 0) * 100 for r in rows)
    returned = sum(int(r.get("payout") or 0) for r in rows if r.get("hit"))
    return {
        "stake": stake,
        "return": returned,
        "roi": round(returned / stake * 100, 1) if stake else None,
    }


def summarize(rows):
    n = len(rows)
    hits = sum(bool(r.get("hit")) for r in rows)
    money = roi(rows)
    return {
        "races": n,
        "hits": hits,
        "hit_rate": pct(hits, n),
        **money,
    }


def build(day: str) -> dict:
    src = POST_DIR / f"{day}.json"
    if not src.exists():
        raise FileNotFoundError(src)
    report = json.loads(src.read_text(encoding="utf-8"))
    rows = [r for r in report.get("rows", []) if r.get("stream") == "mid_odds"]
    target = [r for r in rows if r.get("target_band")]
    target_misses = [r for r in target if not r.get("hit")]

    exact_target = sum(bool(r.get("hit")) for r in target)
    prefix = sum(bool(r.get("prefix_match")) and not r.get("hit") for r in target)
    same_three = sum(bool(r.get("same_three_order_miss")) and not r.get("hit") for r in target)
    head = sum(bool(r.get("head_match")) and not r.get("hit") for r in target)
    two_overlap = sum(int(r.get("max_boat_overlap") or 0) >= 2 and not r.get("hit") for r in target)

    structural_close_rows = [
        r for r in target
        if r.get("hit") or r.get("prefix_match") or r.get("same_three_order_miss")
    ]
    close_misses = [
        r for r in target_misses
        if r.get("prefix_match") or r.get("same_three_order_miss")
    ]

    thresholds = {}
    for threshold in (75, 70, 65, 60, 55, 50):
        sample = [r for r in rows if int(r.get("score") or 0) >= threshold]
        thresholds[str(threshold)] = summarize(sample)

    selected = [r for r in rows if r.get("selected")]

    # Keep the most actionable misses: exact first+second, then same-three.
    near = [
        r for r in target_misses
        if r.get("prefix_match") or r.get("same_three_order_miss")
    ]
    near.sort(
        key=lambda r: (
            2 if r.get("prefix_match") else 1,
            int(r.get("payout") or 0),
            int(r.get("score") or 0),
        ),
        reverse=True,
    )

    return {
        "day": day,
        "generated_at": datetime.now().astimezone().isoformat(),
        "version": "mid-precision-review-v1",
        "all_mid": summarize(rows),
        "target_band": {
            **summarize(target),
            "capture_rate_among_target_band_results": pct(exact_target, len(target)),
            "prefix_right_third_miss": prefix,
            "same_three_order_miss": same_three,
            "head_match_miss": head,
            "two_boat_overlap_miss": two_overlap,
            "structural_close": len(structural_close_rows),
            "structural_close_rate": pct(len(structural_close_rows), len(target)),
            "close_misses": len(close_misses),
            "close_miss_share": pct(len(close_misses), len(target_misses)),
        },
        "selected_mid": summarize(selected),
        "score_thresholds": thresholds,
        "near_misses": [
            {
                "venue": r.get("venue"),
                "rno": r.get("rno"),
                "winner": r.get("winner"),
                "payout": r.get("payout"),
                "score": r.get("score"),
                "label": r.get("label"),
                "prefix_match": bool(r.get("prefix_match")),
                "same_three_order_miss": bool(r.get("same_three_order_miss")),
                "max_boat_overlap": r.get("max_boat_overlap"),
            }
            for r in near[:30]
        ],
        "interpretation_guardrails": [
            "Score-threshold results are observational and not causal.",
            "Small samples must not be used to move live thresholds immediately.",
            "Structural-close is an upper-bound diagnostic, not a guaranteed rescue with one or two swaps.",
        ],
    }


def markdown(r: dict) -> str:
    t = r["target_band"]
    a = r["all_mid"]
    s = r["selected_mid"]
    lines = [
        f"# 中穴 精度検証｜{r['day']}",
        "",
        "## 現状",
        f"- 全中穴：{a['hits']}/{a['races']}R = {a['hit_rate']:.1f}% / ROI {a['roi']:.1f}%",
        f"- 狙い配当帯の実決着：{t['races']}R、そのうち完全的中 {t['hits']}R = {t['hit_rate']:.1f}%",
        f"- 厳選中穴：{s['hits']}/{s['races']}R = {s['hit_rate']:.1f}% / ROI {s['roi']:.1f}%" if s['races'] else "- 厳選中穴：サンプルなし",
        "",
        "## 狙い配当帯での読み方",
        f"- 1・2着一致→3着抜け：{t['prefix_right_third_miss']}R",
        f"- 同じ3艇まで拾って順番違い：{t['same_three_order_miss']}R",
        f"- 頭一致の不的中：{t['head_match_miss']}R",
        f"- 完全的中＋prefix＋same-three の強い接近：{t['structural_close']}/{t['races']}R = {t['structural_close_rate']:.1f}%",
        f"- 狙い配当帯の外れのうち、prefix/same-three型：{t['close_misses']}R = {t['close_miss_share']:.1f}%",
        "",
        "## 狙い指数しきい値の観測値",
    ]
    for threshold in (75, 70, 65, 60, 55, 50):
        x = r["score_thresholds"][str(threshold)]
        lines.append(f"- {threshold}以上：{x['hits']}/{x['races']}R = {x['hit_rate']:.1f}% / ROI {x['roi']:.1f}%" if x['races'] else f"- {threshold}以上：サンプルなし")
    lines += [
        "",
        "## 改善方針",
        "- 中穴は『全レースで当てる』より、実際に買う厳選中穴の精度を最優先にする。",
        "- 1・2着まで強く読めた時は3着ブリッジ、同じ3艇が強い時は順番入替を、点数追加ではなく弱い点との交換で検証する。",
        "- ただし9/17だけで本番ロジックは変更しない。次走から候補プールを影で保存し、実際の買い目と改善案を同条件で比較する。",
        "",
        "## 惜しい中穴",
    ]
    for x in r["near_misses"][:15]:
        lines.append(f"- {x['venue']} {x['rno']}R｜{x['winner']} {int(x['payout']):,}円｜指数{x['score']}｜{x['label']}")
    return "\n".join(lines) + "\n"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--day", required=True)
    args = p.parse_args()
    r = build(args.day)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{args.day}.json").write_text(json.dumps(r, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT_DIR / f"{args.day}.md").write_text(markdown(r), encoding="utf-8")
    print(markdown(r))


if __name__ == "__main__":
    main()
