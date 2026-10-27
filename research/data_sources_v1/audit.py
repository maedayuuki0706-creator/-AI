"""Measure overlapping mirrors without treating them as independent evidence."""
import argparse
from pathlib import Path

from .collect import Client, modern, save_json, stamp


def flatten(obj, prefix=''):
    result={}
    if isinstance(obj,dict):
        for key,value in obj.items():result.update(flatten(value,prefix+'/'+str(key)))
    elif isinstance(obj,list):
        for key,value in enumerate(obj):result.update(flatten(value,prefix+'/'+str(key)))
    elif obj is not None:
        result[prefix]=obj
    return result


def compare(left,right):
    same,different,only_left,only_right=0,[],0,0
    for key in sorted(set(left)|set(right)):
        if key not in left:only_right+=1
        elif key not in right:only_left+=1
        elif left[key]==right[key]:same+=1
        else:different.append({'field':key,'left':left[key],'right':right[key]})
    return {'identical_nonnull_fields':same,'conflicts':different,
            'only_left_nonnull_fields':only_left,'only_right_nonnull_fields':only_right}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',required=True)
    p.add_argument('--day',default='2026-10-18');a=p.parse_args()
    root=Path(a.out);client=Client(root);sources={};receipts={}
    for source in ('turnmark','openapi'):
        meta,payload=client.read(source,a.day);receipts[source]=meta
        if payload is None:raise ValueError('Cannot compare unavailable sources')
        sources[source]=modern(payload,a.day)
    left,right=sources['turnmark'],sources['openapi'];common=sorted(set(left)&set(right))
    comparisons={rid:compare(flatten(left[rid]),flatten(right[rid])) for rid in common}
    result={'generated_at':stamp(),'day':a.day,'sources':receipts,
            'common_races':len(common),'left_only_races':sorted(set(left)-set(right)),
            'right_only_races':sorted(set(right)-set(left)),
            'identical_nonnull_fields':sum(r['identical_nonnull_fields'] for r in comparisons.values()),
            'conflicting_fields':sum(len(r['conflicts']) for r in comparisons.values()),
            'comparisons':comparisons,'independent_evidence_count':1,
            'interpretation':'Both mirror official upstream. Matching fields are not independent votes.'}
    save_json(root/('source_overlap_'+a.day.replace('-','')+'.json'),result)
    print({k:v for k,v in result.items() if k not in ('sources','comparisons')})


if __name__=='__main__':main()
