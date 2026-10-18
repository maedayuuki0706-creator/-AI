import fs from 'node:fs/promises';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
const input=process.argv[2],output=process.argv[3];
if(!input||!output)throw new Error('workbook_data.json and output directory required');
const src=JSON.parse(await fs.readFile(input,'utf8'));await fs.mkdir(output,{recursive:true});
const wb=Workbook.create(),font='Noto Sans CJK JP';
function col(n){let s='';for(n++;n;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s;}
function val(h,v){
 if(v==null||v==='')return v==null?null:'';
 if(typeof v==='boolean')return +v;
 if(h==='日付'&&/^\d{4}-\d{2}-\d{2}$/.test(v))return new Date(v+'T00:00:00Z');
 if(h==='日付'&&/^\d{8}$/.test(v))return new Date(v.slice(0,4)+'-'+v.slice(4,6)+'-'+v.slice(6,8)+'T00:00:00Z');
 if(typeof v==='string'&&/^-?\d+(\.\d+)?$/.test(v)&&!/(ID|id|digest|SHA|選手番号|年月|場コード|状態|元データ|公式値)/.test(h)&&/数|R$|率|円|正解|的中|コース|艇番|実進入|標本|95/.test(h))return +v;
 return v;
}
for(const info of src.sheets)wb.worksheets.add(info.name);
const columns={};
for(let ix=0;ix<src.sheets.length;ix++){
 const info=src.sheets[ix],s=wb.worksheets.getItem(info.name),hs=Object.keys(info.rows[0]),last=info.rows.length+5;
 columns[info.name]=hs;s.showGridLines=false;
 const used=s.getRange(`A1:${col(hs.length-1)}${last}`);
 used.format.font={name:font,size:10,color:'#223047'};used.format.columnWidth=17;used.format.rowHeight=24;used.format.verticalAlignment='center';
 s.getRange('A2').values=[[info.name==='概要'?'4場専門AI Phase 2 品質監査と比較研究':info.name]];
 s.getRange('A2').format.font={name:font,size:15,bold:true,color:'#233E63'};
 s.getRange('A3').values=[[info.description]];s.getRange('A3').format.font={name:font,size:10,italic:true,color:'#56637B'};
 const jp={race_id:'レースID',field:'項目',original:'元データ',official:'公式値',resolution:'処理',source_sha256:'公式SHA256'};
 s.getRange(`A5:${col(hs.length-1)}5`).values=[hs.map(h=>jp[h]||h)];
 for(let start=0;start<info.rows.length;start+=4000){
  const part=info.rows.slice(start,start+4000).map(r=>hs.map(h=>val(h,r[h])));
  s.getRange(`A${start+6}:${col(hs.length-1)}${start+5+part.length}`).values=part;
 }
 const t=s.tables.add(`A5:${col(hs.length-1)}${last}`,true,'FourVenueResearch'+ix);t.showFilterButton=true;
 s.getRange(`A5:${col(hs.length-1)}5`).format={fill:'#233E63',font:{name:font,size:10,bold:true,color:'#FFFFFF'},rowHeight:48,wrapText:true,horizontalAlignment:'center',verticalAlignment:'center'};
 for(let j=0;j<hs.length;j++){
  const h=hs[j],c=col(j),body=s.getRange(`${c}6:${c}${last}`),whole=s.getRange(`${c}5:${c}${last}`);
  if(/率|割合|95下限|95上限|差_/.test(h))body.setNumberFormat('0.0%');
  if(h==='日付'){body.setNumberFormat('yyyy-mm-dd');whole.format.columnWidth=15;}
  if(/ID|race_id/.test(h)){body.setNumberFormat('0');whole.format.columnWidth=27;}
  if(/SHA|digest|URL/.test(h))whole.format.columnWidth=/URL/.test(h)?78:66;
  if(/反応|勝ち筋|負け筋|理由|条件|進路|リスク|根拠|考察|結論|内容|処理|制約|注意|不足項目|欠測項目|候補/.test(h))whole.format.columnWidth=45;
  if(/ユーザー考察|映像URL|映像確認日時|再検証結論/.test(h))body.format.fill='#FFF2CC';
 }
 if(info.name==='コース別'){
  const n=col(hs.indexOf('標本数'));
  for(const [num,rate] of [['1着数','1着率'],['2着数','2着率'],['3着数','3着率']]){
   const q=col(hs.indexOf(num)),p=col(hs.indexOf(rate));s.getRange(`${p}6:${p}${last}`).formulas=info.rows.map((_,i)=>[`=IF(${n}${i+6}=0,"判定不能",${q}${i+6}/${n}${i+6})`]);
  }
 }
 if(info.name==='決まり手連動'){
  const n=col(hs.indexOf('条件標本数')),k=col(hs.indexOf('該当数')),p=col(hs.indexOf('条件付き割合'));
  s.getRange(`${p}6:${p}${last}`).formulas=info.rows.map((_,i)=>[`=IF(${n}${i+6}=0,"判定不能",${k}${i+6}/${n}${i+6})`]);
 }
 if(['全艇展開','展開分岐','ユーザーレビュー'].includes(info.name)){
  s.getRange(`A6:${col(hs.length-1)}${last}`).format.rowHeight=info.name==='全艇展開'?240:110;
  for(let j=0;j<hs.length;j++)if(/反応|筋|理由|条件|進路|リスク|根拠|考察|シナリオ|不一致|結論/.test(hs[j]))s.getRange(`${col(j)}6:${col(j)}${last}`).format.wrapText=true;
 }
 if(info.name==='概要')s.tabColor='#233E63';
 else{s.freezePanes.freezeRows(5);s.freezePanes.freezeColumns(info.name==='全艇原票'?3:1);}
 console.log(JSON.stringify({sheet:info.name,rows:info.rows.length,columns:hs.length}));
}
const overview=wb.worksheets.getItem('概要'),rn=src.sheets.find(s=>s.name==='レース原票').rows.length+5;
for(let row=6;row<=9;row++){
 overview.getRange(`B${row}:E${row}`).formulas=[[
  `=COUNTIF('レース原票'!$C$6:$C$${rn},A${row})`,
  `=COUNTIFS('レース原票'!$C$6:$C$${rn},A${row},'レース原票'!$E$6:$E$${rn},1)`,
  `=COUNTIFS('レース原票'!$C$6:$C$${rn},A${row},'レース原票'!$F$6:$F$${rn},1)`,
  `=COUNTIFS('レース原票'!$C$6:$C$${rn},A${row},'レース原票'!$G$6:$G$${rn},1)`]];
}
wb.recalculate();
const expected=src.sheets[0].rows.map(r=>[r['取得R'],r['正常有効R'],r['事故等R'],r['同着R']]);
if(JSON.stringify(overview.getRange('B6:E9').values)!==JSON.stringify(expected))throw new Error('Source/summary reconciliation failed');
console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:20},maxChars:1500})).ndjson);
for(let i=0;i<src.sheets.length;i++){
 const sheetName=src.sheets[i].name,range=i===0?'A1:H10':sheetName==='全艇展開'?'E4:J7':sheetName==='展開分岐'?'E4:J8':'A4:F11';
 const png=await wb.render({sheetName,range,scale:1,format:'png'});await fs.writeFile(`${output}/preview_${i+1}.png`,new Uint8Array(await png.arrayBuffer()));
}
const file=await SpreadsheetFile.exportXlsx(wb);await file.save(`${output}/four_venue_phase2_analysis_20261018.xlsx`);
console.log('FINAL_EXPORTED');
