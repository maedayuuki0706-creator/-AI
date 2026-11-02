"""Read PR55 tar members without extracting paths or treating retrospective data as live."""
import argparse,json,tarfile
from collections import Counter
from hashlib import sha256
from pathlib import Path
from research.ultimate_fusion_v1.engine import boats_six,digest

def audit(archive,root,output):
    counts=Counter();models=[];joins=[];venues=Counter()
    with tarfile.open(archive,'r:gz') as t:
        for member in t:
            if not member.isfile() or not member.name.endswith('.json'):continue
            if '/models/' in member.name:
                d=json.load(t.extractfile(member));models.append({'venue_code':member.name.rsplit('/',1)[-1][:2],'sha256':digest(d),'player_histories':len(d.get('racer_observations',{}))});continue
            if '/races/' not in member.name:continue
            d=json.load(t.extractfile(member));boats_six(d['rows']);counts[d['original_status']]+=1;venues[d['venue_code']]+=1
            _,code,rno=d['race_id'].split('_');path=Path(root)/'data/exhibition_log'/d['day']/f'{code}_{rno}.json'
            status='missing_current_log'
            if path.exists():
                current=json.loads(path.read_text());boats_six(current['rows'])
                expected={(int(x['lane']),str(x['racer_id'])) for x in current['rows']}
                status='six_racers_matched' if expected=={(int(x['lane']),str(x['racer_id'])) for x in d['rows']} else 'identity_conflict'
            joins.append({'race_id':d['race_id'],'venue24_sha256':digest(d),'join_status':status,
                          'original_status':d['original_status'],'used_in_prediction':False})
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    result={'archive_sha256':sha256(Path(archive).read_bytes()).hexdigest(),'models':models,
            'races':sum(counts.values()),'by_status':dict(counts),'by_venue':dict(sorted(venues.items())),
            'join_counts':dict(Counter(x['join_status'] for x in joins)),
            'live_original_rows_admitted':0,'reason':'Existing PR55 retrospective archive audited, not silently promoted to live provenance.'}
    (out/'venue24_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    (out/'venue24_join_manifest.json').write_text(json.dumps(joins,ensure_ascii=False,separators=(',',':'))+'\n')
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--archive',required=True);p.add_argument('--root',default='.');p.add_argument('--output',required=True);a=p.parse_args();print(json.dumps(audit(a.archive,a.root,a.output),ensure_ascii=False))
