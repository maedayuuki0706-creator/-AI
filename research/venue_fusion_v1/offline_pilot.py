"""Archived pre-deadline official Main-core + Yuuki + venue comparison.

This is COUNTERFACTUAL, calculated after races are finished. It never edits
the original cards or runs official web requests. Receipts verify only the
original research card, NOT the new core/main+Yuuki cards.

No wager/Discord/X/GAS/Sheets/deployment side effects. Historical result is
used only for an isolated grader AFTER three cards are generated.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
import json

from prediction_engine import analyze_race
from research.scenario_v2 import engine as scenario
from research.venue_specialists_v1 import engine as venue
from . import engine as hybrid
from .official_program import from_frozen_official

LABELS=(
    "original_venue_v1",
    "official_main_core",
    "official_main_core_plus_yuuki",
    "official_main_core_plus_yuuki_plus_venue"
)


def build_offline(snapshot, *, generated_at=None):
    # The source may be a dated research original; NEVER stamp this as
    # a real delivery/foreseen deployment.
    original=from_frozen_official(snapshot)
    if generated_at is None:
        generated_at=datetime.now(scenario.JST).isoformat()
    core=analyze_race(original["payload"])
    if core["model_version"]!=hybrid.EXPECTED_MAIN_VERSION:
        raise ValueError("Main production ranker changed")
    ranked=hybrid._ordered_cards(core["trifecta"])
    yuuki=hybrid._build_with_ranking(snapshot,ranked,mode="replay",now=generated_at)
    venue_record=venue.analyze(snapshot,mode="replay",now=generated_at)
    enhanced,active=hybrid._venue_adjust(ranked,venue_record["lane_audits"])
    final=(hybrid._build_with_ranking(snapshot,enhanced,mode="replay",now=generated_at)
           if active else yuuki)
    picks={
        "official_main_core":[r["combination"] for r in ranked[:10]],
        "official_main_core_plus_yuuki":hybrid._card(yuuki),
        "official_main_core_plus_yuuki_plus_venue":hybrid._card(final),
    }
    if any(len(v)!=10 or len(set(v))!=10 for v in picks.values()):
        raise ValueError("Ten-ticket research contract broken")
    return {
        "version":"original-main-core-plus-yuuki-plus-venue-retro-study-v1",
        "research_only":True,
        "status":"retrospective_replay",
        "count_as_prospective":False,
        "source_input_digest":scenario.digest(snapshot),
        "source_identity":original["meta"],
        "main_model_version":core["model_version"],
        "main_full_delivery_parity":False,
        "main_core_missing_enrichment":original["limitations"],
        "scenario_digest":yuuki["digest"],
        "venue_digest":venue_record["digest"],
        "venue_validated_adjustment_active":active,
        "scenario_all_six":[
            {"lane":row["lane"],"win_paths":row["win_paths"],
             "loss_paths":row["loss_paths"],
             "hypotheses":[{"id":h["id"],"tactic":h["tactic"],
                            "supported_observations":h["supported_observations"],
                            "formations":[x["combination"] for x in h["formations"]]}
                           for h in row["hypotheses"]]}
            for row in yuuki["lanes"]
        ],
        "scenario_formation_candidates":yuuki["formation_candidates"],
        "main_120_rank":[r["combination"] for r in ranked],
        "main_120_probability_uncalibrated":[round(float(r["main_probability"]),10) for r in ranked],
        "main_boat_component_scores":core["boats"],
        "venue_scores":venue_record["lane_audits"],
        "cards":picks,
        "replay_generated_at":generated_at,
        "limits":[
            "This card was NOT generated/persisted before the race; it is not live performance",
            "Core uses original production main scoring function with official B/exhibition only",
            "Current point-in-time racer_profiles, previous_form and original predeadline odds were NOT captured",
            "Original specialist version remains untouched and separate from this replay",
            "Main trifecta strengths are not empirically calibrated win probabilities",
            "Venue unvalidated environment/motor coefficients remain zero",
            "All-six tactical causes are hypotheses only; actual first-mark actions require video",
        ],
    }


def checked_old(root, day, rid):
    """Require original immutable input, original forecast AND Git receipt."""
    paths={
        key:root/folder/day/(rid+".json") for key,folder in [
            ("snapshot","inputs"),("forecast","forecasts"),("receipt","receipts"),
            ("review","reviews")]}
    for key in ("snapshot","forecast","receipt"):
        if not paths[key].exists():
            raise FileNotFoundError(f"Missing original {key}")
    snap=json.loads(paths["snapshot"].read_text(encoding="utf-8"))
    forecast=json.loads(paths["forecast"].read_text(encoding="utf-8"))
    receipt=json.loads(paths["receipt"].read_text(encoding="utf-8"))
    if rid!=forecast.get("race_id") or rid!=receipt.get("race_id"):
        raise ValueError("Original race id mismatch")
    if snap["meta"]["day"]!=day or f'{day}_{str(snap["meta"]["jcd"]).zfill(2)}_{int(snap["meta"]["rno"]):02}'!=rid:
        raise ValueError("Original official input race id mismatch")
    for item in [forecast]:
        if item.get("digest")!=scenario.digest({k:v for k,v in item.items() if k!="digest"}):
            raise ValueError("Original signed forecast content changed")
    if forecast.get("snapshot_digest")!=scenario.digest(snap):
        raise ValueError("Forecast was made from different input")
    if (receipt.get("digest")!=forecast["digest"] or
        receipt.get("snapshot_digest")!=forecast["snapshot_digest"] or
        receipt.get("status")!="confirmed_before_deadline" or
        receipt.get("complete_originals_verified") is not True):
        raise ValueError("No verified predeadline immutable receipt")
    if scenario.aware(receipt["checked_at"]) >= scenario.aware(forecast["deadline_at"]):
        raise ValueError("Original remote receipt arrived after deadline")
    chosen=[v["combination"] for v in forecast["virtual_card"]]
    if len(chosen)!=10 or len(set(chosen))!=10:
        raise ValueError("Original card not ten distinct tickets")
    return snap,forecast,receipt,paths["review"]


def grade(entry, winner, payouts):
    if winner is None or payouts is None:
        return None
    result={}
    for key,card in entry["cards"].items():
        hit=winner in card
        amount=int(payouts[winner]) if hit else 0
        head,second,third=winner.split("-")
        leading={c.split("-")[0] for c in card}
        pair={"-".join(c.split("-")[:2]) for c in card}
        if hit: reason="hit"
        elif head not in leading: reason="head_missing"
        elif head+"-"+second not in pair:reason="2nd_missing_given_head"
        else:reason="3rd_missing_given_head_2nd"
        result[key]={"hit":hit,"payout_per_100_yen":amount,
                     "return_yen":amount,"stake_yen":1000,
                     "roi_pct":round(amount/10,2),"selection_reason":reason,
                     "outcome_in_scenario":winner in entry["scenario_formation_candidates"]}
    return result


def compare(days, root, *, source_sha, now=None):
    if len(source_sha)!=40:
        raise ValueError("Pin state Git SHA; do not use a moving state branch")
    allrows=[]
    rejected=[]
    for day in days:
        if not (len(day)==8 and day.isdigit()):
            raise ValueError("Day must be YYYYMMDD")
        directory=root/"receipts"/day
        if not directory.exists():
            rejected.append({"day":day,"reason":"No original receipt directory"})
            continue
        for f in sorted(directory.glob("*.json")):
            rid=f.stem
            code=rid.split("_")[1] if "_" in rid else ""
            if code not in venue.VENUES: continue
            try:
                snap,old,receipt,review_path=checked_old(root,day,rid)
                candidate=build_offline(snap,generated_at=now)
                candidate["cards"]["original_venue_v1"]=[r["combination"] for r in old["virtual_card"]]
                if candidate["source_input_digest"] != old["snapshot_digest"]:
                    raise ValueError("Post-hoc model not based on same frozen official source")
                if candidate["main_core_missing_enrichment"] is None:
                    raise ValueError("Incorrectly reported full Main-kun equivalence")
                row={
                    "race_id":rid,"day":day,"venue_code":code,
                    "venue":venue.VENUES[code]["venue"],
                    "original_forecast_digest":old["digest"],
                    "original_remote_receipt_sha":receipt["commit_sha"],
                    "original_receipt_before_deadline":True,
                    "new_cards_predeadline_received":False,
                    "source_sha":source_sha,
                    "retrospective_replay":True,
                    **candidate
                }
                if review_path.exists():
                    review=json.loads(review_path.read_text(encoding="utf-8"))
                    if (review["race_id"]!=rid or review.get("forecast_digest")!=old["digest"]
                        or review.get("confirmed_commit_sha")!=receipt["commit_sha"]):
                        raise ValueError("Official review and original receipt differ")
                    if review.get("status")=="graded" and not review.get("refund_lanes"):
                        winners=review.get("official_trifectas") or {}
                        if len(winners)!=1 or not all(v in scenario.COMBINATIONS for v in winners):
                            raise ValueError("Official reviewed outcome invalid")
                        winner=next(iter(winners))
                        payouts=winners
                        row["official_trifecta"]=winner
                        row["official_review_digest"]=review["digest"]
                        row["comparison"]=grade(row,winner,payouts)
                        row["review_status"]="graded"
                    else:
                        row["review_status"]="excluded_or_pending"
                else:
                    row["review_status"]="awaiting_official"
                allrows.append(row)
            except (ValueError,TypeError,KeyError,FileNotFoundError) as exc:
                rejected.append({"race_id":rid,"reason":str(exc)[:290],
                                 "error_type":type(exc).__name__})
    summary={"source_sha":source_sha,"dates":list(days),
             "replay_only":True,"new_prospective_predicted_races":0,
             "original_saved_inputs_seen":len(allrows)+len(rejected),
             "reconstructed":len(allrows),
             "source_or_contract_rejected":len(rejected),
             "by_venue":{},"rejection_reasons":dict(Counter(
                x["reason"].split(":")[0] for x in rejected)),
             "originals_not_modified":True}
    for code in venue.VENUES:
        selected=[x for x in allrows if x["venue_code"]==code]
        settled=[x for x in selected if x["review_status"]=="graded"]
        comparison={}
        for key in LABELS:
            n=len(settled)
            hits=sum(int(row["comparison"][key]["hit"]) for row in settled)
            amount=sum(row["comparison"][key]["return_yen"] for row in settled)
            miss=Counter(row["comparison"][key]["selection_reason"] for row in settled)
            comparison[key]={"graded":n,"hits":hits,"hit_rate_pct":round(100*hits/n,2) if n else None,
                              "hypothetical_return_yen":amount,
                              "hypothetical_stake_yen":1000*n,
                              "hypothetical_roi_pct":round(amount/(10*n),2) if n else None,
                              "miss_types":dict(miss)}
        summary["by_venue"][code]={"venue":venue.VENUES[code]["venue"],
                                   "reconstructed":len(selected),"graded":len(settled),
                                   "comparison":comparison}
    return summary,allrows,rejected


def summary_markdown(summary):
    out=["# 4場研究｜本物の締切前公式原本からメイン君の核＋新ゆうき＋場別を再計算","",
         "**注意：今回の改良カードは締切後に計算した反実仮想。配信・事前保存した予想の的中率ではない。**","",
         f"- 研究元Git SHA: {summary['source_sha']}",
         f"- 再計算できたレース: {summary['reconstructed']} / 入力記録 {summary['original_saved_inputs_seen']}",
         f"- 取得元/同期の制約で除外: {summary['source_or_contract_rejected']}レース",
         "- 出走表と展示の公式HTMLを**同じ当該レースで、締切前に保存されたもの**から再解析。",
         "- 既存 Main-kun と同じ予想関数を直接使用。ただし **レーサープロファイル・前日フォーム・当時オッズが未保存**なので「公式プログラムのみのMain-core」と表示。",
         "- 既存研究v1の10点は当初の予想原本＋Git受領証を検証。新しい3種類の10点には**事前の遠隔受領証がない**。",
         "- 新ゆうきの6艇勝ち筋・負け筋と2/3着候補は事前情報由来の仮説。1M映像の証拠ではない。",
         "","| 場 | 原本v1 | Main-core | Core＋新ゆうき | ＋場別 |",
         "|---|---|---|---|---|"]
    for code in ("03","16","23","06"):
        v=summary["by_venue"][code];comp=v["comparison"]
        def f(label):
            x=comp[label]
            return f'{x["hits"]}/{x["graded"]} (仮想{x["hypothetical_roi_pct"]}%)' if x["graded"] else "対象なし"
        out.append(f'| {v["venue"]} | {f("original_venue_v1")} | {f("official_main_core")} | {f("official_main_core_plus_yuuki")} | {f("official_main_core_plus_yuuki_plus_venue")} |')
    out+=["","## 予想に採用する前に必要なこと","",
          "1. レーサー成績・前日フォーム・当時オッズ・場別モーター周期などを**原本と同じ締切前に取得**し、時刻とバージョンを固定する。",
          "2. 完全再現した既存メイン君と今回の公式Main-coreの予想順位差を数値で検証する。",
          "3. 改良カードを新しいレースの締切前にリモートGitへ別保存し、受領時刻と結果を固定した**本当の並行100R→300R**で比較する。",
          "4. 1マークの勝ち筋・負け筋の原因を実進入・本番ST・6艇着順・映像で確認する。",
          "5. 未検証の場別係数は0のまま。仮想回収率が良くても事後学習・選抜のリスクとして扱う。","",
          "## 除外理由",""]
    for k,v in summary["rejection_reasons"].items():
        out.append(f"- {k}: {v}")
    return "\n".join(out)+"\n"


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--state",type=Path,required=True)
    p.add_argument("--source-sha",required=True)
    p.add_argument("--day",action="append",required=True)
    p.add_argument("--out",type=Path,required=True)
    args=p.parse_args()
    summary,rows,rejected=compare(args.day,args.state,source_sha=args.source_sha)
    args.out.mkdir(parents=True,exist_ok=True)
    for name,body in [
        ("summary.json",summary),("per_race.json",rows),("excluded.json",rejected)]:
        (args.out/name).write_text(json.dumps(body,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (args.out/"report.md").write_text(summary_markdown(summary),encoding="utf-8")
    print("FUSION_REPLAY_SUMMARY="+json.dumps(summary,ensure_ascii=False))
    print("FUSION_REPLAY_EXCLUDED="+json.dumps(rejected[:30],ensure_ascii=False))
    return summary


if __name__=="__main__":
    main()
