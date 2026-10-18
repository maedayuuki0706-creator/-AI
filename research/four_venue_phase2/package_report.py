"""Build Japanese workbook inputs and a reviewable research report from evidence."""
import argparse,csv,json
from collections import Counter
from pathlib import Path
from research.edogawa_phase2.acquire import put

def rows(p):return list(csv.DictReader(Path(p).open(encoding='utf-8-sig')))
def run(study,out):
    root=Path(study);out=Path(out);summary=json.loads((root/'summary.json').read_text())
    records=json.loads((root/'audited_races.json').read_text());tables=json.loads((root/'analysis_tables.json').read_text())
    validation=json.loads((root/'validation_summary.json').read_text());paired=rows(root/'paired_comparison.csv')
    sheets=[]
    def add(name,description,data):
        sheets.append({'name':name,'description':description,'rows':data or [{'状態':'該当原本なし・0件。成功扱いしない'}]})
    overview=[]
    for r in summary['venues']:
        overview.append({'場':r['場'],'取得R':r['取得R'],'正常有効R':r['正常有効R'],'事故等R':r['異常確認R'],'同着R':r['同着R'],
            '開催日数':r['開催日数'],'学習R':r['学習R'],'検証R':r['検証R'],'最終評価R':r['最終評価R'],
            '級別6艇確認R':r['級別6艇確認R'],'進入変更R':r['進入変更R'],'改良版締切前実測R':0,'改善判定':'100/300Rの前向き実測待ち'})
    add('概要','2025-10-18〜2026-10-17。通常・事故等・同着を分離。改良版の前向き実測は0R。',overview)
    comparisons=[]
    for r in validation['comparison']:
        ci=r.get('day_cluster_bootstrap_95',[None,None]);comparisons.append({'場':r['場'],'改良版':r['改良版'],'同入力比較R':r['同入力比較R'],
          '既存的中数':r['既存的中数'],'改良的中数':r['改良的中数'],'既存的中率':r['既存的中率'],'改良的中率':r['改良的中率'],
          '開催日数':r['days'],'的中率差95下限':ci[0],'的中率差95上限':ci[1],'判定':r['status'],'前向き研究R':0,'ROI':None,'トリガミ率':None})
    add('同条件比較','改良は凍結済み事前入力を使った後付け研究。開催日/標本不足により改善判定不能。',comparisons)
    add('コース別','通常6艇のみ。実進入コースで集計。率は該当数÷標本数。Wilson 95%区間。',tables['course'])
    add('決まり手連動','実攻め起点は映像未確認。勝者の決まり手と2・3着実進入の条件付き分布。',tables['conditional'])
    add('水面分析','風速m/s・波高cm。月別も併記。潮位/流速の対応観測なし。相関から因果を断定しない。',tables['environment'])
    add('交絡確認','同選手・同コース・同月で弱風/強風を比較。開催節・相手・機力は未調整。',tables['confounding'])
    add('選手適性','通常6艇の出走単位。実ST秒は事後情報。全国同期間の成績差・道中逆転は未検証。',tables['racers'])
    add('モーター月別','番号再利用/交換日未監査。月別の記述値のみ。出足・伸びの性能を確定しない。',tables['motors'])
    add('時系列A評価','学習は6/30まで。事前原本がないためAのみ枠なりを仮定した後付け診断。',validation['historical'])
    add('比較レース','既存は締切前受領済み原本。改良A/Bは後付け再計算。仮想10点×100円。',paired)
    paths=[];reviews=[]
    for p in sorted((root/'replays').glob('*.json')):
        log=json.loads(p.read_text());pred=log['research_replay'];meta=pred['meta']
        actual=log['actual_trifecta'];scenario=pred['primary_scenario']
        reviews.append({'レースID':meta['race_id'],'日付':meta['day'],'場':next(r['場'] for r in summary['venues'] if r['場コード']==pred['venue_code']),
            '改良版':pred['variant'],'研究区分':'後付け研究','本命3連単':pred['primary_prediction'],'実出目':actual,
            '想定攻め起点':scenario['attack_origin_lane'],'想定決まり手':scenario['tactic'],'実攻め起点':None,'実戦術確認':'映像未確認',
            '予測の不一致':' / '.join(log['prediction_error']),'舟券の不一致':' / '.join(log['ticket_loss_reason']),
            'ユーザー考察':'','映像URL':'','映像確認日時':'','再検証結論':'','モデルdigest':pred['model_digest']})
        for b in pred['lanes']:
            paths.append({'レースID':meta['race_id'],'日付':meta['day'],'場コード':pred['venue_code'],'改良版':pred['variant'],
                '艇番':b['lane'],'選手名':b['name'],'選手番号':b['racer_id'],'予想コース':b['predicted_course'],
                '勝ち筋':' / '.join(b['win_paths']),'負け筋':' / '.join(b['loss_paths']),
                '攻め起点と反応':' / '.join(str(h['attack_origin_lane'])+'号艇起点 '+h['tactic']+' '+','.join(str(x['lane'])+'号艇:'+x['hypothesis'] for x in h['reactions']) for h in b['hypotheses']),
                '連動候補':' / '.join(h['id']+':'+','.join(f['combination'] for f in h['formations']) for h in b['hypotheses']),
                '根拠と不確実性':b['unlikely_or_uncertain_reason'],'代替シナリオ':' / '.join(b['alternative_scenarios']),
                '道中逆転リスク':b['reversal_risk'],'ユーザー考察':''})
    add('全艇展開','実在の凍結済み事前入力から後付け再計算。全6艇・他5艇反応・連動候補。',paths)
    add('ユーザーレビュー','黄色欄に考察・映像・再検証結論を記入。元予想は変更せずレースIDと版で紐付ける。',reviews)
    rawraces=[];boats=[]
    for r in records:
        rawraces.append({'レースID':r['race_id'],'日付':r['date'],'場':r['venue'],'R':r['race_no'],
            '正常有効':int(r['normal_eligible']),'事故等確認':int(r['abnormal_confirmed']),'同着':int(r.get('dead_heat_confirmed',False)),
            '締切予定':r.get('deadline_scheduled'),'実決まり手':r['method'],'実出目':r.get('trifecta'),
            '全配当':'; '.join(x['combination']+':'+str(x['payout_per_100'])+'円' for x in r.get('official_trifectas',[])),
            '風速m毎秒':r.get('wind_m'),'風向':r.get('wind_dir'),'波高cm':r.get('wave_cm'),'天候':r.get('weather'),
            '欠測項目':','.join(r['missing_fields']),'取得元URL':r['source_url'],'取得日時':r.get('observed_at'),'SHA256':r['sha256']})
        for b in r['boats']:
            boats.append({'レースID':r['race_id'],'日付':r['date'],'場':r['venue'],'選手名':b.get('name'),'選手番号':b['racer_id'],
                '艇番':b['lane'],'実進入':b.get('course'),'着順':b.get('finish'),'状態':b['status'],'実決まり手':r['method'],
                '風速m毎秒':r.get('wind_m'),'風向':r.get('wind_dir'),'波高cm':r.get('wave_cm'),
                '本番ST秒':b.get('actual_st'),'展示秒':b.get('exhibition_time'),'級別':b.get('racer_class'),
                'モーター番号':b.get('motor_number'),'ボート番号':b.get('boat_number'),'平均ST秒':None})
    add('レース原票','公式Kの事後記録。B番組の締切予定は当時の確定締切や受領証ではない。',rawraces)
    add('全艇原票','1行1艇。日付・場・選手・実進入・決まり手・風速でフィルター可能。本番STは事後情報。',boats)
    missing=Counter((r['場'],r['field'],r['reason']) for r in tables['missing'])
    add('欠測監査','レース/項目単位で集計。原票の欠測と公式の異常着順・同着を区別する。',
        [{'場':v,'不足項目':f,'件数':n,'理由':reason} for (v,f,reason),n in sorted(missing.items())])
    add('差分監査','江戸川元CSVと公式値、B/K差分。元CSV/原本は不変。',tables['differences'])
    add('日別取得','365日×4場。取得失敗を非開催扱いしない。Kにない予定レースは別途確認。',tables['coverage'])
    add('Phase1と未達','Phase2の研究開始・コード動作をPhase1完了扱いにしない。',[
        {'項目':'新ゆうき完全原本の自動保存','状態':'未完了','必要作業':'6艇・展開・固定10点・締切前リモート受領の実測'},
        {'項目':'浜名湖実開催保存','状態':'未完了','必要作業':'公式日程2026-10-21開始。前検・展示・締切前保存を実測'},
        {'項目':'保存率95%以上を7日継続','状態':'未完了','必要作業':'日別対象R/受領成功/欠測理由を7日追跡'},
        {'項目':'10月17日の欠測','状態':'11R欠測を維持','必要作業':'江戸川6R・児島5R。事後生成で穴埋めしない'},
        {'項目':'改良版の独立自動稼働','状態':'未稼働・実測0R','必要作業':'mainを変えず使える独立実行基盤を確定。新workflowは既定ブランチ未登録'},
        {'項目':'100R/300R評価','状態':'未到達','必要作業':'4場別に同レース・同入力・締切前受領で収集'},
        {'項目':'改良C','状態':'停止','必要作業':'潮/選手/機力の欠測と交絡を解消し、独立時系列で検証'}])
    add('方式と未検証','取得証拠・分析と予想の時間関係・改善判定の条件。',[
        {'項目':'出典','内容':'BOATRACE公式K/B。SHA256・URL・実際の取得時刻を保存。江戸川元CSVは公式で監査'},
        {'項目':'決まり手と本番ST','内容':'事後の学習ラベル/記述に限定。対象レースの予想入力には入れない'},
        {'項目':'攻め起点と1着','内容':'勝者の決まり手から他艇の実際の攻めを推定ラベルにしない。映像ラベルが必要'},
        {'項目':'A','内容':'場ごとの学習期コース分布。過去は枠なりを仮定した限定的な後付け診断'},
        {'項目':'B','内容':'6艇の展開・起点と反応の仮説を事前根拠で順位付け。構造順位は未検証'},
        {'項目':'C','内容':'潮位/流速・選手・モーターを検証済み係数として採用できず停止'},
        {'項目':'オッズ','内容':'過去オッズ原本なし。ROI/トリガミ率は推測しない。払戻とオッズは別項目'},
        {'項目':'最終テストの限界','内容':validation['holdout_limit']},
        {'項目':'潮と機力','内容':'観測点・時刻・単位の対応、モーター交換日、出足/伸びの実測なし。係数不採用'},
        {'項目':'日本語Excel','内容':'率の単純算術は数式。複雑な集計は保存済みPython/CSVから再生成。原票編集は集計に自動反映しない'}])
    put(out/'workbook_data.json',json.dumps({'study':str(root),'run_id':summary['run_id'],'sheets':sheets},ensure_ascii=False).encode())
    lines=['# 4場専門AI Phase 2 研究報告','',f"対象期間: 2025-10-18〜2026-10-17 / 研究ID `{summary['run_id']}`",'',
           'Phase2は未完了。既存AI・Discord・X・main・Secrets・既存LOGを変更せず、研究ブランチに追加した。',
           '', '|場|公式R|通常6艇|事故等|同着|学習|検証|最終|','|---|---:|---:|---:|---:|---:|---:|---:|']
    lines += ['|'+ '|'.join(str(r[k]) for k in ['場','取得R','正常有効R','異常確認R','同着R','学習R','検証R','最終評価R'])+'|' for r in summary['venues']]
    lines += ['', '## 品質監査', '', 'K原本365日を確認。既存174日を再利用、新規191日、失敗0日。計8876R、通常8192R、事故等682R、同着2R。',
              '江戸川は元2041Rを全件公式照合し、公式にある28Rを追加。元212Rの着順不足は公式異常記録と確認し、欠落順位を作らなかった。',
              '児島2026-05-23 3Rは3着同着、浜名湖2026-05-31 7Rは2着同着。複数の3連単と配当を保存し、通常分布から分離した。',
              'KとBは独立原本。B/K選手IDが一致した場合だけ級別等を結合。締切予定を締切前受領の証拠に使わない。',
              '', '## 同入力比較（改良は後付け）','', '|場|版|R|既存的中|改良的中|判定|','|---|---|---:|---:|---:|---|']
    lines += ['|'+ '|'.join(str(r[k]) for k in ['場','改良版','同入力比較R','既存的中数','改良的中数','status'])+'|' for r in validation['comparison']]
    lines += ['', 'BはAより江戸川・唐津で各1R的中が少ない。1〜2開催日・48Rの後付け比較で、安定した改善/悪化は判定不能。Cは未検証係数のため停止。',
              '既存49原本のうち児島20261018_16_06は1号艇返還を公式照合済み。返還確認1Rは別集計。残り48Rも全6艇の確定着順は未結合のため「返還なし」と表示し、通常展開確認済みとはしない。',
              '', '## 実装と検証', '', '共通エンジンは既存scenario_v2を再利用。4場別学習、A/B固定10点×100円、全6艇の勝ち筋/負け筋・攻め起点・他5艇反応・不採用理由を保存。',
              '独立LOGは予想/受領/結果/レビュー/失敗に分離。同一レース二重生成、締切後保存、他ブランチ/保存先への書込を禁止。push最大3回・リモート原本読戻し・排他制御・中断後resumeに対応。',
              '新しいGitHub定期ジョブは起動していない。手動workflowは研究ブランチにのみ追加し、mainへの登録は行っていない。前向き研究は0R。',
              '', '## 不足と次段階', '', '平均STの歴史事前原本、潮位/流速の時刻・単位/地点対応、前検、返還明細、モーター交換日、実攻め起点/旋回の映像ラベルが不足。推測で埋めない。',
              'Phase1の完全保存・浜名湖稼働・7日95%以上を別管理。研究を開始しただけでは達成扱いにしない。',
              'Phase3前に独立実行基盤の稼働、各場100R/300Rの実開催同条件比較、日クラスタ不確実性、C係数の逐次検証と新しい未観測期間での評価が必要。']
    put(out/'REPORT.md',('\n'.join(lines)+'\n').encode());print(json.dumps({'report':str(out),'sheets':len(sheets),'rows':{s['name']:len(s['rows']) for s in sheets}},ensure_ascii=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--study',required=True);p.add_argument('--out',required=True);a=p.parse_args();run(a.study,a.out)
