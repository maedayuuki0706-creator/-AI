from pathlib import Path
import json,datetime as dt,hashlib,gzip,base64
from explanations_26 import EXPLANATIONS
from parsers import textify
ROOT=Path(__file__).resolve().parent;P=ROOT/'review'
def now():return dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat()
def main():
 rs=json.loads((P/'review_cases.json').read_text());man=[r for r in rs if r['payout']>=10000]
 assert set(EXPLANATIONS)=={r['race_id'] for r in man} and len(man)==26
 records=[]
 for r in sorted(man,key=lambda x:(x['jcd'],x['rno'])):
  rid=r['race_id'];title,pre,post,unknown=EXPLANATIONS[rid]
  if r['input_timing']['status']=='existing_frozen_original':
   raw=json.loads((ROOT/'reused-state/reused_inputs'/(rid+'.json')).read_text())['official_originals']['racelist']['html']
  else:
   m=r['prerace_display']['sources']['program'];raw=gzip.decompress(base64.b64decode((P/m['raw_path']).read_bytes())).decode()
  t=textify(raw);conditions=[s for s in ('安定板使用','周回短縮','進入固定') if s in t]
  record={'race_id':rid,'venue':r['venue'],'race_no':r['rno'],'trifecta':r['trifecta'],'payout':r['payout'],'title':title,'prerace_facts':pre,'postrace_facts_and_partial_interpretation':post,'unresolved':unknown,'race_conditions':conditions,'source_url':r['outcome']['details']['source_url'],'predeadline_evidence':r['timing_class'],'causal_completion':'partial_data_based_explanation','attack_origin':None,'inner_resistance':None,'linked_boats':None,'second_third_route':None,'video_viewed':False,'six_boat_rows':r['prerace_display']['boats'],'six_boat_outcome':r['outcome']['details']['finish']}
  records.append(record)
 meta={'day':'20261020','reviewed_at':now(),'cases':26,'video_verified_cases':0,'complete_causal_explanations':0,'prerace_git_versions':16,'data_only_retrospective_cases':10,'video_attempt':{'race_id':'20261020_12_05','public_player_url':'https://front.player.boatrace-cdn.jp/player/vod?service=boatcast&stadium=12suminoe&raceType=race&raceDate=20261020&raceNumber=5&autoplay=0&bitrate=low','setting_catalog_available':True,'browser_visible_message':'エラーコード：0 この動画の視聴は許可されていません。','normal_reload_count':1,'recheck_result':'same_error','http_playback_request_status':403,'scope':'1 race player tested. Other 25 not attempted. No video labels for any race.','restriction_not_bypassed':True},'corrections':[{'race_id':'20261020_03_12','racer_id':'4269','field':'current_class_in_commentary','previous':'A1','correct':'A2','source':'official racelist and already-saved boat row','counts_changed':False}],'production_changes':0,'records':records}
 (P/'causal_review.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
 lines=['# 全26万舟の説明状況','',f"確認：{meta['reviewed_at']}",'','全26件について事前材料と本番ST・進入・決まり手・事故を照合した。全艇の攻め起点、内艇の抵抗、2着・3着への連動まで映像で確認した完全な因果説明は0件。以下はデータからの部分説明で、未確認の動きを事実に置き換えない。','', '住之江5Rの公式公開プレイヤーは、この閲覧環境では「この動画の視聴は許可されていません」と表示。一度の通常再読込後も同じ表示だった。その他25件の動画は未試行。全26件で映像確認済みラベルを付けない。','', '締切前GitHub版を照合した16件と、事後に公式表示を取得した10件を区別する。本番STは説明用の結果であり、事前予測の入力には使わない。全国勝率やモーター2連率は力量・機力を直接確定する値ではなく、個別の標本数や条件にも注意する。']
 for n,r in enumerate(records,1):
  lines+=['',f"## {n}. {r['venue']}{r['race_no']}R　{r['trifecta']}　{r['payout']:,}円",'',r['title'],'','事前材料：'+r['prerace_facts'],'','事後確認・部分説明：'+r['postrace_facts_and_partial_interpretation'],'','未確認：'+r['unresolved'],'',f"事前保存：{r['predeadline_evidence']}。開催条件：{'・'.join(r['race_conditions']) or '本記録で追加の特殊条件を検出せず'}。",'',f"[公式結果]({r['source_url']})",'','|枠|選手|級|全国勝率|平均ST|展示秒|展示ST|展示コース|本番コース|本番ST|着|','|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---|']
  out={b['lane']:b for b in r['six_boat_outcome']}
  def st(v):return '未取得' if v is None else ('F'+f'{abs(v):.2f}' if v<0 else f'{v:.2f}')
  for b in r['six_boat_rows']:
   d=out[b['lane']];lines.append(f"|{b['lane']}|{b['name']}|{b['current_class']}|{b['win_rate']:.2f}|{st(b['avg_st'])}|{b.get('exhibition_time','欠測')}|{st(b.get('exhibition_st_timing'))}|{b.get('predicted_course','未取得')}|{d.get('course','未取得')}|{st(d.get('st'))}|{d['finish'] or d['status']}|")
 lines+=['','## 今回の訂正と次の確認','','江戸川12R・杉山裕也の級別は公式出走表のA2に訂正。保存済み艇データはA2であり、誤りは説明文のA1表記。結果・件数は変わらない。','','次の確認は映像上の攻め起点、内の抵抗、2/3着の追走順、抜きの逆転地点。別日の事前固定データで誤警報も検証する。映像確認ができるまで推測ラベルを学習の正解にしない。本番配信・予想・ワーカー・設定の変更は0件。']
 (P/'CAUSAL_REVIEW.md').write_text('\n'.join(lines)+'\n')
 print(json.dumps({'cases':len(records),'boat_rows':sum(len(r['six_boat_rows']) for r in records),'full_explanations':0,'video_verified':0,'corrections':1},ensure_ascii=False))
if __name__=='__main__':main()
