"""Refresh viewer artifacts from Git objects only; no production execution or writes.
--fetch contacts only the repository origin. Output is required, never a deploy.
"""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
from build_research_history import build, emit

REPO=Path(__file__).resolve().parent.parent
AUDIT_REF='3e8958ab22134dc0caeb2979561137e702fc0c5b'
AUDIT_PATH='data/research_four_venue_phase2/20251018_20261017/studies/eed2cf3775203abb/audited_races.json.gz'


def git(*args):
    return subprocess.check_output(['git',*args],cwd=REPO,timeout=300)


def refresh(output,source_ref,audit_ref=AUDIT_REF,fetch=False):
    if fetch:
        git('fetch','--depth','1','origin','main')
        source_ref=git('rev-parse','FETCH_HEAD').decode().strip()
        # Pin historical evidence. Do not advance research sources implicitly.
        try:git('cat-file','-e',audit_ref+'^{commit}')
        except subprocess.CalledProcessError:git('fetch','--depth','1','origin',audit_ref)
    source_sha=git('rev-parse',source_ref+'^{commit}').decode().strip()
    audit_sha=git('rev-parse',audit_ref+'^{commit}').decode().strip()
    with tempfile.TemporaryDirectory(prefix='boat-viewer-readonly-') as temp:
        root=Path(temp)
        for prefix in ('data/official_results','data/exhibition_log'):
            paths=git('ls-tree','-r','--name-only',source_sha,prefix).decode().splitlines()
            for path in paths:
                if not path.endswith('.json'):continue
                dest=root/path;dest.parent.mkdir(parents=True,exist_ok=True)
                dest.write_bytes(git('show',source_sha+':'+path))
        audited=root/'audited_races.json.gz';audited.write_bytes(git('show',audit_sha+':'+AUDIT_PATH))
        report=build(root,audited,output,source_sha,audit_sha)
    # Frozen research indices are separate from both outcomes and entry simulation.
    entries=[]
    paths=git('ls-tree','-r','--name-only',audit_sha,'data/trifecta_120_index').decode().splitlines()
    for path in paths:
        if not path.endswith('.json') or Path(path).name.startswith('outcomes_'):continue
        item=json.loads(git('show',audit_sha+':'+path))
        if not isinstance(item.get('races'),list):continue
        for race in item['races']:
            ranks=race.get('ranks',[])
            combinations={row[1] for row in ranks}
            expected={f'{a}-{b}-{c}' for a in range(1,7) for b in range(1,7) for c in range(1,7) if len({a,b,c})==3}
            if len(ranks)!=120 or combinations!=expected or sorted(row[0] for row in ranks)!=list(range(1,121)):
                raise ValueError('Incomplete research index: '+path)
            if item.get('calibrated') is not False or item.get('prospective_index_verified') is not False:
                raise ValueError('Unexpected index evidence flags: '+path)
        name=Path(path).parent.name+'-'+Path(path).name
        emit(output/'research/indices'/name,item)
        entries.append({'file':name,'date':item.get('date'), 'model':item['races'][0].get('model') if item['races'] else '',
                        'races':len(item['races']),'source_path':path})
    emit(output/'research/indices/manifest.json',{'source_ref':audit_sha,'files':entries,'races':sum(e['races'] for e in entries)})
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--source-ref',default='HEAD');p.add_argument('--audit-ref',default=AUDIT_REF);p.add_argument('--fetch',action='store_true')
    a=p.parse_args();refresh(a.output,a.source_ref,a.audit_ref,a.fetch)
