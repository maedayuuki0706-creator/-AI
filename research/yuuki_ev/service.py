"""Trusted GitHub runtime -> allowlisted research Sheets. No secret transfer.

No notification imports, no production module imports, no main writes.
"""
import json
import os
from pathlib import Path
from datetime import datetime
from . import core
from .runner import TARGET, REPOSITORY, BRANCH, read_records
from .online import run, acknowledge
from .sheets import tables, IDS, write, payloads, targeted_sync

def run_job(root='data/research_yuuki_ev'):
    # Writes remain disabled after the approval review rejected batch updates.
    # Do not enable until that specific action is authorized and reviewed.
    if os.environ.get('YUUKI_RESEARCH_WRITES_APPROVED')!='true':
        raise RuntimeError('research_writes_blocked_pending_review')
    from google.oauth2.service_account import Credentials
    from google.auth.transport.requests import AuthorizedSession
    account=json.loads(os.environ['GOOGLE_SERVICE_ACCOUNT_JSON'])
    client=AuthorizedSession(Credentials.from_service_account_info(account,scopes=['https://www.googleapis.com/auth/spreadsheets']))
    endpoint='https://sheets.googleapis.com/v4/spreadsheets/'+TARGET
    def read(range_):
        r=client.get(endpoint+'/values/'+range_,params={'valueRenderOption':'UNFORMATTED_VALUE'},timeout=20);r.raise_for_status();return r.json().get('values',[])
    def send(requests):
        if not requests:return
        r=client.post(endpoint+':batchUpdate',json={'requests':requests},timeout=25)
        if not r.ok:raise RuntimeError('research_sheet_write_http_'+str(r.status_code))
    def append_new(name,rows):
        current=read("'"+name+"'!A1:B"+str(min(grids[name]['gridProperties']['rowCount'],5000)))
        ids={str(row[0]):str(row[1]) if len(row)>1 else '' for row in current[1:] if row}
        fresh=[r for r in rows[1:] if r[0] not in ids]
        # Match forecast hashes; a mismatch is evidence of corruption, not an
        # invitation to overwrite the original.
        for row in rows[1:]:
            if row[0] in ids and name!='保存確認' and ids[row[0]]!=row[1]:
                raise RuntimeError('research_original_hash_conflict')
        start=max(len(current),1)
        for i in range(0,len(fresh),10):send([write(IDS[name],start+i,fresh[i:i+10])])
        return [row[0] for row in fresh]
    metadata=client.get(endpoint,params={'fields':'sheets.properties'},timeout=20)
    if metadata.status_code==403:
        # Public identity only: lets owner grant the authorized research access.
        print('research_editor_required='+account['client_email'],flush=True)
        raise RuntimeError('research_sheet_editor_missing')
    metadata.raise_for_status()
    grids={s['properties']['title']:s['properties'] for s in metadata.json()['sheets']}
    if not set(IDS).issubset(grids):raise RuntimeError('research_tabs_not_initialized')
    # Recover only IDs missing locally after a successful Sheets write followed
    # by failed Git persistence. Never regenerate an already published forecast.
    local={f['id'] for f in read_records(root,'predictions')}
    originals=read("'研究予想原本'!A1:B5000")
    for row_index,row in enumerate(originals[1:],2):
        if not row or str(row[0]) in local:continue
        value=read("'研究予想原本'!C"+str(row_index)+":C"+str(row_index))
        recovered=json.loads(value[0][0]);claimed=recovered['hash']
        if claimed!=row[1] or core.digest({k:v for k,v in recovered.items() if k!='hash'})!=claimed:
            raise RuntimeError('research_recovery_hash_conflict')
        if recovered['id']!=row[0]:raise RuntimeError('research_recovery_id_conflict')
        core.write_once(Path(root)/'predictions'/recovered['day']/(recovered['id'].replace(':','_')+'.json'),recovered)
    for name,kind in [('保存確認','receipts'),('事後検証','results')]:
        known={x['id'] for x in read_records(root,kind)}
        records=read("'"+name+"'!A1:D5000")
        for row in records[1:]:
            if not row or row[0] in known:continue
            if kind=='results':recovered=json.loads(row[2])
            else:recovered={'id':row[0],'forecast_hash':row[1],'persisted_at':row[2],'eligible_live':row[3]}
            f=next((x for x in read_records(root,'predictions') if x['id']==row[0]),None)
            if not f or f['hash']!=recovered['forecast_hash']:raise RuntimeError('research_recovery_reference_conflict')
            core.write_once(Path(root)/kind/f['day']/(row[0].replace(':','_')+'.json'),recovered)
    started=datetime.now(core.JST).isoformat()
    collection=run(root,'/tmp/yuuki-ev-research-batches',limit=6)
    forecasts=read_records(root,'predictions');results=read_records(root,'results');receipts=read_records(root,'receipts')
    if len(forecasts)>4900:raise RuntimeError('research_archive_required_before_5000_records')
    data=tables(forecasts,results,receipts)
    # Grow only the needed research tabs before append or derived writes.
    expansions=[]
    for name,rows in data.items():
        if name not in grids:continue
        props=grids[name];g=props['gridProperties'];width=max(len(r) for r in rows)
        required=max(5000 if name in ('研究予想原本','事後検証','保存確認','EV閾値比較') else len(rows)+100,g['rowCount'])
        if required*g['columnCount']>1000000:raise RuntimeError('research_sheet_capacity_guard')
        if required>g['rowCount'] or width>g['columnCount']:
            expansions.append({'updateSheetProperties':{'properties':{'sheetId':props['sheetId'],'gridProperties':{'rowCount':required,'columnCount':max(width,g['columnCount'])}},'fields':'gridProperties.rowCount,gridProperties.columnCount'}})
            g['rowCount']=required;g['columnCount']=max(width,g['columnCount'])
    send(expansions)
    new_ids=append_new('研究予想原本',data['研究予想原本'])
    # Success responses from the actual forecast writes are the receipt basis.
    acknowledged=datetime.now(core.JST).isoformat()
    acknowledge(root,new_ids,acknowledged)
    receipts=read_records(root,'receipts');data=tables(forecasts,results,receipts)
    append_new('保存確認',data['保存確認']);append_new('事後検証',data['事後検証'])
    immutable={'研究予想原本','事後検証','保存確認'}
    for name,rows in data.items():
        if name in immutable:continue
        sid=100000001 if name=='EV買い目ログ' else IDS[name]
        width=len(rows[0]);last='';n=width
        while n:n,r=divmod(n-1,26);last=chr(65+r)+last
        old=read("'"+name+"'!A1:"+last+str(min(grids[name]['gridProperties']['rowCount'],max(len(rows)+100,1000),5000)))
        policies={
            '新ゆうき予想LOG':([0],set(range(26,29))|set(range(30,35)),False),
            '艇別勝ち負けLOG':([0,6],set(),True),
            '欠測・遅延LOG':([0,6],set(),True),
            'EV閾値比較':([0,1,2,3],set(range(4,24)),False),
            '日別場別AI成績':([0,1,2,3],set(range(4,24)),False),
            'EV買い目ログ':([20,5],set(range(12,19)),False),
            '研究ジョブ稼働':([0],{1},False),
            'EV120通り閲覧':([0],set(range(1,7)),False),
        }
        keys,mutable,append_only=policies[name]
        patches=targeted_sync(sid,old,rows,keys,mutable,append_only=append_only)
        for i in range(0,len(patches),100):send(patches[i:i+100])
    event={'started_at':started,'completed_at':datetime.now(core.JST).isoformat(),'status':'success',
           'new_forecasts':len(new_ids),'record_count':len(forecasts),'result_count':len(results),
           'source_sha':collection['source_sha'],'coverage':collection['coverage_note'],'errors':collection['errors']}
    core.write_once(Path(root)/'jobs'/(datetime.now(core.JST).strftime('%Y%m%dT%H%M%S')+'.json'),event)
    # Mutable small status block, not prediction evidence.
    status=[['項目','値'],['直近実行開始',started],['直近実行終了',event['completed_at']],['直近結果','success'],['新規研究原本',len(new_ids)],['現在の研究原本',len(forecasts)],['取得エラー',core.dumps(collection['errors'])],['定期方式','独立GitHub研究ジョブ／既存Google認証を同一環境内で使用（移送なし）']]
    old=read("'研究ジョブ稼働'!A1:B100")
    send(targeted_sync(IDS['研究ジョブ稼働'],old,status,[0],{1}))
    print(core.dumps(event),flush=True)

if __name__=='__main__':
    try:run_job()
    except Exception as exc:
        # Never print secret-bearing requests/headers or credential values.
        print('research_job_failed='+type(exc).__name__+':'+str(exc)[:120] if isinstance(exc,RuntimeError) else 'research_job_failed='+type(exc).__name__,flush=True)
        raise SystemExit(1)
