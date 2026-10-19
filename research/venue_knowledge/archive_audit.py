"""Retrospective venue-mechanics exploration on already audited official K archive.

The archive is post-race. Use it ONLY to describe historical changes and
check group sizes. Never use historical K weather, actual courses, methods or
final timing as if these had been observed before the race.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import json
import math
from pathlib import Path

JCD={"03":"江戸川","16":"児島","23":"唐津","06":"浜名湖"}


def era(jcd, day):
    if jcd=="23":
        # The official venue says December 2025, NOT a precise switch day.
        if day<"2025-12-01":return "before_dec2025_pit_change"
        if day<"2026-01-01":return "excluded_transition_dec2025"
        return "after_dec2025_pit_change"
    if jcd=="06":
        # Official Hamanako motor start = Apr 9, 2026. This is a motor ERA,
        # NOT proof that every historical motor entry belongs to that unit.
        return "before_current_motor_20260409" if day<"2026-04-09" else "current_motor_period_20260409"
    return "no_structural_era_asserted"


def wind_band(v):
    if isinstance(v,bool):return "unknown"
    try:
        x=float(v)
    except (ValueError,TypeError):return "unknown"
    if not math.isfinite(x) or x<0:return "unknown"
    return "0-1m" if x<=1 else "2-3m" if x<=3 else "4-5m" if x<=5 else "6m+"


def summarize(records):
    if not isinstance(records,list):
        raise ValueError("Expect audited archive list")
    groups=defaultdict(list)
    seen=set()
    outcomes={}
    for row in records:
        venue=str(row.get("venue_code","")).zfill(2)
        if venue not in JCD:
            continue
        rid=row.get("race_id")
        if rid in seen or not isinstance(rid,str):
            raise ValueError("Duplicate or invalid official K race ID")
        seen.add(rid)
        day=row.get("date","")
        if not isinstance(day,str) or len(day)!=10 or day[4]!="-" or day[7]!="-":
            raise ValueError("Bad audit race date")
        # Match proven official K race and normal settlement for these stats.
        if not row.get("official_verified") or not row.get("normal_eligible"):
            continue
        win=row.get("trifecta_from_finish")
        if not isinstance(win,str) or len(win.split("-"))!=3:
            continue
        first=int(win.split("-")[0])
        if first not in range(1,7):
            raise ValueError("Bad winning lane")
        band=wind_band(row.get("wind_m"))
        period=era(venue,day)
        actual_changed=row.get("entry_changed")
        actual_changed=actual_changed if isinstance(actual_changed,bool) else None
        motor_ids=[b.get("motor_number") for b in row.get("boats",[]) if isinstance(b,dict)]
        entry=(venue,period)
        groups[entry].append((rid,day,first,actual_changed,band,motor_ids))
    for (jcd,period),data in sorted(groups.items()):
        n=len(data)
        by_head=Counter(d[2] for d in data)
        known=[d[3] for d in data if d[3] is not None]
        band_counter=Counter(d[4] for d in data)
        outcomes[f"{jcd}/{period}"]={
            "venue":JCD[jcd],"jcd":jcd,"era":period,
            "normal_graded":n,"first_lane_counts":{str(i):by_head[i] for i in range(1,7)},
            "head_lane1_pct":round(by_head[1]*100/n,2),
            "entry_changed_count_known":sum(known),
            "entry_known_count":len(known),
            "entry_changed_pct_when_known":round(100*sum(known)/len(known),2) if known else None,
            "race_days":len(set(d[1] for d in data)),
            "wind_band_counts":dict(band_counter),
            "wind_direction_checked_for_predeadline":False,
            "race_day_input_available_at_start":False,
            "motor_ids_not_evidence_of_same_physical_unit":True,
            "learned_predictive_effect":False,
            "is_transition_excluded_from_train":period=="excluded_transition_dec2025",
        }
    return {"schema":"venue-history-breaks-v1",
            "analysis_only":True,"archive_source":"BOAT RACE official B/K audited history",
            "historical_result_data_available_at_original_deadline":False,
            "groups":outcomes,
            "warnings":[
                "Retrospective K archive from AFTER race, cannot be fed into historical simulated bets as pre-deadline weather/course",
                "Karatsu official document specifies month Dec2025, not exact switch date; whole December excluded as cautious unknown transition",
                "Hamanako motor IDs across Apr9 renewal cannot be considered the same physical motor",
                "Only aggregate groups shown. Re-check within-venue race grade, time, conditions before drawing causal conclusions",
                "All groups are descriptive and retrospective, not an automatic venue coefficient",
            ]}


def markdown(res):
    out=["# 場別研究｜公式1年履歴の構造変更・条件別記述監査","",
         "**公式Kの事後確定データに基づく記述統計。締切前の予想検証でも、風・潮位の効果の証明でもない。**","",
         "| 場 | 期間区分 | 通常R | 1枠1着率 | 進入変化 / 判定R | 風6m以上 |",
         "|---|---|---:|---:|---:|---:|"]
    for row in res["groups"].values():
        out.append("| "+" | ".join([
            row["venue"],row["era"],str(row["normal_graded"]),f"{row['head_lane1_pct']}%",
            f"{row['entry_changed_count_known']}/{row['entry_known_count']}",
            str(row["wind_band_counts"].get("6m+",0))])+" |")
    out.extend(["", "## 訓練データを混ぜないためのゲート","",
                "- 唐津：2025年12月のピット位置変更前後を別集計。**12月全体は暫定的な切替月として隔離**。正確な変更日が公式に確定した場合のみ修正。",
                "- 浜名湖：2026年4月9日の新モーター開始前後を分離。同じモーター番号でも使い回しによる同一機とは扱わない。",
                "- 江戸川：河川特有の風×上げ潮/下げ潮と水位観測の位置が未結合。風速帯だけの記述統計を推論に使わない。",
                "- 児島：満潮・干潮と風向/公式レース時刻の観測点照合が未完了。公式の文章を相関係数と解釈しない。",
                "- 各群とも200R以上を見たとしても因果は確定しない。期間外の開催節単位の再評価が必要。",""])
    return "\n".join(out)


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--archive",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    args=p.parse_args()
    with gzip.open(args.archive,"rt",encoding="utf-8") as f:
        original=json.load(f)
    if len(original)!=8876:
        raise ValueError("Historic archive count changed")
    report=summarize(original)
    args.out.mkdir(parents=True,exist_ok=True)
    (args.out/"history_era.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (args.out/"history_era.md").write_text(markdown(report),encoding="utf-8")
    print("STRUCTURAL_BREAK_AUDIT="+json.dumps(report["groups"],ensure_ascii=False))


if __name__=="__main__":
    main()
