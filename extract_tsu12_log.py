import json
from pathlib import Path
import daily_report as dr
import direct_discord_notify as base
DAY='20260914'; KEY='09:12'
rows=dr.read_jsonl(base.LOG_PATH)
chosen,_=dr.latest_predictions(rows,DAY)
out={'prediction':chosen.get(KEY)}
results=json.loads(Path('data/official_results/20260914.json').read_text(encoding='utf-8'))
out['official']=results.get(KEY)
Path('data/case_studies').mkdir(parents=True,exist_ok=True)
Path('data/case_studies/20260914_tsu12_log.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
print(json.dumps(out,ensure_ascii=False,sort_keys=True))
