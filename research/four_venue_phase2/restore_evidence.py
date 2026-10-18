"""Restore published compressed research evidence without overwriting anything."""
import argparse,gzip,json,zipfile
from pathlib import Path
from research.edogawa_phase2.acquire import put,digest

def restore(root,original):
    root=Path(root);original=Path(original)
    for archive in [original/'official_raw_archives.zip',root/'official_K_new_raw.zip']+sorted((root/'programs').glob('official_B_raw*.zip')):
        if not archive.exists():continue
        target=root/'programs' if archive.parent.name=='programs' else root
        with zipfile.ZipFile(archive) as z:
            for name in z.namelist():
                if not name.endswith('.lzh'):continue
                basename=name.split('/')[-1];body=z.read(name)
                if basename!=digest(body)+'.lzh':raise ValueError('Raw archive member digest mismatch')
                put(target/'raw'/basename,body)
    for p in root.rglob('*.gz'):
        if p.name.endswith('.sqlite.gz'):continue
        put(p.with_suffix(''),gzip.decompress(p.read_bytes()))
    # Daily states are reconstructed only when absent, from the chosen audited
    # manifest. Old acquisition checkpoints remain unchanged in an active tree.
    candidates=[p for p in (root/'acquisition').glob('*.json') if not p.name.endswith('_summary.json')]
    for p in candidates:
        data=json.loads(p.read_text())
        if not isinstance(data,list):continue
        for d in data:
            path=root/'days'/(d['day']+'.json')
            if not path.exists():put(path,json.dumps(d,ensure_ascii=False,sort_keys=True).encode())

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--original',required=True);a=p.parse_args();restore(a.root,a.original)
