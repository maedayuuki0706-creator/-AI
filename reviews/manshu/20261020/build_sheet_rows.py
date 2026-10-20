from pathlib import Path
import json
P=Path(__file__).resolve().parent/'review'
s=json.loads((P/'summary.json').read_text());rs=json.loads((P/'review_cases.json').read_text())
root='https://github.com/maedayuuki0706-creator/-AI/blob/research/manshu-review-20261020/reviews/manshu/20261020/'
headers=['日付','場','R','レースキー','確定3連単','払戻(円/100円)','人気','決まり手','事後の事故等','事前保存の確認','締切前版の保存時刻','展示掲載風(m)','展示掲載波(cm)','1号艇展示順位','1号艇全国勝率','勝者展示順位','分析区分','事前の材料','事後専用の確認','今回の確認時刻','公式結果URL','原本・記録参照']
rows=[headers]
for r in sorted([x for x in rs if x['payout']>=10000],key=lambda x:x['payout'],reverse=True):
 b={z['lane']:z for z in r['prerace_display']['boats']};winner=int(r['trifecta'][0]);p=r.get('verified_prerace_version',{});e=r['prerace_display']['environment'];v=r['review']
 rows.append([r['day'],r['venue'],r['rno'],r['race_id'],r['trifecta'],r['payout'],r['popularity'],r['outcome']['details']['method'],','.join(str(z['lane'])+z['status'] for z in r['accident_or_withdrawal']) or 'なし',r['timing_class'],p.get('commit_date'),e['wind_speed'],e['wave_cm'],b[1].get('exhibition_rank'),b[1]['win_rate'],b[winner].get('exhibition_rank'),v['classification'],v['prerace_materials'],v['postrace_only'],s['reviewed_at'],r['outcome']['details']['source_url'],root+'review_cases.json'])
analysis=[['2026年10月20日 万舟結果と荒れた要素','',''],['公式最終確認 '+s['official_pay_retrieved_at']+'。払戻は3連単100円当たり。','',''],['論点','確認内容','出典・保存先'],['確定結果',f"全144R確定。万舟26本（{s['manshu_rate']:.1%}）。20万円以上3本。",'https://www.boatrace.jp/owpc/pc/race/pay?hd=20261020'],['場別','住之江6/12R、尼崎4/12R、江戸川3/12R、三国3/12R、下関3/12R。児島・唐津各1/12R。浜名湖は開催なし。',root+'summary.json'],['共通原因','20万円以上3件の展示掲載風は0〜2m、結果時風速はすべて0m。強風だけでは説明できない。住之江の万舟6件はすべて1号艇展示最速。',root+'review_cases.json']]
for key in ['20261020_13_04','20261020_12_05','20261020_12_07','20261020_12_10','20261020_03_08','20261020_03_10','20261020_03_12','20261020_16_02','20261020_23_02']:
 r=next(x for x in rs if x['race_id']==key);v=r['review'];analysis.append([f"{r['venue']}{r['rno']}R {r['payout']:,}円",v['prerace_materials']+' 事後：'+v['postrace_only'],r['outcome']['details']['source_url']])
analysis += [['事前保存の確認','26件のうち16件に締切前GitHub保存版があり、登録番号・展示タイム・展示ST・進入の差異0件。残り10件は今回の事後取得。',root+'predeadline_verification.json'],['同日比較の分母','優先3場と住之江・尼崎の60Rを収集。尼崎10Rは3号艇欠場で展示5艇のため除外。比較59R＝万舟15、非万舟44。その他11万舟をこの分母に混ぜない。',root+'summary.json']]
for f in s['feature_comparisons']:
 if f['feature']=='1号艇全国勝率4.5以下':analysis.append(['探索：'+('勝率4.5以下' if f['present'] else '勝率4.5超'),f"{f['race_count']}R中{f['manshu_count']}本（{f['manshu_rate']:.1%}）。探索上の区切りで、場・級別の交絡未調整。採用前に翌日以降で検証。",root+'summary.json'])
analysis += [['実警戒の不発','住之江10Rの万舟シャドー保存判定は19:15:54時点alert=false。結果92,690円。未観測25件を不発と数えない。',root+'reused_manshu_watch/20261020.json'],['残る不足','当時の締切前オッズ・取得時刻は未照合。映像からの攻め起点・内艇抵抗・2/3着への連動は未確認。事後の本番ST・着順・払戻は入力へ混ぜない。',root+'REPORT.md'],['予想への接続','研究仮説として保存。本番未反映。機番周期の未確認は明記し、近隣潮位を場内流速に代用せず、唐津への潮汐補正なし。',root+'REPORT.md'],['取得・保存実績','既存36Rの公式結果・入力原本を再利用し、結果35Rを追加。詳細71R・426艇、万舟26R・156艇の展示を照合。既存配信・取得・研究ワーカー・Secrets・設定の変更0。',root+'run.json']]
(P/'sheet_rows.json').write_text(json.dumps({'log':rows,'analysis':analysis},ensure_ascii=False))
print('log rows',len(rows),'analysis rows',len(analysis))
