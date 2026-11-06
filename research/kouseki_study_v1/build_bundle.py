"""Export a standalone read-only HTML + provenanced JSON research snapshot."""
from __future__ import annotations
import argparse
import json
import shutil
from pathlib import Path
from analytics import build_report

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--archive',type=Path,default=Path('data/exhibition_log'))
    parser.add_argument('--target',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    r=build_report(args.archive,args.target)
    shutil.copyfile(Path(__file__).with_name('index.html'),args.out/'index.html')
    (args.out/'report.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    (args.out/'report.js').write_text('window.KOUSEKI_REPORT = '+json.dumps(r,ensure_ascii=False,allow_nan=False)+';\n',encoding='utf8')
    print('Built',args.out,'race',r['venue'],r['race_no'],'entries',r['collection_coverage']['completed_finishes_with_course'])

if __name__=='__main__':main()
