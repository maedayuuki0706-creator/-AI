"""Describe outcomes without promoting post-race values to predictive inputs."""
from pathlib import Path
import json,datetime as dt,hashlib,gzip,base64,collections
from parsers import parse_beforeinfo
ROOT=Path(__file__).resolve().parent;P=ROOT/'review'
def read(p):return json.loads(p.read_text())
def write(name,obj):(P/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
def stamp():return dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat()
cases={
'20261020_13_04':('外の攻め候補はある・事故混在','5号艇はA1、全国6.37、展示6.79で最速。1号艇B1の5.21を上回る。6号艇はB2・1.68、展示ST.38で6頭を強く裏付ける材料は薄い。','5号艇転覆。6-1-3と転覆の因果関係・攻め起点は映像未確認。事故混在例として通常展開と分ける。'),
'20261020_12_05':('進入不確実性はある・着順の特定は難しい','展示進入123564。4号艇はB2だが展示6.80で2位。1号艇は全国6.15・展示6.76最速、5号艇の展示ST.22は最後。','本番は枠なり。1〜3号艇STは.26/.33/.32、4〜6号艇は.22/.26/.22。展示時からこの遅れや5-4-3を分かっていたとは扱わない。'),
'20261020_12_07':('インを疑う材料あり・6-4特定は難しい','1号艇の全国4.06に対し2号艇6.28、6号艇4.98。5号艇展示ST.03。6号艇は展示6.84で2位だが展示ST.20、4号艇展示6.95は最後。','4号艇本番ST.03、5号艇.06、6号艇.09で外が先行。決まり手は抜き。誰が攻めを起こしたか、6の逆転過程は映像未確認。'),
'20261020_12_10':('壁と外のST差はある・既存警戒は不発','1号艇展示6.82最速でも、2/3号艇展示ST.33/.22に対し4号艇.06。内の壁と4の攻め候補を別に見る材料。5号艇は展示6.88で最後。','1号艇本番ST.28。勝者5号艇の決まり手は抜き。保存済み万舟シャドーは19:15:54時点alert=false。5-3-1の選択成功とは扱えない。'),
'20261020_03_08':('インの基礎成績と外の足に材料あり','1号艇全国3.60に対し3号艇5.83、5号艇4.96。展示は3号艇6.64最速、5号艇6.69で2位。4号艇展示ST.31。掲載風2m・波5cm。','5号艇まくり差し、3号艇2着、1号艇3着。攻め起点・内艇の抵抗・連動の経路は映像未確認。'),
'20261020_03_10':('今回の展示から2-4-6の特定は難しい','1号艇は展示6.69で同率最速、展示ST.03も最速。2号艇は全国3.96、展示6.72。4/6号艇の展示タイムとSTも強い上位材料ではない。','1号艇本番ST.33、2号艇.16。事後の1号艇の遅れを事前警戒の根拠に流用しない。'),
'20261020_03_12':('3号艇の力量・機力に材料あり','3号艇A1・全国7.11・平均ST.15・モーター2連率44.21%。1号艇は全国6.26・平均ST.17。3の展示STはF.02で本番再現を保証しない。','3号艇まくり、5号艇2着、2号艇3着。最速展示の4号艇は展示ST.32、本番.36で4着。展示タイムとSTを分けて評価する例。'),
'20261020_16_02':('2号艇の攻めと外のSTに材料あり','1号艇全国3.77に対し2号艇4.80。2号艇展示6.73最速。4/5/6号艇展示ST.03/.04/.05で内3艇より早い。5/6号艇の展示タイム自体は下位。','2号艇まくり、5号艇2着、6号艇3着。6号艇が本番4コース、5号艇6コース。2の攻めと5/6の着取りの連動は映像で別検証。'),
'20261020_23_02':('外の展示とSTに具体的材料あり','6号艇展示6.62最速、3号艇6.63で2位、5号艇展示ST.01最速。2号艇展示ST.21に対し3号艇.04、5号艇.01。掲載風4m・波4cm。1号艇全国7.91は弱いインとは扱わない。','5-3-6、決まり手は抜き。本番ST1号艇.15と勝者5号艇.14は僅差。最初の攻め起点を勝者と同一視しない。唐津に潮汐補正は加えない。')}

def features(r):
    bs={b['lane']:b for b in r['prerace_display']['boats']};b=bs[1];e=r['prerace_display']['environment']
    return {'1号艇全国勝率4.5以下':b['win_rate']<=4.5,'1号艇展示最速':b.get('exhibition_rank')==1,'外4〜6号艇が展示最速':any(bs[l].get('exhibition_rank')==1 for l in (4,5,6)),'展示進入が枠なり以外':any(l!=bs[l].get('predicted_course',l) for l in bs),'掲載風速4m以上':e['wind_speed'] is not None and e['wind_speed']>=4}

def main():
    pay=read(P/'daily_pay.json');allrows=pay['races'];rows=[read(q) for q in sorted((P/'races').glob('*.json'))]
    proofs=read(P/'exhibition_commit_proofs.json')['records'];priority=read(P/'priority_commit_proofs.json');proofmap={x['data']['day']+'_'+x['data']['jcd']+'_'+str(x['data']['rno']).zfill(2):x for x in proofs if x.get('data')}
    proofmap.update({x['race_id']:x for x in priority if x.get('data')})
    verification=[]
    for r in rows:
        rid=r['race_id'];d=r['outcome']['details'];bs=r['prerace_display']['boats'];assert len(bs)==6 and len(d['finish'])==6
        assert set(b['racer_id'] for b in bs)==set(b['racer_id'] for b in d['finish'])
        assert r['trifecta']==d['trifecta'] and r['payout']==d['payout_per_100']
        if rid in proofmap:
            pr=proofmap[rid];pd=pr['data'];prows=pd.get('rows',pd.get('boats',[]));frozen_by={int(b['lane']):b for b in prows};dif=[]
            if 'rows' in pd:
                assert pd.get('settled') is False and all(b.get('actual_st') is None and b.get('finish') is None for b in prows)
                for b in bs:
                    f=frozen_by[b['lane']]
                    for key,old in [('exhibition_time','exhibition_time'),('exhibition_st_timing','exhibition_st'),('predicted_course','exhibition_course'),('racer_id','racer_id')]:
                        if b.get(key)!=f.get(old):dif.append({'lane':b['lane'],'field':key,'current':b.get(key),'predeadline':f.get(old)})
            else:
                op=pd['official_originals']['beforeinfo'];assert hashlib.sha256(op['html'].encode()).hexdigest()==op['sha256']
                parsed=parse_beforeinfo(op['html'])
                for b in bs:
                    f=frozen_by[b['lane']]
                    f.update(parsed['boats'][b['lane']])
                    for key in ('exhibition_time','racer_id','exhibition_st_timing','predicted_course'):
                        if b.get(key)!=f.get(key):dif.append({'lane':b['lane'],'field':key})
            verification.append({'race_id':rid,'commit_sha':pr['commit_sha'],'commit_date':pr['commit_date'],'difference_count':len(dif),'differences':dif})
            r['verified_prerace_version']={k:v for k,v in pr.items() if k!='data'};r['timing_class']='締切前GitHub保存版を確認'
        else:r['timing_class']='事後に公式の出走表・展示表示を取得'
        accident=[{'lane':b['lane'],'status':b['status']} for b in d['finish'] if b['status']!='finished'];r['accident_or_withdrawal']=accident
        r['feature_comparison_eligible']=r['prerace_display']['environment']['exhibition_count']==6 and len(d['finish'])==6
        r['descriptive_features']=features(r) if r['feature_comparison_eligible'] else None
        if rid in cases:classification,pre,post=cases[rid]
        else:
            b1=bs[0];win=next(b for b in bs if b['lane']==int(r['trifecta'][0]));classification='展示と力量の照合例・個別戦術は未確認'
            pre=f"1号艇全国{b1['win_rate']:.2f}・展示順位{b1.get('exhibition_rank','欠測')}。勝者{win['lane']}号艇は全国{win['win_rate']:.2f}・展示順位{win.get('exhibition_rank','欠測')}・展示ST{win.get('exhibition_st_timing','欠測')}。"
            post=f"公式決まり手は{d['method']}。全6艇の攻め・抵抗・追走順は映像未確認。"
        r['review']={'classification':classification,'prerace_materials':pre,'postrace_only':post,'causal_attack_labels':None,'video_review_status':'not_viewed','adoption_status':'研究仮説・本番未反映'}
        r['replay']={'official_venue_link':f"https://race.boatcast.jp/?jo={r['jcd']}",'day':r['day'],'race_no':r['rno'],'playback_verified':False}
    manshu=[r for r in rows if r['payout']>=10000]
    comparison=[r for r in rows if r['jcd'] in ('03','16','23','12','13') and r['feature_comparison_eligible']]
    comps=[]
    for f in features(comparison[0]):
        for flag in (True,False):
            sample=[r for r in comparison if r['descriptive_features'][f] is flag];n=sum(r['payout']>=10000 for r in sample)
            comps.append({'feature':f,'present':flag,'race_count':len(sample),'manshu_count':n,'manshu_rate':n/len(sample) if sample else None,'status':'同日探索・場と級別の交絡未調整・事後取得分含む'})
    byvenue=[]
    for jcd in sorted(set(r['jcd'] for r in allrows)):
        vr=[r for r in allrows if r['jcd']==jcd];settled=[r for r in vr if r['payout'] is not None];man=[r for r in settled if r['payout']>=10000]
        byvenue.append({'jcd':jcd,'venue':vr[0]['venue'],'scheduled':len(vr),'settled':len(settled),'manshu':len(man),'rate':len(man)/len(settled) if settled else None,'max_payout':max((r['payout'] for r in settled),default=None)})
    settled=sum(r['payout'] is not None for r in allrows)
    summary={'day':'20261020','reviewed_at':stamp(),'official_pay_retrieved_at':pay['acquisition']['retrieved_at'],'scheduled_races':len(allrows),'settled_races':settled,'pending_races':[r['race_id'] for r in allrows if r['payout'] is None],'manshu_count':len(manshu),'manshu_rate':len(manshu)/settled,'payout_unit':'yen per 100 yen','threshold_yen':10000,'over_200000_count':sum(r['payout']>=200000 for r in manshu),'result_detail_races':len(rows),'result_boat_rows':len(rows)*6,'reused_official_results':sum(r['result_reused'] for r in rows),'new_official_result_details':sum(not r['result_reused'] for r in rows),'reused_original_inputs':sum(r['input_timing']['status']=='existing_frozen_original' for r in rows),'manshu_with_predeadline_git_version':sum(r['race_id'] in proofmap for r in manshu),'manshu_retrospective_only':sum(r['race_id'] not in proofmap for r in manshu),'manshu_accident_races':sum(bool(r['accident_or_withdrawal']) for r in manshu),'manshu_methods':dict(collections.Counter(r['outcome']['details']['method'] for r in manshu)),'comparison_races':len(comparison),'comparison_manshu':sum(r['payout']>=10000 for r in comparison),'feature_comparisons':comps,'by_venue':byvenue,'verification':verification,'actual_warning_decision':{'race_id':'20261020_12_10','observed_at':'2026-10-20T19:15:54.294722+09:00','alert':False,'outcome_manshu':True,'status':'保存済み1観測の不発。未観測25件を警戒失敗として数えない。','source':'research-manshu-watch-state/data/research_manshu_watch/20261020.json'},'missing':[{'race_id':r['race_id'],'reasons':r['missing_reasons']} for r in rows if r['missing_reasons']],'global_gaps':['当時の締切前オッズ・全120通りの取得時刻は未照合','全艇の攻め起点・抵抗・連動は映像未確認','機番の使用周期は今回独立再確認なし。機番をまたぐモーター成績統合は実施せず','場内実測流速・流向なし。近隣潮位で代用せず、唐津の潮汐補正なし'],'production_change_count':0,'prediction_adoption':'未採用。翌日以降の未見データで事前固定・場別検証が必要'}
    write('summary.json',summary);write('review_cases.json',rows);write('predeadline_verification.json',verification)
    (P/'manshu_cases.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in manshu))
    report=[f'# 2026年10月20日 万舟結果と荒れた要素',f"確認：{summary['reviewed_at']}。公式払戻取得：{summary['official_pay_retrieved_at']}。",f"3連単100円当たり1万円以上を万舟とする。{settled}/{len(allrows)}R確定、万舟{len(manshu)}本（{summary['manshu_rate']:.1%}）。20万円以上{summary['over_200000_count']}本。未確定{len(summary['pending_races'])}R。",'', '## 結論','強風が全体の共通原因とは言えない。20万円以上の3件は展示掲載風速0〜2m、結果時風速はすべて0m。住之江は万舟6本すべてで1号艇の展示タイムが最速だった。展示タイムだけでインを信頼する見方は今日のケースを説明しきれない。','インの基礎成績、内側のSTの壁、外の攻め候補、進入不確実性を別々に記録する。尼崎4Rなどの事故混在例も分離した。ただし荒れ警戒と的中は別であり、着順の特定・攻め起点の説明には映像と事前オッズが不足する。','', '## 場別件数','|場|確定R|万舟|率|最大払戻円|','|---|---:|---:|---:|---:|']
    report += [f"|{v['venue']}|{v['settled']}|{v['manshu']}|{v['rate']:.1%}|{v['max_payout']:,}|" for v in byvenue]
    report+=['浜名湖は当日開催なし。','', '## 全万舟記録','|場R|3連単|払戻円|人気|決まり手|事前保存|事後の事故等|','|---|---|---:|---:|---|---|---|']
    for r in sorted(manshu,key=lambda r:r['payout'],reverse=True):report.append(f"|{r['venue']}{r['rno']}R|{r['trifecta']}|{r['payout']:,}|{r['popularity']}|{r['outcome']['details']['method']}|{'締切前Git版あり' if r['race_id'] in proofmap else '事後取得'}|{','.join(str(a['lane'])+a['status'] for a in r['accident_or_withdrawal']) or 'なし'}|")
    report+=['', '## 主要ケース']
    for rid in cases:
        r=next(z for z in rows if z['race_id']==rid);cl,pre,post=cases[rid];report.extend([f"### {r['venue']}{r['rno']}R：{r['trifecta']}、{r['payout']:,}円",f'評価：{cl}。',f'事前材料：{pre}',f'事後確認：{post}',f"[公式結果]({r['outcome']['details']['source_url']})",''])
    report+=['## 同日比較（探索）',f'江戸川・児島・唐津・住之江・尼崎の60Rを収集。欠場により展示5艇の尼崎10Rを除き、6艇比較可能な{len(comparison)}R（万舟15本、非万舟44本）を比較した。その他11件は万舟だけ追加したため、そちらをこの比較の分母には入れない。事後取得分を含み、場・級別・レース番組の交絡を調整していない。閾値4.5や風4mは本レポートの探索上の区切りであり、事前登録済みルールではない。','|項目|該当|R数|万舟|率|','|---|---|---:|---:|---:|']
    report += [f"|{c['feature']}|{'あり' if c['present'] else 'なし'}|{c['race_count']}|{c['manshu_count']}|{c['manshu_rate']:.1%}|" for c in comps]
    report+=['風・展示進入の変化・外の展示最速は、この同日集計では単独で万舟率上昇を示していない。1号艇全国勝率の低さは候補材料だが、今日の小標本だけで採用しない。住之江への偏りもあり、1号艇展示最速の高率を一般則にしない。','', '## 時刻と検証',f"万舟{len(manshu)}件のうち{summary['manshu_with_predeadline_git_version']}件は締切前コミットの保存版を確認し、展示タイム・展示ST・進入・登録番号を照合した。差異はpredeadline_verification.jsonに残す。残り{summary['manshu_retrospective_only']}件は今回取得した公式表示であり、当時取得済みに置き換えない。",'既存シャドーで保存済みの実判定は住之江10Rの1件（alert=false）。結果は92,690円なので不発の実例として記録する。他の未観測ケースを警戒失敗の分母に加えない。','新しい採用ルール・予想重みは変更していない。探索で見つけた材料は翌日以降の時系列で、場別・事故除外/含む・誤警報・回収率まで確認して採用候補にする。','', '## 保存内容と不足',f"71Rの全6艇結果426艇分を照合。既存公式結果36R・入力原本36Rを再利用。今回追加結果35R。万舟26件の展示6艇156艇分は全件揃う。尼崎10Rの3号艇欠場に伴う展示欠測は構造的欠測として明示。",'原本はraw/のgzip+base64、取得時刻・出典・SHA-256はacquisitions/、既存原本の参照はraces/内。全6艇の登録番号・機番・展示・本番ST・着順はreview_cases.jsonに保存。機番の使用周期の未確認は各艇の欠測理由に残した。','予想入力はprerace_display、結果はoutcomeで分離。本番ST・着順・決まり手・払い戻しを事前材料に混ぜていない。','映像は公式場別参照リンクを保存し、攻め起点・内艇抵抗・連動艇は未確認として空欄。決まり手のみで動きを断定しない。当時の締切前オッズと取得時刻も未照合。','近隣検潮所の潮位を場内実測や流速には使わず、唐津に潮汐補正を追加していない。既存Discord・X・予想・取得・ワーカー・Secrets・設定の変更は0件。']
    formatted=[]
    for line in report:
        if line.startswith('|'):
            formatted.append(line)
        elif line:
            if formatted and formatted[-1]!='':formatted.append('')
            formatted.extend([line,''])
        elif formatted and formatted[-1]!='':formatted.append('')
    (P/'REPORT.md').write_text('\n'.join(formatted)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k not in ['verification','feature_comparisons','by_venue']},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
