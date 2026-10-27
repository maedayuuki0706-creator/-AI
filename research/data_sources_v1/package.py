"""Export a verified data-only research archive without copying repository code."""
import argparse
import gzip
import json
from pathlib import Path
import zipfile

from .collect import digest, encode, stamp


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data',required=True)
    p.add_argument('--zip',required=True);a=p.parse_args()
    root=Path(a.data).resolve();target=Path(a.zip).resolve()
    summary=json.loads((root/'summary.json').read_bytes())
    if summary['pending_days']:
        raise ValueError('Do not package an unfinished calendar range as complete')
    for p in (root/'downloads').glob('*/*.json'):
        meta=json.loads(p.read_bytes())
        if meta['status']=='ok':
            if digest(gzip.decompress((root/meta['raw_path']).read_bytes()))!=meta['sha256']:
                raise ValueError('Evidence digest mismatch')
    for p in (root/'gaps/sources').glob('*.json'):
        meta=json.loads(p.read_bytes())
        if meta['status']=='ok' and digest(gzip.decompress((root/'gaps'/meta['raw_path']).read_bytes()))!=meta['sha256']:
            raise ValueError('Official gap evidence digest mismatch')
    files=sorted(p for p in root.rglob('*') if p.is_file() and not p.name.endswith('.tmp'))
    manifest={'created_at':stamp(),'kind':'data_only_research_archive','code_included':False,
              'quarantined_items':len(summary['errors']),'all_data_complete':False,
              'file_count':len(files),'summary':summary['counts'],
              'files':[{'path':str(p.relative_to(root)),'sha256':digest(p.read_bytes()),'bytes':p.stat().st_size}
                       for p in files]}
    if (root/'gaps/summary.json').is_file():
        manifest['additional_official_gap_counts']=json.loads((root/'gaps/summary.json').read_bytes())['counts']
    prefix='data/data_sources_v1/'+root.name+'/'
    target.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in files:z.write(p,prefix+str(p.relative_to(root)))
        z.writestr(prefix+'MANIFEST.json',encode(manifest))
    with zipfile.ZipFile(target) as z:
        if z.testzip() is not None:raise ValueError('Archive CRC verification failed')
    print(json.dumps({'path':str(target),'bytes':target.stat().st_size,'sha256':digest(target.read_bytes()),
                      'files':len(files)+1,'counts':summary['counts']},ensure_ascii=False))


if __name__=='__main__':main()
