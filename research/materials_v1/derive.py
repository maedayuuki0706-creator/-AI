"""Offline descriptive histories from the already-acquired archive, no network."""
from collections import Counter,defaultdict
import argparse,gzip,json
from pathlib import Path
from .collector import Store,read,write,encode,digest,stamp,once

def derive(archive,state):
    root=Path(archive);out=Store(state);summary=read(root/'summary.json')
    groups=defaultdict(lambda:{'starts':0,'wins':0,'top2':0,'top3':0,'methods':Counter(),'st':[]})
    motors=[];flows=Counter();ids=set();eligible=0;invalid=0;registered=set();races_by_venue=Counter()
    cycles=read(root/'gaps/motor_cycles.json');official_normal=0;missing_actual_details=0
    # Catalog is evidence with bounded validity, not an assumption that a motor
    # number remains the same machine beyond the reviewed service interval.
    if isinstance(cycles,dict):cycles=cycles.get('cycles',cycles.get('motor_cycles',[]))
    for p in sorted((root/'days').glob('*.json.gz')):
        doc=json.loads(gzip.decompress(p.read_bytes()))
        for race in doc['races']:
            rid=race['race_id']
            if rid in ids:raise ValueError('Duplicate archived race: '+rid)
            ids.add(rid);code=race['venue_code'];races_by_venue[code]+=1
            if not race['official_normal_eligible']:invalid+=1;continue
            official_normal+=1
            res=race.get('api_result') or {};rs=res.get('racers') or {}
            if len(rs)!=6 or sorted(x.get('place_number') for x in rs.values())!=list(range(1,7)):
                invalid+=1;missing_actual_details+=1;continue
            eligible+=1;season=(int(race['day'][5:7])%12)//3
            wind=(race.get('preview_environment') or {}).get('wind_speed')
            bucket='missing' if wind is None else '0-1' if wind<=1 else '2-3' if wind<=3 else '4-5' if wind<=5 else '6+'
            winner=next(x for x in rs.values() if x['place_number']==1)
            second=next(x for x in rs.values() if x['place_number']==2);third=next(x for x in rs.values() if x['place_number']==3)
            method=res.get('technique_number_source') or str(res.get('technique_number'))
            flows[(code,str(winner.get('course_number')),method,str(second.get('course_number')),str(third.get('course_number')))]+=1
            for boat in race['boats']:
                lane=str(boat['lane']);b=rs.get(lane)
                if not b or str(b['number'])!=boat['racer_id']:raise ValueError('Result racer identity mismatch')
                course=b.get('course_number')
                if course not in range(1,7):continue
                registered.add(boat['racer_id']);place=b['place_number']
                dimensions=[('course',str(course)),('venue_course',code+':'+str(course)),('season_course',str(season)+':'+str(course)),('wind_course',bucket+':'+str(course))]
                for dimension,value in dimensions:
                    g=groups[(boat['racer_id'],dimension,value)];g['starts']+=1;g['wins']+=place==1;g['top2']+=place<=2;g['top3']+=place<=3
                    if place==1:g['methods'][method]+=1
                    if b.get('start_timing') is not None:g['st'].append(b['start_timing'])
                cat=[x for x in cycles if x['venue_code']==code and x['valid_from']<=race['day']<=x['valid_through']]
                c=cat[0] if len(cat)==1 else None
                motors.append({'day':race['day'],'venue_code':code,'race_no':race['race_no'],'race_id':rid,'lane':boat['lane'],'racer_id':boat['racer_id'],
                    'motor_number':boat['motor_number'],'cycle_id':c['cycle_id'] if c else None,
                    'motor_key':f"{code}:{c['cycle_id']}:{boat['motor_number']}" if c else None,'cycle_missing_reason':None if c else 'no unambiguous reviewed cycle',
                    'cycle_precision':c['start_precision'] if c else None,'parts':boat.get('parts'),'preview':boat.get('preview'),
                    'finish':place,'actual_course':course,'actual_st':b.get('start_timing'),'usage':'retrospective_research_only',
                    'source':race.get('provenance'),'observed_at':doc.get('observed_at'),'source_publish_time':None,'predictive_input_allowed':False})
    rows=[]
    for (racer,dim,value),g in sorted(groups.items()):
        n=g['starts'];rows.append({'racer_id':racer,'dimension':dim,'group':value,'denominator':n,'wins':g['wins'],'top2_count':g['top2'],'top3_count':g['top3'],
            'win_rate_pct':round(100*g['wins']/n,2),'top2_rate_pct':round(100*g['top2']/n,2),'top3_rate_pct':round(100*g['top3']/n,2),
            'winning_methods':dict(g['methods']),'method_rate_denominator':'all starts in this group; counts of wins by method',
            'mean_actual_st':round(sum(g['st'])/len(g['st']),4) if g['st'] else None,'st_denominator':len(g['st']),
            'period_start':'2025-10-18','period_end':'2026-10-17','sample_status':'small_sample' if n<30 else 'descriptive_only',
            'population':'only four target venues, official-normal matched archive; not nationwide career rates','predictive_input_allowed':False})
    for filename,value in [('racer_tendencies.json.gz',rows),('motor_race_histories.json.gz',motors)]:
        once(out.root/'derived'/filename,gzip.compress(encode(value),mtime=0))
    flowrows=[{'venue_code':k[0],'winner_actual_course':k[1],'official_winning_method':k[2],'second_actual_course':k[3],'third_actual_course':k[4],'count':v,
        'attack_origin_verified':False,'all_six_movement_verified':False} for k,v in sorted(flows.items())]
    write(out.root/'derived/result_course_associations.json',{'rows':flowrows,'warning':'Result association only; winning method does not establish attack origin, resistance, or boat movements'})
    result={'generated_at':stamp(),'archive_source_summary_sha256':digest((root/'summary.json').read_bytes()),'reused_unique_races':len(ids),'races_by_venue':dict(races_by_venue),
        'official_normal_eligible':official_normal,'eligible_with_full_actual_details':eligible,'normal_missing_actual_details':missing_actual_details,'excluded_or_unverified':invalid,'racer_ids':len(registered),'racer_group_rows':len(rows),'motor_history_rows':len(motors),
        'result_course_association_groups':len(flowrows),'new_independent_races':0,'training_connected':False,'forward_receipts_for_historical_archive':0}
    write(out.root/'reports/archive_reuse.json',result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--archive',required=True);p.add_argument('--state',required=True);a=p.parse_args();print(json.dumps(derive(a.archive,a.state),ensure_ascii=False))
