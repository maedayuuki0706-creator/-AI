import fs from 'node:fs/promises';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
const repo=process.argv[2] || process.cwd(),dir=process.argv[3] || repo+'/outputs/edogawa_phase2';await fs.mkdir(dir,{recursive:true});
const src=JSON.parse(await fs.readFile(repo+'/research/edogawa_phase2/report_20261018/workbook_data.json','utf8'));
const wb=Workbook.create(),font='Noto Sans CJK JP';
function col(n){let s='';for(n++;n;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s;}
const orders={
 'コース別':['コース','進入条件','標本数','1着数','2着数','3着数','1着率','2着率','3着率','1着率95下限','1着率95上限'],
 '決まり手連動':['1着コース','決まり手','2着コース','3着コース','該当数','条件標本数','条件付き割合'],
 '水面分析':['条件','区分','年月','標本数','1コース1着数','1コース1着率'],
 '交絡確認':['選手番号','コース','年月','弱風出走数','強風出走数','弱風1着率','強風1着率'],
 '選手適性':['選手番号','選手名','コース','出走数','1着数','1着率','95下限','95上限'],
 '時系列評価':['区分','モデル','標本数','的中数','的中率','95下限','95上限'],
 '月別有効数':['年月','取得R','公式照合R','正常有効R','異常確認R','未照合R']};
for(const info of src.sheets)wb.worksheets.add(info.name);
for(let ix=0;ix<src.sheets.length;ix++){
 const info=src.sheets[ix],s=wb.worksheets.getItem(info.name),all=Object.keys(info.rows[0]||{状態:''}),pre=orders[info.name]||[];
 const hs=[...pre,...all.filter(k=>!pre.includes(k))],last=info.rows.length+5;
 const vals=info.rows.map(r=>hs.map(h=>{
  const v=r[h];if(v==null||v==='')return v==null?null:'';
  if(typeof v==='boolean')return +v;
  if(h==='日付'&&/^\d{4}-\d{2}-\d{2}$/.test(v))return new Date(v+'T00:00:00Z');
  if(h==='日付'&&/^\d{8}$/.test(v))return new Date(v.slice(0,4)+'-'+v.slice(4,6)+'-'+v.slice(6,8)+'T00:00:00Z');
  if(typeof v==='string'&&/^-?\d+(\.\d+)?$/.test(v)&&!/(ID|id|digest|SHA|選手番号|年月|元値|元フラグ|コード)/.test(h))return +v;
  return v;
 }));
 s.showGridLines=false;const used=s.getRange(`A1:${col(hs.length-1)}${last}`);
 used.format.font={name:font,size:10,color:'#202B3B'};used.format.columnWidth=18;used.format.rowHeight=25;used.format.verticalAlignment='center';
 s.getRange('A2').values=[[info.name==='概要'?'江戸川くん Phase 2 品質監査と比較研究':info.name]];s.getRange('A2').format.font={name:font,size:15,bold:true,color:'#193A5C'};
 if(info.description){s.getRange('A3').values=[[info.description]];s.getRange('A3').format.font={name:font,size:10,italic:true,color:'#556375'};}
 const jpHeaders={race_id:'レースID',field:'項目',original:'元データ',official:'公式値',resolution:'処理',source_sha256:'公式SHA256'};
 s.getRange(`A5:${col(hs.length-1)}5`).values=[hs.map(h=>jpHeaders[h]||h)];s.getRange(`A6:${col(hs.length-1)}${last}`).values=vals;
 const t=s.tables.add(`A5:${col(hs.length-1)}${last}`,true,'EdogawaFinalTable'+ix);t.showFilterButton=true;
 s.getRange(`A5:${col(hs.length-1)}5`).format={fill:'#193A5C',font:{name:font,size:10,bold:true,color:'#FFFFFF'},rowHeight:48,wrapText:true,horizontalAlignment:'center',verticalAlignment:'center'};
 for(let j=0;j<hs.length;j++){
  const h=hs[j],c=col(j),r=s.getRange(`${c}6:${c}${last}`);
  if(/率|割合|95下限|95上限|差_/.test(h))r.setNumberFormat('0.0%');
  if(h==='日付')r.setNumberFormat('yyyy-mm-dd');
  if(/ID|race_id/.test(h)){r.setNumberFormat('0');s.getRange(`${c}5:${c}${last}`).format.columnWidth=27;}
  if(/SHA|digest|URL|反応|勝ち筋|負け筋|ユーザー考察|判定|制約|限界|採用|理由|扱い|実際/.test(h))s.getRange(`${c}5:${c}${last}`).format.columnWidth=/SHA|digest/.test(h)?68:/URL/.test(h)?80:42;
  if(/反応|勝ち筋|負け筋|判定|制約|限界/.test(h))r.format.wrapText=true;
  if(/ユーザー考察/.test(h))r.format.fill='#FFF2CC';
 }
 if(info.name==='コース別'){s.getRange(`G6:I${last}`).formulas=vals.map((_,i)=>[0,1,2].map(j=>`=IF(C${i+6}=0,"判定不能",${col(j+3)}${i+6}/C${i+6})`));s.getRange(`G6:K${last}`).setNumberFormat('0.0%');}
 if(info.name==='展開レビュー')s.getRange(`A6:${col(hs.length-1)}${last}`).format.rowHeight=85;
 if(info.name==='概要'){s.getRange('A5:A23').format.columnWidth=34;s.getRange('B5:B23').format.columnWidth=22;s.getRange('C5:C23').format.columnWidth=78;s.tabColor='#193A5C';}
 else{s.freezePanes.freezeRows(5);s.freezePanes.freezeColumns(1);}
 console.log('Populated '+info.name);
}
const sum=wb.worksheets.getItem('概要');
sum.getRange('B6').formulas=[["=COUNTA('元CSV'!A6:A2046)"]];sum.getRange('B8').formulas=[["=COUNTA('全レース監査'!A6:A2074)"]];sum.getRange('B9').formulas=[["=COUNTIFS('全レース監査'!E6:E2074,1)"]];sum.getRange('B10').formulas=[["=COUNTIFS('全レース監査'!F6:F2074,1)"]];
wb.recalculate();if(sum.getRange('B9').values[0][0]!==1850||sum.getRange('B10').values[0][0]!==219)throw new Error('Reconciliation failed');
console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:20},maxChars:1000})).ndjson);
for(let i=0;i<src.sheets.length;i++){const png=await wb.render({sheetName:src.sheets[i].name,range:i===0?'A1:C14':'A4:F11',scale:1.2,format:'png'});await fs.writeFile(dir+`/jp_preview_${i+1}.png`,new Uint8Array(await png.arrayBuffer()));}
const x=await SpreadsheetFile.exportXlsx(wb);await x.save(dir+'/edogawa_phase2_quality_analysis_20261018.xlsx');console.log('FINAL_EXPORTED');
