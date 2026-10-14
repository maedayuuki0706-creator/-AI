"""Scoped native Sheets payloads. Full 120-way forecasts remain in originals.

Existing manual controls are retained. The derived bet view is explicitly
bounded; authoritative originals and full-cohort metrics are not truncated.
"""
from . import core

IDS={'新ゆうき予想LOG':141400001,'艇別勝ち負けLOG':141400002,'研究予想原本':141400003,
     '事後検証':141400004,'保存確認':141400005,'EV閾値比較':141400006,
     '日別場別AI成績':141400007,'欠測・遅延LOG':141400008,'研究ジョブ稼働':141400009,
     'EV120通り閲覧':141400010}

FORECAST_HEADERS=['予想ID','日付','場','R','モデル','データ区分','予想生成時刻','締切','モデル版','本線','抑え','BOX','全採用買い目',
                  '1頭確率','2頭確率','3頭確率','4頭確率','5頭確率','6頭確率','原本確率件数','オッズ件数','記録状態','未取得項目',
                  '事前原本SHA256','元GitHub SHA','参照原本','結果状態','的中','検証理由','原本モデル版']
BET_HEADERS=['予想日(YYYYMMDD)','場','R','AI/モデル','研究プラン','買い目(1-2-3)','予想発行時刻','締切時刻','事前推定確率(0-1)',
             '事前オッズ(倍)','EV(自動)','EV1.4印(固定1.4)','仮想投資額(円)','的中','仮想払戻額(円)','結果状態','純損益','券回収率','実結果3連単','レースキー','出典・予想ID','原本オッズ保存時刻','データ区分','備考']
METRIC_HEADERS=['データ区分','モデル','集計区分','EV閾値','対象レース','対象買い目','的中券','券的中率','的中レース','レース的中率',
                '仮想投資','仮想払戻','回収率','純損益','最大連敗R','最大DD円','中穴的中券','万舟的中券','中穴払戻','万舟払戻','中穴純寄与','万舟純寄与','必要資金目安','評価']
METRIC_KEYS=['cohort','model','group','threshold','races','bets','hits','hit_rate','race_hits','race_hit_rate','investment','payout','roi','profit',
             'max_loss_streak_races','max_drawdown_yen','mid_hits','manshu_hits','mid_gross_payout','manshu_gross_payout','mid_net_contribution','manshu_net_contribution','needed_capital_yen','assessment']

def cell(v):
    if v is None:return {}
    if isinstance(v,bool):return {'userEnteredValue':{'boolValue':v}}
    if isinstance(v,(int,float)):return {'userEnteredValue':{'numberValue':v}}
    if len(str(v))>49000:raise ValueError('Google cell size guard: split/archive record first')
    return {'userEnteredValue':{'stringValue':str(v)}}

def write(sheet,start,rows):
    width=max((len(x) for x in rows),default=1)
    return {'updateCells':{'range':{'sheetId':sheet,'startRowIndex':start,'endRowIndex':start+len(rows),'startColumnIndex':0,'endColumnIndex':width},
                           'rows':[{'values':[cell(x) for x in r]+[{}]*(width-len(r))} for r in rows], 'fields':'userEnteredValue'}}

def formula(sheet,row,col,text):
    return {'updateCells':{'start':{'sheetId':sheet,'rowIndex':row,'columnIndex':col},'rows':[{'values':[{'userEnteredValue':{'formulaValue':text}}]}], 'fields':'userEnteredValue'}}

def layout(sheet,width,rows):
    return [
      {'updateSheetProperties':{'properties':{'sheetId':sheet,'gridProperties':{'frozenRowCount':1,'frozenColumnCount':1}},'fields':'gridProperties.frozenRowCount,gridProperties.frozenColumnCount'}},
      {'repeatCell':{'range':{'sheetId':sheet,'startRowIndex':0,'endRowIndex':1,'startColumnIndex':0,'endColumnIndex':width},'cell':{'userEnteredFormat':{'backgroundColor':{'red':.94,'green':.94,'blue':.94},'textFormat':{'bold':True},'wrapStrategy':'WRAP'}},'fields':'userEnteredFormat'}},
      {'updateDimensionProperties':{'range':{'sheetId':sheet,'dimension':'COLUMNS','startIndex':0,'endIndex':width},'properties':{'pixelSize':130},'fields':'pixelSize'}},
      {'repeatCell':{'range':{'sheetId':sheet,'startRowIndex':1,'endRowIndex':max(rows,2),'startColumnIndex':0,'endColumnIndex':width},'cell':{'userEnteredFormat':{'verticalAlignment':'TOP','wrapStrategy':'CLIP','textFormat':{'fontSize':10}}},'fields':'userEnteredFormat'}},
      {'setBasicFilter':{'filter':{'range':{'sheetId':sheet,'startRowIndex':0,'endRowIndex':max(rows,2),'startColumnIndex':0,'endColumnIndex':width}}}}
    ]

def tables(records,results,receipts):
    rmap={r['id']:r for r in results};out={}
    out['研究予想原本']=[['予想ID','SHA256','固定予想JSON（120通り・6艇根拠）','区分']]+[[f['id'],f['hash'],core.dumps(f),f['cohort']] for f in records]
    out['事後検証']=[['予想ID','原本SHA256','結果・検証JSON','照合時刻']]+[[r['id'],r['forecast_hash'],core.dumps(r),r['settled_at']] for r in results]
    out['保存確認']=[['予想ID','原本SHA256','保存成功確認時刻','締切前保存済']]+[[r['id'],r['forecast_hash'],r['persisted_at'],r['eligible_live']] for r in receipts]
    logs=[FORECAST_HEADERS];boats=[['予想ID','日付','場','R','モデル','区分','艇','想定コース','頭確率','勝ち筋（仮説）','成立条件','負け筋（仮説）','取得した根拠JSON','非軸理由','未取得・未検証','検証状態']]
    missing=[['予想ID','日付','場','R','モデル','区分','状態','未取得／標本不足','取得時刻']]
    betrows=[]
    for f in records:
        r=rmap.get(f['id']);off=r['official'] if r else None
        logs.append([f['id'],f['day'],f['venue'],f['rno'],f['model'],f['cohort'],f['generated_at'],f['deadline'],f['version'],
                     ' / '.join(f['main']),' / '.join(f['cover']),' / '.join(f['box']),' / '.join(f['picks']),
                     *[f['heads'][str(i)] for i in range(1,7)],sum(t['probability'] is not None for t in f['tickets']),sum(t['odds'] is not None for t in f['tickets']),
                     f['availability'],' / '.join(f['missing']),f['hash'],f['source_sha'],'研究予想原本:'+f['id'],
                     off['status'] if off else '未確定',('○' if r['hit'] else '×') if r else '', ' / '.join(r['review']) if r else '結果待ち',f['source_model_version']])
        for s in f['scenarios']:
            boats.append([f['id'],f['day'],f['venue'],f['rno'],f['model'],f['cohort'],s['lane'],s['predicted_course'],f['heads'][str(s['lane'])],s['win_path'],s['conditions'],s['lose_path'],core.dumps(s['evidence']),s['non_axis_reason'],' / '.join(s['missing']),s['evidence_status']])
        if f['missing']:missing.append([f['id'],f['day'],f['venue'],f['rno'],f['model'],f['cohort'],f['availability'],' / '.join(f['missing']),f['generated_at']])
        if f['cohort']!='締切前固定':missing.append([f['id'],f['day'],f['venue'],f['rno'],f['model'],f['cohort'],'遅延／過去再計算','研究モデルは締切前に固定していないため本当の予想成績へ算入しない',f['generated_at']])
        if f['availability']!='記録可':continue
        for t in f['tickets']:
            if t['ev'] is None or t['ev']<1.05:continue
            inv,pay,hit=core.payoff(t,off) if off else (100,None,None)
            state='確定' if off else '未確定'
            betrows.append([f['day'],f['venue'],f['rno'],f['model'],f['plan'],t['combination'],f['generated_at'],f['deadline'],t['probability'],t['odds'],t['ev'],t['mark'],inv,('○' if hit else '×') if hit is not None else '',pay,state,pay-inv if pay is not None else None,pay/inv if pay is not None and inv else None,' / '.join(off['payouts']) if off else '',f['race_key'],f['id'],f['odds_asof'],f['cohort'],'返還券は投資0・ROI除外' if inv==0 else '全120通りEV仮想研究。既存採用買い目と別。'])
    out['新ゆうき予想LOG']=logs;out['艇別勝ち負けLOG']=boats;out['欠測・遅延LOG']=missing
    stats=core.metrics(records,results,receipts)
    out['EV閾値比較']=[METRIC_HEADERS]+[[s[k] for k in METRIC_KEYS] for s in stats if s['group'] in ('総計','全モデル共通')]
    out['日別場別AI成績']=[METRIC_HEADERS]+[[s[k] for k in METRIC_KEYS] for s in stats if s['group'] not in ('総計','全モデル共通')]
    out['EV買い目ログ']=[BET_HEADERS]+sorted(betrows,key=lambda r:(r[0],r[7],r[20]),reverse=True)[:1000]
    # All six thresholds are applied to all valid 120 outcomes, not just main/cover.
    out['研究ジョブ稼働']=[['項目','値'],['実装版',core.VERSION],['研究原本数',len(records)],['実レース数',len(set(f['race_key'] for f in records))],['締切前保存確認',sum(r['eligible_live'] for r in receipts)],['履歴の上書き','禁止／原本SHA256照合'],['テスト混入','テスト用fixtureはこのログへ入れない'],['定期方式','認証複製を伴わない接続済みアプリの独立タスク。最高頻度1時間。'],['高頻度Cron','未稼働：認証複製が自動審査で拒否された'],['配信処理','通知・X投稿・既存Actions呼出しなし'],['EV券詳細表示','直近1000券。全120通りと全件集計は研究予想原本・EV閾値比較に保持'],['継続ROI120%','まだ未検証。過去再計算をライブ成績と混ぜない']]
    latest=next((f for f in reversed(records) if f['availability']=='記録可'),None)
    rows=[['最新の研究原本の120通り','モデル','区分','確率','原本オッズ','EV','★EV1.4+']]
    if latest:
        rows += [[t['combination'],latest['model'],latest['cohort'],t['probability'],t['odds'],t['ev'],t['mark']] for t in latest['tickets']]
    out['EV120通り閲覧']=rows
    return out

def payloads(records,results,receipts):
    data=tables(records,results,receipts);batches=[]
    # Scaffold batch is used only after metadata proves these IDs/names absent.
    scaffold=[]
    for name,sheet in IDS.items():
        width=max(len(r) for r in data[name]);count=max(5000 if name=='EV閾値比較' else 1000,len(data[name])+100)
        scaffold.append({'addSheet':{'properties':{'sheetId':sheet,'title':name,'gridProperties':{'rowCount':count,'columnCount':max(26,width)}}}})
    batches.append(scaffold)
    batches.append([{'updateSheetProperties':{'properties':{'sheetId':100000001,'gridProperties':{'rowCount':max(2000,len(data['EV買い目ログ'])+100)}},'fields':'gridProperties.rowCount'}}])
    for name,rows in data.items():
        sheet=100000001 if name=='EV買い目ログ' else IDS[name]
        # Originals carry long JSON; use two records per transaction.
        chunk=2 if name=='研究予想原本' else 25
        for start in range(0,len(rows),chunk):batches.append([write(sheet,start,rows[start:start+chunk])])
        batches.append(layout(sheet,len(rows[0]),len(rows)))
    # Formula-based dashboard: model + cohort + EV selector, no hard-coded star filter.
    dash=1787762466
    requests=[write(dash,1,[['EV=原本確率×原本オッズ。1点100円の仮想研究。過去再計算と締切前保存を分離。']]),
              write(dash,5,[['★はEV1.4以上に固定。B4は比較閾値。E4はモデル。K4はデータ区分。']]),
              {'updateCells':{'start':{'sheetId':dash,'rowIndex':3,'columnIndex':9},'rows':[{'values':[cell('集計区分'),cell('締切前固定')]}],'fields':'userEnteredValue'}},
              {'setDataValidation':{'range':{'sheetId':dash,'startRowIndex':3,'endRowIndex':4,'startColumnIndex':1,'endColumnIndex':2},'rule':{'condition':{'type':'ONE_OF_LIST','values':[{'userEnteredValue':str(t)} for t in core.THRESHOLDS]},'strict':True,'showCustomUi':True}}},
              {'setDataValidation':{'range':{'sheetId':dash,'startRowIndex':3,'endRowIndex':4,'startColumnIndex':10,'endColumnIndex':11},'rule':{'condition':{'type':'ONE_OF_LIST','values':[{'userEnteredValue':'締切前固定'},{'userEnteredValue':'過去再計算'}]},'strict':True,'showCustomUi':True}}}]
    # Keep E4's existing validation and selected model. SUMIFS aggregate per-model
    # rows; model-specific drawdown/streak shown in the comparison table.
    condition="'EV閾値比較'!$A$2:$A$5000,$K$4,'EV閾値比較'!$C$2:$C$5000,\"総計\",'EV閾値比較'!$D$2:$D$5000,$B$4,'EV閾値比較'!$B$2:$B$5000,$E$4"
    def summ(col):return '=SUMIFS(\'EV閾値比較\'!'+col+'2:'+col+'5000,'+condition+')'
    requests += [formula(dash,6,1,summ('F')),formula(dash,6,4,summ('G')),formula(dash,6,7,summ('E')),
                 formula(dash,8,1,summ('K')),formula(dash,8,4,summ('L')),formula(dash,8,7,'=IF(B9>0,E9/B9,"")'),
                 formula(dash,9,1,'=IF(B7>0,E7/B7,"")'),formula(dash,9,4,'=E9-B9'),formula(dash,9,7,'=IF(B7=0,"標本不足",IF(H9>=H4,"期間内目標達成／継続未検証","未達"))'),
                 write(dash,6,[['条件該当券'],]),
                 {'updateCells':{'start':{'sheetId':dash,'rowIndex':6,'columnIndex':3},'rows':[{'values':[cell('的中券')]}],'fields':'userEnteredValue'}},
                 {'updateCells':{'start':{'sheetId':dash,'rowIndex':6,'columnIndex':6},'rows':[{'values':[cell('対象レース（重複除外）')]}],'fields':'userEnteredValue'}},
                 write(dash,8,[['仮想投資額（確定）']]),
                 {'updateCells':{'start':{'sheetId':dash,'rowIndex':8,'columnIndex':3},'rows':[{'values':[cell('仮想払戻額（確定）')]}],'fields':'userEnteredValue'}},
                 write(dash,13,[['閾値6条件の比較：EV閾値比較。日別・場別：日別場別AI成績。全モデル共通集合はまだ不足。']])]
    batches.append(requests)
    compare=[]
    for i,letter in enumerate(core.MODELS,4):
        available=sum(f['plan']==letter and f['availability']=='記録可' for f in records)
        message='未取得／標本不足' if not available else '原本入力済／継続ROI未検証'
        compare.append({'updateCells':{'start':{'sheetId':100000002,'rowIndex':i,'columnIndex':3},'rows':[{'values':[cell(message),cell('不足は欠測・遅延LOGへ。過去再計算とライブを分離。'),cell('1点100円・全120通りのEV閾値研究')]}],'fields':'userEnteredValue'}})
        criteria="'EV閾値比較'!$A$2:$A$5000,'EV1.4集計'!$K$4,'EV閾値比較'!$B$2:$B$5000,$A"+str(i+1)+",'EV閾値比較'!$C$2:$C$5000,\"総計\",'EV閾値比較'!$D$2:$D$5000,1.4"
        for col,metriccol in [(6,'F'),(7,'G'),(9,'K'),(10,'L')]:compare.append(formula(100000002,i,col,"=SUMIFS('EV閾値比較'!"+metriccol+"2:"+metriccol+"5000,"+criteria+")"))
        compare.append(formula(100000002,i,8,'=IF(G'+str(i+1)+'>0,H'+str(i+1)+'/G'+str(i+1)+',"")'))
        compare.append(formula(100000002,i,11,'=IF(J'+str(i+1)+'>0,K'+str(i+1)+'/J'+str(i+1)+',"")'))
    batches.append(compare)
    return batches
