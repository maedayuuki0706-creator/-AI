from prediction_recap import post_confirmed, report_destination_key
from pathlib import Path
import json
from datetime import datetime
DAY='20260914'; AS_OF='12:30 JST'
VENUES=[('戸田',12,3,1,0,0,0),('平和島',12,3,1,0,0,0),('浜名湖',12,2,1,0,0,0),('蒲郡',12,0,0,0,0,0),('常滑',12,3,1,1,0,0),('津',12,4,2,1,1,0),('三国',12,3,3,0,3,0),('びわこ',12,3,0,0,0,0),('住之江',12,0,0,0,0,0),('徳山',12,3,2,1,1,0),('下関',12,0,0,0,0,0),('若松',12,0,0,0,0,0),('芦屋',12,8,5,4,1,0),('福岡',12,2,0,0,0,0)]
def payload():
 total=sum(v[2] for v in VENUES); hits=sum(v[3] for v in VENUES); main=sum(v[4] for v in VENUES); mid=sum(v[5] for v in VENUES); man=sum(v[6] for v in VENUES)
 lines=[f'📊 **9/14 {AS_OF} 中間報告**',f'結果確認 **{total}R**／配信記録 **{sum(v[1] for v in VENUES)}R**',f'全体的中 **{hits}/{total}R**（{hits/total*100:.1f}%）',f'本線的中 **{main}R**｜中穴的中 **{mid}R**｜万舟的中 **{man}R**','※12:30時点で払戻が確認できたレースのみ集計。未確定は分母外。','━━━━━━━━━━━━━━━━━━']
 for venue,sent,confirmed,hit,mh,midh,manh in VENUES:
  if confirmed: lines.append(f'**{venue}**　配信 {sent}R｜結果 {confirmed}R｜的中 {hit}/{confirmed}R｜本線 {mh}｜中穴 {midh}｜万舟 {manh}')
  else: lines.append(f'**{venue}**　配信 {sent}R｜結果待ち（0/0）')
  lines.append('━━━━━━━━━━━━')
 return {'embeds':[{'title':'9/14 12:30時点｜全場中間報告','description':'\n'.join(lines),'color':0x176B87,'footer':{'text':'結果確認分だけの中間集計。確定版は全レース終了後に更新。'}}],'allowed_mentions':{'parse':[]}}
if __name__=='__main__':
 msg=post_confirmed(payload())
 Path('data').mkdir(exist_ok=True); p=Path('data/interim_report_deliveries.jsonl')
 with p.open('a',encoding='utf-8') as f: f.write(json.dumps({'day':DAY,'as_of':AS_OF,'destination':report_destination_key(),'message_id':msg['id'],'sent_at':datetime.now().astimezone().isoformat(),'confirmed_races':sum(v[2] for v in VENUES)},ensure_ascii=False)+'\n')
 print('Interim report acknowledged')
