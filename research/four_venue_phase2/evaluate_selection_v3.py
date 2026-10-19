"""Offline comparison of A/B weight rankings and V3 on official archive and frozen Oct19 receipts.

NO network, model training on evaluation dates, web service, Discord, X, Sheets,
or production changes. Never calls a prediction generator using post-race data.
Historical lane=course is an assumption made before reading recorded K entry.
The October19 version is explicitly post-hoc and uses only true pre-race inputs.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import gzip
import json
from pathlib import Path
import random
import statistics

from research.scenario_v2 import engine as scenario
from research.four_venue_phase2 import model as historical
from .selection_v3 import VARIANTS, historical_card, snapshot_candidates, rank_weights, choose, _scoring, miss_type, course_to_lane

JCD = {"03": "江戸川", "06": "浜名湖", "16": "児島", "23": "唐津"}
VARIANT_LABEL = {
    "ORIGINAL": "現行V1の締切前固定10点",
    "A": "学習した場別3連単頻度の上位10点",
    "B": "学習した決まり手周辺化の条件付き頻度上位10点（Phase2-Bの事前仮説加点は含まない）",
    "V3": "B学習値から同じ頭5点・同じ1-2着組2点までの10点",
}


def load_json(path):
    p = Path(path)
    if p.suffix == ".gz":
        with gzip.open(p, "rt", encoding="utf-8") as fp:
            return json.load(fp)
    return json.loads(p.read_text(encoding="utf-8"))


def manifests(folder):
    items = {}
    for code in JCD:
        m = load_json(Path(folder) / (code + ".json"))
        historical.check_model(m)
        if m["venue_code"] != code:
            raise ValueError("Model venue mismatch")
        if m["training_end"] != "2026-06-30":
            raise ValueError("Training end date changed")
        items[code] = m
    return items


def _actual_lanes(race):
    """Ground truth read only in the *evaluator*, never candidate generation."""
    if not race.get("normal_eligible") or not race.get("official_verified"):
        return None
    if race.get("dead_heat_confirmed") or race.get("cancelled"):
        return None
    boats = race.get("boats") or []
    if (len(boats) != 6 or {b.get("lane") for b in boats} != set(range(1, 7))
            or {b.get("finish") for b in boats} != set(range(1, 7))):
        return None
    byfinish = {b["finish"]: b["lane"] for b in boats}
    truth = "-".join(str(byfinish[n]) for n in (1, 2, 3))
    if truth != race.get("trifecta_from_finish"):
        raise ValueError("Official lane/finish consistency check failed: " + race["race_id"])
    return truth


def _accumulate(rows, *, cohort_field="cohort"):
    totals = {}
    for (place, cohort, variant), values in sorted(
            _by_bucket(rows, cohort_field).items()):
        n = len(values)
        k = sum(int(v["hit"]) for v in values)
        card = Counter(v["selection_type"] for v in values)
        totals[f"{place}/{cohort}/{variant}"] = {
            "venue": place, "cohort": cohort, "variant": variant,
            "judged": n, "hits": k, "hit_rate_pct": round(100*k/n, 2) if n else None,
            "miss_second": card["second_not_selected_given_head"],
            "miss_third": card["third_not_selected_given_head_and_second"],
            "miss_head": card["head_not_selected"],
            "sample_days": len({v["day"] for v in values}),
        }
        if cohort_field == "cohort" and cohort == "oct19_frozen_replay":
            totals[f"{place}/{cohort}/{variant}"]["return_yen"] = sum(v["return_yen"] for v in values)
            totals[f"{place}/{cohort}/{variant}"]["stake_yen"] = 1000*n
            totals[f"{place}/{cohort}/{variant}"]["roi_pct"] = round(sum(v["return_yen"] for v in values)/(10*n), 2) if n else None
            totals[f"{place}/{cohort}/{variant}"]["torigami_hits"] = sum(v["hit"] and v["return_yen"] < 1000 for v in values)
    return totals


def _by_bucket(rows, cohort_field):
    out=defaultdict(list)
    for r in rows:
        out[(r["venue_code"], r[cohort_field], r["variant"])].append(r)
    return out


def _row(venue, race, day, cohort, variant, card, winner, payout=None, **extras):
    hit = winner in card
    if len(card) != 10 or len(set(card)) != 10:
        raise ValueError("Fixed ten points violated")
    return {
        "venue_code": venue, "venue": JCD[venue], "race_id": race, "day": day,
        "cohort": cohort, "variant": variant, "outcome": winner,
        "hit": hit, "selection_type": miss_type(winner,card),
        "card": list(card), "return_yen": payout if hit else 0 if payout is not None else None,
        **extras,
    }


def historical_exploration(records, models):
    """Previously viewed July-Oct17 data: not untouched prospective validation."""
    precomputed = {(code,variant): historical_card(m,variant)
                   for code,m in models.items() for variant in VARIANTS}
    rows = []
    seen = set()
    for r in records:
        code = r.get("venue_code")
        if code not in models:
            continue
        day = str(r["date"]).replace("-","")
        if day <= "20260630" or day > "20261017":
            continue
        rid=r["race_id"]
        if rid in seen:
            raise ValueError("Duplicate official race: " + rid)
        seen.add(rid)
        actual = _actual_lanes(r)
        if actual is None:
            continue
        cohort = "historical_jul_sep" if day <= "20260930" else "historical_oct1_17"
        for variant in VARIANTS:
            card = precomputed[code,variant]
            rows.append(_row(code,rid,day,cohort,variant,card,actual,
                             historical_pre_race_course_identity="lane=course assumption (actual K course NEVER input)",
                             observed_entry_change_FOR_REVIEW_ONLY=r.get("entry_changed"),
                             causal_analysis_verified=False,
                             model_ready_at_race_time=False,
                             ROI_available=False))
    return rows


def frozen_oct19_replay(state, models, state_sha):
    """Run no more than 36 observed 20261019 frozen forecasts; ignore nonreceipted races."""
    if len(state_sha) != 40:
        raise ValueError("Pinned original Git SHA required")
    base = Path(state)
    reviews_dir = base/"reviews"/"20261019"
    if not reviews_dir.exists():
        raise FileNotFoundError("Frozen review directory missing")
    output, rejected = [], []
    for rpath in sorted(reviews_dir.glob("20261019_*.json")):
        reviewed=load_json(rpath)
        raceid=rpath.stem
        code=raceid.split("_")[1]
        if code not in models:
            continue
        source=base/"inputs"/"20261019"/(raceid+".json")
        forecast=base/"forecasts"/"20261019"/(raceid+".json")
        receipt=base/"receipts"/"20261019"/(raceid+".json")
        if not (source.exists() and forecast.exists() and receipt.exists()):
            rejected.append({"race_id":raceid,"reason":"Missing frozen input/forecast/receipt"})
            continue
        snap,original,sign=load_json(source),load_json(forecast),load_json(receipt)
        if (snap["meta"]["jcd"] != code or original["race_id"] != raceid
                or sign["race_id"] != raceid or reviewed["race_id"] != raceid):
            raise ValueError("Race identity mismatch: "+raceid)
        if original["digest"] != scenario.digest({k:v for k,v in original.items() if k!="digest"}):
            raise ValueError("Unverified original digest: "+raceid)
        if sign.get("status")!="confirmed_before_deadline" or sign.get("digest")!=original["digest"]:
            raise ValueError("No confirmed original receipt: "+raceid)
        if reviewed["confirmed_commit_sha"]!=sign["commit_sha"] or reviewed["forecast_digest"]!=original["digest"]:
            raise ValueError("Review/receipt mismatch: "+raceid)
        if scenario.aware(sign["checked_at"])>=scenario.aware(original["deadline_at"]):
            raise ValueError("Original saved too late: "+raceid)
        if scenario.digest(snap)!=original["snapshot_digest"]:
            raise ValueError("Frozen input content mismatch: "+raceid)
        if reviewed["status"]!="graded":
            rejected.append({"race_id":raceid,"reason":reviewed.get("exclusion_reason","not_graded")})
            continue
        wins=sorted(reviewed.get("official_trifectas") or {})
        if len(wins)!=1 or reviewed.get("refund_lanes"):
            raise ValueError("Unverified standard settlement: "+raceid)
        winner=wins[0]
        if winner not in scenario.COMBINATIONS:
            raise ValueError("Official winner invalid: "+raceid)
        payout=reviewed["official_trifectas"][winner]
        pretime=scenario.aware(snap["meta"]["captured_at"])
        manifest=models[code]
        if any(s and scenario.aware(s)>pretime for s in [manifest["fitted_at"],manifest.get("data_available_at")]):
            rejected.append({"race_id":raceid,"reason":"Model learned/available after pre-race input"})
            continue
        baseline=[row["combination"] for row in original["virtual_card"]]
        if [p for p in baseline]!=reviewed["virtual_card"]:
            raise ValueError("Original ticket disagreement: "+raceid)
        output.append(_row(code,raceid,"20261019","oct19_frozen_replay","ORIGINAL",baseline,winner,payout,
                           model_ready_at_race_time=True,original_forecast_digest=original["digest"],
                           receipt_checked_at=sign["checked_at"],experiment_generated_after_race=False,
                           actual_tactics_verified=False,exhibition_course_changed=any(x["lane"]!=x["course"] for x in snap["boats"])))
        # For all three experimental versions, the exact same signed pre-race
        # input is used. Full six-lane win/loss hypotheses + 120 candidates are
        # recomputed after the result: STRICTLY OFFLINE, not a new live forecast.
        for variant in VARIANTS:
            selection=snapshot_candidates(snap,manifest,variant,mode="replay",
                                          now=datetime.now(scenario.JST).isoformat(),
                                          strict_asof=True)
            card=[row["combination"] for row in selection["virtual_card"]]
            if selection["input_digest"] != original["snapshot_digest"]:
                raise ValueError("Candidate input digest mismatch: "+raceid)
            output.append(_row(code,raceid,"20261019","oct19_frozen_replay",variant,card,winner,payout,
                               model_ready_at_race_time=True,original_forecast_digest=original["digest"],
                               receipt_checked_at=sign["checked_at"],experiment_generated_after_race=True,
                               original_scenario_candidate_present=winner in original["formation_candidates"],
                               new_scenario_candidate_present=winner in {x["combination"] for x in selection["all_120_candidates"] if x["v2_scenario_supported"]},
                               candidate_rank=next(x["rank"] for x in selection["all_120_candidates"] if x["combination"] == winner),
                               raw_scenario_digest=selection["raw_scenario_digest"],
                               actual_tactics_verified=False,
                               exhibition_course_changed=any(x["lane"]!=x["course"] for x in snap["boats"])))
    return output,rejected


def by_day_paired(rows, compare="V3", baseline="A", seed=17, draws=1000):
    """Deterministic paired *day-cluster* diagnostic; not fresh unbiased holdout."""
    pairs=defaultdict(dict)
    for r in rows:
        if r["variant"] in [compare,baseline]:
            pairs[r["race_id"]][r["variant"]]=r
    grouped=defaultdict(list)
    for rid, item in pairs.items():
        if compare not in item or baseline not in item:
            continue
        a,b=item[compare],item[baseline]
        if a["cohort"]!=b["cohort"] or a["venue_code"]!=b["venue_code"]:
            raise ValueError("Not a paired race")
        grouped[(a["venue_code"],a["cohort"])].append((a["day"],int(a["hit"])-int(b["hit"])))
    rng=random.Random(seed)
    results={}
    for (code,cohort),v in sorted(grouped.items()):
        daymap=defaultdict(list)
        for day,delta in v:
            daymap[day].append(delta)
        days=list(sorted(daymap))
        N=sum(map(len,daymap.values()))
        observed=sum(y for _,y in v)
        distributions=[]
        for _ in range(draws):
            groups=[daymap[rng.choice(days)] for _ in days]
            distributions.append(sum(sum(g) for g in groups)/sum(map(len,groups)))
        distributions.sort()
        results[f"{code}/{cohort}/{compare}_vs_{baseline}"]={
            "paired_races":N,"race_days":len(days),
            "hit_count_difference":observed,
            "hit_rate_difference_pct":round(100*observed/N,2),
            "day_cluster_bootstrap_interval_pct":[round(100*distributions[int(draws*.025)],2),
                                                  round(100*distributions[min(draws-1,int(draws*.975))],2)],
            "warning":"Exploratory old holdout; uncertainty alone cannot establish a live improvement",
        }
    return results


def summarize(history, replay, rejected, models, source_sha):
    allrows = history+replay
    groups=_accumulate(allrows)
    comparisons={}
    for baseline in ["A","B"]:
        comparisons.update(by_day_paired(history,"V3",baseline))
        comparisons.update(by_day_paired(replay,"V3",baseline))
    recent={code:{} for code in JCD}
    for code in JCD:
        for variant in ["ORIGINAL",*VARIANTS]:
            j=groups.get(f"{code}/oct19_frozen_replay/{variant}")
            recent[code][variant]=j or {"judged":0,"hits":0,"return_yen":0,"roi_pct":None}
    return {
        "report_version":"specialist-selection-v3-first-offline-study",
        "history_source":"official historical K archive; 2025-10-18..2026-10-17, only 2026-07-01 onward evaluated",
        "history_train_end":"2026-06-30",
        "source_state_sha":source_sha,
        "venue_training_n":{c:m["training_n"] for c,m in models.items()},
        "historical":groups,
        "oct19":recent,
        "paired_uncertainty":comparisons,
        "rejected_original_races":rejected,
        "verification":{
            "all_120_pre_outcome_candidate_ranked":True,
            "fixed_10_point_cards":True,
            "heldout_archived_results_not_used_as_input":True,
            "all_actual_tactics_verified":False,
            "new_prospective_results":0,
            "untouched_historical_evaluation":False,
            "C_or_environment_coefficient_enabled":False,
            "ROI_historical_available":False
        },
        "limitations":[
            "Historical July-Oct17 comparison is retrospective and already inspected by prior researchers; not an untouched validation set",
            "Historic official K lacks frozen pre-race course; all historical selectors assume lane=course independently of actual K entry",
            "October19 uses original signed pre-race snapshots but V3 picks were generated after racing (never count as real-time forecasts)",
            "A/B here refer to historical distribution weights only; Phase2-B's supported-observation precedence is NOT reproduced",
            "Money figures from October19 standard official payouts are hypothetical result-based what-if, not real-time investment returns",
            "Full six-boat finish, actual ST, 1M attack and failure causes are not verified in frozen original postmortems",
            "No weather, tide, motor or odds coefficient was learned; future date-clustered prospective tests must precede adoption",
            "Freeing every historical 3-combination into the ranked pool improves theoretical availability but not necessarily accuracy",
        ],
    }


def report_markdown(result):
    lines=[
        "# 4場専門AI｜V3の展開候補・10点選抜・学習の並行研究",
        "",
        "**本番未採用・配信未変更・後付け研究。全点数10点×100円で比較。**",
        "",
        "## 改善内容",
        "",
        "- 共通v2仮説から外れた出目も**場別の公式過去履歴から120通りを全部順位付け**。勝ち筋の仮説は残し、形成不能と低優先度を明確に区別する。",
        "- 各場ごとの2026年6月30日以前の学習群だけから、3連単頻度と決まり手・後続2艇の条件付き頻度を学習（既存Phase2の凍結済みモデルを再利用）。",
        "- V3は条件付き学習順位から**同じ頭は最大5点・同じ1-2着ペアは最大2点**にして10点を構成。調整係数で勝率を捏造せず、出走前の公式進入だけで艇番へ写像。",
        "- レース開始後に生成したV3の買い目と、締切前に凍結された既存原本を絶対に混同しない。",
        "",
        "## 学習資料と判定条件",
        "",
        "| 場 | 学習した通常R | 学習終了 |",
        "|---|---:|---|",
    ]
    for code in ("03","16","23","06"):
        lines.append(f"| {JCD[code]} | {result['venue_training_n'][code]:,} | 2026-06-30 |")
    lines += ["","## 7〜10月の歴史データ評価（再利用済みホールドアウト：参考）","","| 場 | 群 | 方式 | 判定R | 的中 | 的中率 |","|---|---|---|---:|---:|---:|"]
    for key,r in sorted(result["historical"].items()):
        if r["cohort"]=="oct19_frozen_replay":
            continue
        lines.append(f"| {JCD[r['venue']]} | {r['cohort']} | {r['variant']} | {r['judged']} | {r['hits']} | {r['hit_rate_pct']}% |")
    lines+=["", "## 10/19締切前の保存原本を使った後付け比較", "",
            "| 場 | 既存原本 | A（場別頻度） | B（条件付き頻度） | V3（ペア・頭分散） |",
            "|---|---|---|---|---|"]
    for code in ("03","16","23","06"):
        def fmt(v):
            return f"{v['hits']}/{v['judged']}R・{v['roi_pct']}%" if v["judged"] else "対象0R"
        vals=result["oct19"][code]
        lines.append(f"| {JCD[code]} | {fmt(vals['ORIGINAL'])} | {fmt(vals['A'])} | {fmt(vals['B'])} | {fmt(vals['V3'])} |")
    lines+=["", "※10月19日のA/B/V3は実際の締切**後**に計算した比較。ROIは仮想的中時払戻/仮想1,000円、返還等は通常成績から除外。実予想として配信した成績ではありません。",
            "",
            "## ペア比較の診断（V3と同一レース）", "",
            "| 場と群 | 比較 | 的中増減 | クラスタ区間（百分点） |",
            "|---|---|---:|---|"]
    for key,d in sorted(result["paired_uncertainty"].items()):
        lines.append(f"| {key.split('/')[0]} / {key.split('/')[1]} | {key.split('/')[2]} | {d['hit_count_difference']} | {d['day_cluster_bootstrap_interval_pct']} |")
    lines += [
        "", "## 注意と次の段階", "",
        "- 過去群の全成績は**レース後に取得された資料による再利用検証**。勝ち筋の予測改善を証明するものではない。先に見た結果を再度評価しても未観測の検証にはならない。",
        "- 事前係数として風・潮位・波高・平均ST・展示タイムの重みを追加したわけではない。未検証なら重み0のまま。",
        "- 目に見える改善には、新しい未観測開催で**同じ締切・同じ10点・同じレース**の原本を別保存し、100R/300Rの途中評価と日単位の不確実性を比較する必要がある。",
        "- 1M映像・本番進入・実STのラベルは未連結。着順だけで『捲りが失敗した』『差しが入った』とは判定しない。",
        "- **浜名湖の実開催研究は10/21開始予定。10/19の0Rを成功・失敗と判定しない。**",
    ]
    return "\n".join(lines)+"\n"


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--history",type=Path,required=True,help="read-only audited_races.json.gz")
    p.add_argument("--models",type=Path,required=True)
    p.add_argument("--state",type=Path,required=True,help="read-only frozen specialist state root")
    p.add_argument("--state-sha",required=True)
    p.add_argument("--out",type=Path,required=True)
    opts=p.parse_args()
    models=manifests(opts.models)
    archive=load_json(opts.history)
    if len(archive)!=8876:
        raise ValueError("Historical official K row count drift; stop")
    history=historical_exploration(archive,models)
    replay,rejected=frozen_oct19_replay(opts.state,models,opts.state_sha)
    result=summarize(history,replay,rejected,models,opts.state_sha)
    opts.out.mkdir(exist_ok=True,parents=True)
    (opts.out/"summary.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    (opts.out/"report.md").write_text(report_markdown(result),encoding="utf-8")
    # Include every race, all cards, and immutable source identities to audit small differences.
    (opts.out/"per_race.json").write_text(json.dumps(history+replay,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"models":result["venue_training_n"],"oct19":result["oct19"],
       "historic_graded":len(history)//3,"oct19_graded":len(replay)//4,
       "rejected":rejected,"output":str(opts.out)},ensure_ascii=False))
    return result


if __name__=="__main__":
    main()
