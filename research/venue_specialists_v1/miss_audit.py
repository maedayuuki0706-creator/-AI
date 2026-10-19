"""Read-only, as-of-snapshot postmortem for four venue specialist AIs.

Run:
  python -m research.venue_specialists_v1.miss_audit \
      --state /path/to/state/data/venue_specialists_v1 \
      --out /tmp/venue-miss-audit \
      --state-sha 736e40a15c40e0ad1e0b41faca04bba55bb803ef

No networking, workflow triggers, Git writes, predictions, API keys, or production imports.
The report distinguishes card selection errors from *unverified* race tactics.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path

VENUES = {"03":"江戸川", "06":"浜名湖", "16":"児島", "23":"唐津"}
LABEL = {
    "hit":"的中（通常判定）",
    "head_not_selected":"1着艇の買い目候補なし",
    "second_not_selected_given_head":"1着は買い目にあるが、実際の2着がその頭の組にない",
    "third_not_selected_given_head_and_second":"1・2着の並びはあるが、実際の3着がない",
    "not_graded":"返還・不成立などで採点除外",
}
DATES = {"20261017", "20261018", "20261019"}


def digest(obj):
    return sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True,
                  separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def ticket_parts(ticket):
    parts = str(ticket).split("-")
    if len(parts) != 3 or any(x not in "123456" or len(x) != 1 for x in parts):
        raise ValueError(f"invalid ticket {ticket!r}")
    if len(set(parts)) != 3:
        raise ValueError(f"non-distinct ticket {ticket!r}")
    return parts


def classification(winner, tickets):
    if winner in tickets:
        return "hit"
    w = ticket_parts(winner)
    if not any(x.split("-")[0] == w[0] for x in tickets):
        return "head_not_selected"
    if not any(x.split("-")[:2] == w[:2] for x in tickets):
        return "second_not_selected_given_head"
    return "third_not_selected_given_head_and_second"


def audit(root: Path, state_sha: str):
    expected_summary = read(root / "summary/latest.json")
    reviews = sorted((root / "reviews").glob("20*/*.json"))
    rows = []
    patterns = Counter()
    seen = set()
    zero_weight = Counter()
    report_totals = Counter()
    diagnostic = Counter()
    completeness = Counter()
    for path in reviews:
        race_id = path.stem
        day,jcd,rno = race_id.split("_")
        if day not in DATES or jcd not in VENUES:
            continue
        if race_id in seen:
            raise ValueError("duplicate result: "+race_id)
        seen.add(race_id)
        review = read(path)
        if review["race_id"] != race_id or review["jcd"] != jcd:
            raise ValueError("race identity mismatch: "+race_id)
        origin = root / "forecasts" / day / (race_id+".json")
        receipt_path = root / "receipts" / day / (race_id+".json")
        if not origin.exists() or not receipt_path.exists():
            raise ValueError("missing remote-frozen forecast/receipt: "+race_id)
        forecast, receipt = read(origin), read(receipt_path)
        if forecast["race_id"] != race_id or receipt["race_id"] != race_id:
            raise ValueError("forecast/receipt identity mismatch: "+race_id)
        own_digest = digest({k:v for k,v in forecast.items() if k!="digest"})
        if own_digest != forecast["digest"] or review["forecast_digest"] != own_digest or receipt["digest"] != own_digest:
            raise ValueError("frozen forecast digest mismatch: "+race_id)
        if receipt["commit_sha"] != review["confirmed_commit_sha"]:
            raise ValueError("receipt commit mismatch: "+race_id)
        if receipt["status"] != "confirmed_before_deadline":
            raise ValueError("not actually saved before deadline: "+race_id)
        if datetime.fromisoformat(receipt["checked_at"]) >= datetime.fromisoformat(forecast["deadline_at"]):
            raise ValueError("late receipt: "+race_id)
        if forecast["status"] == "retrospective_replay":
            raise ValueError("hindsight prediction: "+race_id)
        picks = [v["combination"] for v in forecast["virtual_card"]]
        if picks != review["virtual_card"]:
            raise ValueError("frozen ticket mismatch: "+race_id)
        if len(picks)!=10 or len(set(picks))!=10 or any(not ticket_parts(p) for p in picks):
            raise ValueError("bad fixed ten-ticket card: "+race_id)
        if review["stake_yen"] is not None and review["stake_yen"]!=1000:
            raise ValueError("nonstandard stake: "+race_id)
        patterns[tuple(picks)] += 1
        scores = forecast.get("lane_audits") or []
        if len(scores)!=6:
            raise ValueError("missing six-boat scoring log: "+race_id)
        if all(abs(float(b["score"])) < 1e-12 for b in scores):
            zero_weight[jcd]+=1
        else:
            diagnostic["nonzero_scores"]+=1
        env=forecast.get("environment") or {}
        if env.get("wind_speed") is not None:
            diagnostic["wind_observed"]+=1
            if float(env["wind_speed"])>=6: diagnostic["wind_6plus"]+=1
        if env.get("wind_direction") is None:diagnostic["wind_direction_unresolved"]+=1
        if (env.get("tide") or {}).get("current_measured") is False:diagnostic["tide_current_unmeasured"]+=1
        if any(b.get("course")!=b.get("lane") for b in scores):
            diagnostic["entry_changed_exhibition"]+=1

        winner_set=sorted(review.get("official_trifectas") or {})
        status=review["status"]
        row={"race_id":race_id,"venue":VENUES[jcd],"jcd":jcd,"day":day,
             "rno":int(rno),"status":status,"exclusion_reason":review.get("exclusion_reason"),
             "actual_trifectas":winner_set,"card":picks,
             "frozen_forecast_digest":own_digest,"receipt_commit":receipt["commit_sha"],
             "receipt_checked_at":receipt["checked_at"],"deadline_at":forecast["deadline_at"],
             "environment_at_capture":{"wind_speed":env.get("wind_speed"),"wave_cm":env.get("wave_cm"),
                 "wind_direction":env.get("wind_direction"),"tide":env.get("tide")},
             "all_six_scores_zero":jcd in zero_weight and abs(float(scores[0]["score"]))<1e-12,
             "full_finish_verified":bool(review.get("full_finish_verified")),
             "actual_scenario_mechanism_verified":bool(review.get("scenario_mechanism_verified")),
             "official_source_url":review.get("official_source_url"),
             "model_version":forecast.get("version"),
             "selection_policy":forecast.get("selection_policy")}
        if status=="graded":
            if len(winner_set)!=1 or review.get("refund_lanes"):
                raise ValueError("non-standard graded race: "+race_id)
            win=winner_set[0]
            kind=classification(win,picks)
            if review.get("selection")!=kind or bool(review.get("hit"))!=(kind=="hit"):
                raise ValueError("incorrect saved selection classification: "+race_id)
            best=picks[0].split("-")[0] == ticket_parts(win)[0]
            if review.get("main_head_correct") != best:
                raise ValueError("incorrect recorded main-head choice: "+race_id)
            formations=forecast.get("formation_candidates") or []
            if any(not ticket_parts(t) for t in formations):
                raise ValueError("invalid pre-race scenario candidate: "+race_id)
            included=win in formations
            candidate_head=any(x.startswith(win.split("-")[0]+"-") for x in formations)
            report_totals[(jcd,"graded")]+=1
            report_totals[(jcd,kind)]+=1
            report_totals[(jcd,"main_head_correct")]+=int(best)
            report_totals[(jcd,"winning_formation_in_candidates")]+=int(included)
            report_totals[(jcd,"winning_formation_absent_from_candidates")]+=int(not included)
            report_totals[(jcd,"stake")]+=1000
            report_totals[(jcd,"returned")]+=review["return_yen"]
            row.update({"winning":win,"selection_error":kind,
                        "main_head_correct":best,"candidate_count":len(formations),
                        "winning_candidate_pre_generated":included,
                        "winning_head_in_generated_candidates":candidate_head,
                        "stake_yen":1000,"return_yen":review["return_yen"],
                        "profit_yen":review["return_yen"]-1000,
                        "causal_label":"未確認（実際の進入・本番ST・1M映像・6艇着順詳細を未照合）"})
        elif status=="excluded":
            if review.get("hit") is not None or review.get("return_yen") is not None:
                raise ValueError("excluded record must not count as a hit or payout: "+race_id)
            report_totals[(jcd,"excluded")]+=1
            row.update({"winning":winner_set[0] if len(winner_set)==1 else None,
                        "selection_error":"not_graded","main_head_correct":None,
                        "winning_candidate_pre_generated":None,
                        "winning_head_in_generated_candidates":None,
                        "candidate_count":len(forecast.get("formation_candidates") or []),
                        "stake_yen":None,"return_yen":None,"profit_yen":None,
                        "causal_label":"採点除外（返還等）。通常の的中率/ROIには含めない"})
        else:
            raise ValueError("unknown status: "+race_id+" "+str(status))
        if not row["full_finish_verified"] and row["status"]=="graded":
            completeness["graded_without_six_boat_finish"]+=1
        if not row["actual_scenario_mechanism_verified"]:
            completeness["unverified_actual_tactics"]+=1
        rows.append(row)
    rows.sort(key=lambda r:(r["day"],r["jcd"],r["rno"]))
    current_counts=expected_summary["venues"]
    for code in VENUES:
        data=current_counts[code]
        if report_totals[(code,"graded")]!=int(data.get("graded") or 0):
            raise ValueError(f"summary/review graded count drift {code}")
        if report_totals[(code,"hit")]!=int(data.get("hits") or 0):
            raise ValueError(f"summary/review hits drift {code}")
        if report_totals[(code,"stake")]!=int(data.get("stake_yen") or 0):
            raise ValueError(f"summary/review stake drift {code}")
        if report_totals[(code,"returned")]!=int(data.get("return_yen") or 0):
            raise ValueError(f"summary/review return drift {code}")
    venues={}
    for code, name in VENUES.items():
        tally={key:report_totals[(code,key)] for key in
               ("graded","excluded","hit","head_not_selected",
                "second_not_selected_given_head","third_not_selected_given_head_and_second",
                "main_head_correct","winning_formation_in_candidates",
                "winning_formation_absent_from_candidates","stake","returned")}
        tally.update({"misses":tally["graded"]-tally["hit"],
                      "roi_pct":round(100*tally["returned"]/tally["stake"],2) if tally["stake"] else None,
                      "profit_yen":tally["returned"]-tally["stake"],
                      "all_graded_forecast_scores_zero":zero_weight[code]==tally["graded"] and tally["graded"]>0,
                      "missing_predeadline_races":current_counts[code].get("missing_count",0),
                      "missing_race_ids":current_counts[code].get("missing_race_ids",[]),
                      "operational_status":current_counts[code].get("operational_status"),
                      "started":bool(tally["graded"] or tally["excluded"])})
        venues[code]={"name":name,**tally}
    graded=sum(v["graded"] for v in venues.values())
    hits=sum(v["hit"] for v in venues.values())
    stake=sum(v["stake"] for v in venues.values())
    returned=sum(v["returned"] for v in venues.values())
    return {"report_version":"all-venue-specialists-miss-audit-v1",
            "state_sha":state_sha,"through_day":expected_summary["through_day"],
            "dataset": "official trifecta/payout + immutable research forecasts/remote receipts",
            "observational_limit":"Winning trifecta alone does not identify course change, actual ST or 1M causal mechanism.",
            "total":{"graded":graded,"hits":hits,"misses":graded-hits,
                     "hit_rate_pct":round(100*hits/graded,2) if graded else None,
                     "stake_yen":stake,"return_yen":returned,
                     "roi_pct":round(100*returned/stake,2) if stake else None,
                     "profit_yen":returned-stake,
                     "excluded":sum(v["excluded"] for v in venues.values()),
                     "second_not_selected_given_head":sum(v["second_not_selected_given_head"] for v in venues.values()),
                     "third_not_selected_given_head_and_second":sum(v["third_not_selected_given_head_and_second"] for v in venues.values()),
                     "candidate_selection_bottleneck":sum(v["winning_formation_in_candidates"]-v["hit"] for v in venues.values()),
                     "candidate_generation_bottleneck":sum(v["winning_formation_absent_from_candidates"] for v in venues.values())},
            "venues":venues,"records":rows,
            "diagnostics":{"unique_10_ticket_cards":len(patterns),
                 "most_common_cards":[{"tickets":list(p),"count":n} for p,n in patterns.most_common(8)],
                 "first_ticket_1_2_3":sum(n for p,n in patterns.items() if p and p[0]=="1-2-3"),
                 "all_zero_scores":dict(zero_weight),
                 "pre_race_environment":dict(diagnostic),
                 "completeness":dict(completeness),
                 "actual_mechanisms_verified":sum(int(r["actual_scenario_mechanism_verified"]) for r in rows)},
            "limits":["No full six-boat official finish ST/settlement tactics verified in graded set",
                      "No actual replay video reviewed",
                      "A selected first-head match does not establish correct scenario",
                      "Weather/wave correlations must not be inferred as causes",
                      "All-zero unvalidated weights imply no demonstrated venue-specific effect",
                      "Not a backtest, not a forward claim, nor realized investment returns"]}


def markdown(report):
    total=report["total"]
    lines=["# 4場専門AI｜全レースの外れ方監査（研究版）", "",
      f"原本固定SHA：\u0060{report['state_sha']}\u0060　対象：2026年10月17〜19日（締切前保存・結果確認済みのみ）", "",
      "## 先に結論",
      f"- 通常採点 **{total['graded']}R／的中{total['hits']}R／外れ{total['misses']}R**。回収率 **{total['roi_pct']}%**、仮想収支 **{total['profit_yen']:,}円**（10点×100円／R）。採点除外 **{total['excluded']}R**は別管理。",
      f"- 10点から見た落選位置：**2着の組がない {total['second_not_selected_given_head']}R**、**1・2着の組があるが3着違い {total['third_not_selected_given_head_and_second']}R**。これはあくまで券面の算術分類。",
      f"- 共通v2の事前候補に当たり3連単が存在したのに10点から漏れた **{total['candidate_selection_bottleneck']}R**、そもそも候補に存在しなかった **{total['candidate_generation_bottleneck']}R**。生成段階と選抜段階を別の研究対象にする。",
      f"- 予想カードの種類 **{report['diagnostics']['unique_10_ticket_cards']}種類**、先頭1点が1-2-3だったレース **{report['diagnostics']['first_ticket_1_2_3']}R**（採点除外含む）。分散して見えても類似した固定順の偏りがある。",
      "- 実際の1マーク、進入変更、本番ST、6艇の負け筋まで確定したレース **0件**。勝因・敗因を後付けで断定しない。",
      "",
      "## 場別の集計", "",
      "| 場 | 判定 | 的中 | 2着の組なし | 3着の組なし | v2候補は存在・10点落選 | v2候補なし | 仮想回収率 | 保存漏れ |",
      "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for code in ("03","16","23","06"):
        v=report["venues"][code]
        lines.append(f"| {v['name']} | {v['graded']} | {v['hit']} | {v['second_not_selected_given_head']} | {v['third_not_selected_given_head_and_second']} | {v['winning_formation_in_candidates']-v['hit']} | {v['winning_formation_absent_from_candidates']} | {str(v['roi_pct'])+'%' if v['roi_pct'] is not None else '未開始'} | {v['missing_predeadline_races']} |")
    lines += ["", "## 研究上の読み方",
      "1. **券面の組み立て方**：2着欠落・3着欠落は『その頭との組み合わせが10点にあるか』で判定し、戦術の失敗とは呼ばない。",
      "2. **選抜への流れ**：共通v2候補に的中目があるかと、最終10点に残ったかを分ける。候補不足か選抜不足かを先に特定する。",
      "3. **未検証係数**：場別コース率・モーター・平均ST・展示・風・潮位の未校正な係数は現状0。記録しても実際の選抜には反映されていない。場別AIの能力差をまだ証明していない。",
      "4. **環境情報**：風・波・水質は事前ログの観測値。負けた原因が強風や潮位だったと決めつけない。風向や潮流の欠測を分ける。",
      "5. **映像／公式詳細**：本番進入、実ST、1Mの攻めの起点と他艇反応は未検証。次の研究では別途取得・映像レビューが必要。",
      "6. **保存欠測**：対象場の予想未保存・返還除外は通常の外れに混ぜず、別途運用課題として計測。",
      "",
      "## 1Rずつの検証LOG",
      "",
      "| 日付 | 場 | R | 結果 | 締切前10点 | 分類 | v2候補に的中目 | 1着本命 | 風m/s | 官方結果 |",
      "|---|---|---:|---|---|---|---|---|---:|---|"]
    for r in report["records"]:
        wind=r["environment_at_capture"]["wind_speed"]
        actual=r["winning"] or "／".join(r["actual_trifectas"]) or "不明"
        url=r.get("official_source_url")
        result=f"[公式]({url})" if url else "—"
        lines.append("| "+ " | ".join([
          f"{r['day'][4:6]}/{r['day'][6:8]}",r["venue"],str(r["rno"]),
          actual,"、".join(r["card"]),LABEL[r["selection_error"]],
          ("○" if r["winning_candidate_pre_generated"] else "×") if r["winning_candidate_pre_generated"] is not None else "除外",
          ("○" if r["main_head_correct"] else "×") if r["main_head_correct"] is not None else "除外",
          str(wind) if wind is not None else "欠測",result])+" |")
    lines += ["", "### 次に実施すべき比較実験（**未実装／未検証**）",
      "- 凍結済み共通候補から **現行固定10点 vs 2・3着の条件付き候補抽出10点** を並列評価。対象同一、仮想投資同一、時系列外で検証。",
      "- 既存10点への予想後上書きは禁止。風・展示STなど未検証の係数は別の研究ブランチで条件を固定し、数値の採用基準を先に決める。",
      "- 江戸川の風・波・進入・1M映像を優先して別途突合。児島・唐津も同じ分類ルールを使う。浜名湖は10/21開始予定で現時点の採点対象なし。",
      "",
      "**本報告は自動集計された『外れた券の位置』の検証であり、各艇の実際の勝ち筋・負け筋が確認できたという意味ではない。**",
      ""]
    return "\n".join(lines)


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--state",required=True,type=Path)
    p.add_argument("--out",required=True,type=Path)
    p.add_argument("--state-sha",required=True)
    args=p.parse_args()
    report=audit(args.state,args.state_sha)
    args.out.mkdir(parents=True,exist_ok=True)
    (args.out/"miss_audit.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (args.out/"miss_audit.md").write_text(markdown(report),encoding="utf-8")
    print(json.dumps({"total":report["total"],"venues":report["venues"],"diagnostics":report["diagnostics"]},ensure_ascii=False))


if __name__=="__main__":
    main()
