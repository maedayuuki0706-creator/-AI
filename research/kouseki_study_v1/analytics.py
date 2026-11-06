"""航跡: read-only, result-leakage-safe racer/course stats from archived exhibition logs.

No prediction, betting, dispatch, network or mutation of existing data.
A 'year' means records observed inside 365 days, NOT guaranteed complete coverage.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

VENUES = ('桐生','戸田','江戸川','平和島','多摩川','浜名湖','蒲郡','常滑','津','三国','びわこ','住之江','尼崎','鳴門','丸亀','児島','宮島','徳山','下関','若松','芦屋','福岡','唐津','大村')
BASE_POINTS = {1:10, 2:8, 3:6, 4:4, 5:2, 6:1}
ST_MIN, ST_MAX = 0.0, 0.99


def is_valid_id(s):
    return bool(re.fullmatch(r'\d{4}', str(s)))


def as_day(s):
    if not re.fullmatch(r'\d{8}', str(s)):
        raise ValueError('YYYYMMDD expected')
    return date.fromisoformat(f'{s[:4]}-{s[4:6]}-{s[6:8]}')


def is_six(rows):
    return (isinstance(rows, list) and len(rows) == 6 and
            sorted([r.get('lane') for r in rows]) == [1,2,3,4,5,6] and
            len({str(r.get('racer_id')) for r in rows}) == 6 and
            all(is_valid_id(r.get('racer_id')) for r in rows))


def iter_races(folder: Path, cutoff_day: str):
    """Strictly earlier calendar dates. Never use result from target day."""
    target = as_day(cutoff_day)
    for p in sorted(folder.glob('[0-9]'*8 + '/[0-9][0-9]_[0-9][0-9].json')):
        try:
            d = as_day(p.parent.name)
            if d >= target or d < target - timedelta(days=365):
                continue
            race = json.loads(p.read_text(encoding='utf-8'))
            code = str(race.get('jcd', '')).zfill(2)
            if not race.get('settled') or not is_six(race.get('rows')) or not (1 <= int(code) <= 24):
                continue
            if str(race.get('day')) != p.parent.name:
                continue
            for b in race['rows']:
                finish, course = b.get('finish'), b.get('actual_course')
                # F/失格/etc need their own denominators; exclude until explicitly modeled.
                if type(finish) is not int or type(course) is not int or not (1 <= finish <= 6 and 1 <= course <= 6):
                    continue
                st = b.get('actual_st')
                st = float(st) if type(st) in (int, float) and math.isfinite(float(st)) and ST_MIN <= st <= ST_MAX else None
                yield {'day':d.isoformat(),'race':int(race.get('rno',0)), 'venue':code,
                       'racer_id':str(b['racer_id']), 'name':str(b.get('name','')),
                       'lane':b['lane'], 'course':course, 'finish':finish, 'st':st,
                       'grade':str(b.get('current_class') or ''),'source_path':str(p.relative_to(folder))}
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            continue


def wilson(successes, n, z=1.96):
    if n == 0:
        return None
    p = successes/n
    div = 1+z*z/n
    center=(p+z*z/(2*n))/div
    spread=(z/div)*math.sqrt(p*(1-p)/n+z*z/(4*n*n))
    return [round(max(0,100*(center-spread)),1),round(min(100,100*(center+spread)),1)]


def summarize(rows):
    n=len(rows)
    if not n:
        return {'n':0,'win_rate_points_basic':None,'first_pct':None,'second_pct':None,
                'third_pct':None,'top3_pct':None,'st_mean':None,'st_sd':None,
                'st_fast_015_pct':None,'st_n':0,'top3_wilson95':None,'first_wilson95':None}
    counts=[sum(1 for r in rows if r['finish']==i) for i in (1,2,3)]
    st=[r['st'] for r in rows if r['st'] is not None]
    mean=sum(st)/len(st) if st else None
    return {
        'n':n,
        # No SG/G1/G2/final bonuses available in this log; never mislabel as official rate.
        'win_rate_points_basic':round(sum(BASE_POINTS[r['finish']] for r in rows)/n,2),
        'first_pct':round(100*counts[0]/n,1),
        'second_pct':round(100*counts[1]/n,1),
        'third_pct':round(100*counts[2]/n,1),
        'top3_pct':round(100*sum(counts)/n,1),
        'st_mean':round(mean,3) if mean is not None else None,
        'st_sd':round(math.sqrt(sum((x-mean)**2 for x in st)/len(st)),3) if st else None,
        'st_fast_015_pct':round(100*sum(x<=0.15 for x in st)/len(st),1) if st else None,
        'st_n':len(st),
        'top3_wilson95':wilson(sum(counts),n),
        'first_wilson95':wilson(counts[0],n),
    }


def recent(rows,n=10):
    return sorted(rows,key=lambda x:(x['day'],x['race'],x['venue']),reverse=True)[:n]


def select(rows, *, racer_id=None, course=None, venue=None):
    return [r for r in rows if (racer_id is None or r['racer_id']==str(racer_id))
            and (course is None or r['course']==course)
            and (venue is None or r['venue']==str(venue).zfill(2))]


def insights(short, annual, venue_benchmark):
    """Descriptive evidence only; not a causal discovery or calibrated prediction."""
    statements=[]
    if short['n']>=6 and annual['n']>=20:
        diff=round(short['top3_pct']-annual['top3_pct'],1)
        if abs(diff)>=15:
            statements.append({'kind':'recent_vs_year','diff_pp':diff,
                'text':f'直近10走の3連対率は収録された過去1年の同コース実績より{abs(diff):.1f}ポイント'+('高い' if diff>0 else '低い'),
                'n_short':short['n'],'n_year':annual['n'],'verified_out_of_sample':False})
    if annual['n']>=20 and venue_benchmark['n']>=50:
        diff=round(annual['top3_pct']-venue_benchmark['top3_pct'],1)
        if abs(diff)>=10:
            statements.append({'kind':'vs_venue_course','diff_pp':diff,
                'text':f'全国の同コース3連対率は、当地の同コース平均より{abs(diff):.1f}ポイント'+('高い' if diff>0 else '低い')+'（異なる集団の比較）',
                'n_player':annual['n'],'n_benchmark':venue_benchmark['n'],'verified_out_of_sample':False})
    return statements


def build_report(archive: Path, target: Path):
    t=json.loads(target.read_text(encoding='utf-8'))
    day=str(t['day']); venue=str(t['jcd']).zfill(2); rno=int(t['rno'])
    as_day(day)
    if venue not in [f'{i:02d}' for i in range(1,25)] or not 1<=rno<=12 or not is_six(t.get('rows')):
        raise ValueError('Invalid target race / racer IDs')
    history=list(iter_races(archive,day))
    by_course={c:select(history,course=c) for c in range(1,7)}
    racers=[]
    for b in sorted(t['rows'],key=lambda v:v['lane']):
        rid=str(b['racer_id']); assumed_course=b.get('exhibition_course')
        if type(assumed_course) is not int or not 1 <= assumed_course <= 6:
            assumed_course=b['lane']
        courses=[]
        for c in range(1,7):
            player_course=select(history,racer_id=rid,course=c)
            venue_course=select(by_course[c],venue=venue)
            short=summarize(recent(player_course))
            year=summarize(player_course)
            local=summarize(select(player_course,venue=venue))
            benchmark=summarize(venue_course)
            courses.append({'course':c,'recent10':short,'year_observed':year,
                            'local_year_observed':local,'venue_course_benchmark':benchmark,
                            'signals':insights(short,year,benchmark)})
        racers.append({'lane':b['lane'],'assumed_course':assumed_course,
                       'racer_id':rid,'name':str(b.get('name') or ''),
                       'grade':str(b.get('current_class') or ''), 'courses':courses,
                       'ai_top3_probability':None,'ai_status':'not_calibrated',
                       'target_race_result_included':False})
    dates=sorted({r['day'] for r in history})
    return {
        'schema':'kouseki/course-comparison-v1', 'research_only':True,
        'venue_code':venue,'venue':VENUES[int(venue)-1], 'race_no':rno,'date':day,
        'historical_only':day < date.today().strftime('%Y%m%d'),
        'as_of_rule':'training races strictly before target calendar day',
        'collection_coverage':{'earliest_day':dates[0] if dates else None,
            'latest_day':dates[-1] if dates else None,'observed_days':len(dates),
            'completed_finishes_with_course':len(history),
            'one_year_complete':False,
            'caution':'既存収録分のみ。過去1年分の完全収録を意味しません。失格・F等は現在の着順率分母に含めず、公式勝率とは別物です。'},
        'columns':['actual_finish_pct','actual_course','basic_win_rate_points','actual_start_st'],
        'racer_count':6,'racers':racers,
        'interpretation_notice':'独自傾向は未検証の記述統計。AI予測確率/買い目の推奨ではありません。',
        'source':'GitHub research snapshot / data/exhibition_log, official result-linked rows',
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--archive',type=Path,default=Path('data/exhibition_log'))
    ap.add_argument('--target',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args()
    report=build_report(args.archive,args.target)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f"report={args.out} venue={report['venue']} {report['race_no']}R past_entries={report['collection_coverage']['completed_finishes_with_course']}")

if __name__=='__main__':
    main()
