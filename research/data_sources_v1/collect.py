"""Resume dated public API downloads; retain raw evidence and unknowns.

Historical API snapshots are retrospective research, never pre-deadline receipts.
Run from the repository root with python -m research.data_sources_v1.collect.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import urllib.error
import urllib.request

VENUES = {'03': '江戸川', '16': '児島', '23': '唐津', '06': '浜名湖'}
BASELINE_REF = 'origin/research/four-venue-phase2-20261018'
BASELINE_PATH = ('data/research_four_venue_phase2/20251018_20261017/'
                 'studies/eed2cf3775203abb/audited_races.json.gz')
SOURCES = {
    'turnmark': 'https://turnmark.github.io/api/v1/{year}/{day}.json',
    'openapi': 'https://boatraceopenapi.github.io/api/v1/{year}/{day}.json',
    'legacy_programs': 'https://boatraceopenapi.github.io/programs/v3/{year}/{day}.json',
    'legacy_previews': 'https://boatraceopenapi.github.io/previews/v3/{year}/{day}.json',
}
JST = timezone(timedelta(hours=9))
MAX_BYTES = 16_000_000
GAP_FIELDS = ('average_st', 'exhibition_st', 'exhibition_course', 'tilt',
              'parts', 'propeller_exchange', 'refund_lanes', 'historical_odds', 'preview_wind_direction_text',
              'tide_observation', 'current_observation', 'motor_service_period',
              'preinspection', 'video_attack_origin', 'prerace_receipt')


def stamp():
    return datetime.now(timezone.utc).isoformat()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def atomic(path, raw):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_bytes(raw)
    os.replace(temp, path)


def save_json(path, obj):
    atomic(path, encode(obj))


def days(start, end):
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first > last or first < date(2025, 5, 1):
        raise ValueError('Invalid supported research range')
    if last >= datetime.now(JST).date():
        raise ValueError('Historical collector only accepts completed JST days')
    return [(first + timedelta(days=i)).isoformat() for i in range((last-first).days+1)]


class Client:
    def __init__(self, root, interval=1.0):
        self.root = Path(root)
        self.lock = threading.Lock()
        self.next_request = 0.0
        self.interval = interval

    def read(self, source, day, retry_failed=False):
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError('Need an ISO calendar day')
        path = self.root / 'downloads' / source / (day + '.json')
        if path.exists():
            meta = json.loads(path.read_bytes())
            if meta['status'] == 'ok':
                body = gzip.decompress((self.root / meta['raw_path']).read_bytes())
                if digest(body) != meta['sha256']:
                    raise ValueError('Raw cache digest mismatch')
                return meta, json.loads(body)
            if not retry_failed:
                return meta, None
        compact = day.replace('-', '')
        url = SOURCES[source].format(year=compact[:4], day=compact)
        meta = {'source': source, 'day': day, 'url': url, 'requested_at': stamp(),
                'upstream_family': 'BOATRACE_official_derived', 'official': False,
                'prospective_verified': False}
        try:
            with self.lock:
                wait = max(0.0, self.next_request-time.monotonic())
                if wait:
                    time.sleep(wait)
                self.next_request = time.monotonic() + self.interval
            req = urllib.request.Request(url, headers={'User-Agent': 'BoatAI-DataResearch/1.0',
                                                       'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=25) as response:
                if response.geturl() != url:
                    raise ValueError('Unexpected redirect')
                body = response.read(MAX_BYTES+1)
                meta['etag'] = response.headers.get('ETag')
                meta['last_modified'] = response.headers.get('Last-Modified')
            if not body or len(body) > MAX_BYTES:
                raise ValueError('Empty or oversized response')
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError('API root must be an object')
            sha = digest(body)
            raw_path = 'raw/' + sha + '.json.gz'
            atomic(self.root/raw_path, gzip.compress(body, mtime=0))
            meta.update(status='ok', sha256=sha, raw_path=raw_path, bytes=len(body), observed_at=stamp())
        except Exception as exc:
            meta.update(status='unavailable_not_no_race', error_type=type(exc).__name__,
                        error=str(exc)[:250], observed_at=stamp())
            payload = None
        # Receipt records are content-addressed; latest index supports resume.
        save_json(self.root/'download_receipts'/source/(day+'_'+digest(encode(meta))[:16]+'.json'), meta)
        save_json(path, meta)
        return meta, payload


def race_identity(row, day, stadium, race_no, number_key='race_number'):
    jcd, rno = int(stadium), int(race_no)
    if row.get('date') != day or int(row.get('stadium_number', -1)) != jcd or int(row.get(number_key, -1)) != rno:
        raise ValueError('API race identity mismatch')
    if not 1 <= jcd <= 24 or not 1 <= rno <= 12:
        raise ValueError('Invalid race identity')
    return day.replace('-', '') + f'{jcd:02}{rno:02}'


def modern(payload, day):
    stadiums = payload.get('programs', {}).get('stadiums')
    if not isinstance(stadiums, dict) or not stadiums:
        raise ValueError('Missing stadium map; not evidence of no racing')
    out = {}
    for stadium, venue in stadiums.items():
        for number, row in venue.get('races', {}).items():
            rid = race_identity(row, day, stadium, number)
            if f'{int(stadium):02}' not in VENUES:
                continue
            for name in ('preview', 'odds', 'result'):
                section = row.get(name)
                if section and any(section.get(k) is not None for k in ('date', 'stadium_number', 'race_number')):
                    race_identity(section, day, stadium, number)
            if rid in out:
                raise ValueError('Duplicate race identity')
            out[rid] = row
    return out


PROGRAM_MAP = {
    'entry_number':'racer_boat_number', 'number':'racer_number', 'name':'racer_name',
    'rank_number':'racer_class_number', 'age':'racer_age', 'weight':'racer_weight',
    'average_start_timing':'racer_average_start_timing', 'flying_count':'racer_flying_count',
    'late_count':'racer_late_count', 'national_win_rate':'racer_national_top_1_percent',
    'national_top_2_percent':'racer_national_top_2_percent', 'national_top_3_percent':'racer_national_top_3_percent',
    'local_win_rate':'racer_local_top_1_percent', 'local_top_2_percent':'racer_local_top_2_percent',
    'local_top_3_percent':'racer_local_top_3_percent', 'motor_number':'racer_assigned_motor_number',
    'motor_top_2_percent':'racer_assigned_motor_top_2_percent', 'motor_top_3_percent':'racer_assigned_motor_top_3_percent',
    'boat_number':'racer_assigned_boat_number', 'boat_top_2_percent':'racer_assigned_boat_top_2_percent',
    'boat_top_3_percent':'racer_assigned_boat_top_3_percent'}
PREVIEW_MAP = {'entry_number':'racer_boat_number', 'course_number':'racer_course_number',
               'start_timing':'racer_start_timing', 'weight':'racer_weight',
               'weight_adjustment':'racer_weight_adjustment', 'exhibition_time':'racer_exhibition_time',
               'tilt_adjustment':'racer_tilt_adjustment'}


def legacy(payload, day, kind):
    rows = payload.get(kind)
    if not isinstance(rows, list) or not rows:
        raise ValueError('Missing legacy race list')
    out = {}
    for row in rows:
        rid = race_identity(row, day, row['stadium_number'], row['number'], 'number')
        if f"{int(row['stadium_number']):02}" not in VENUES:
            continue
        if rid in out:
            raise ValueError('Duplicate legacy race')
        mapping = PROGRAM_MAP if kind == 'programs' else PREVIEW_MAP
        racers = {}
        for boat in row.get('boats', []):
            lane = str(boat['racer_boat_number'])
            if lane in racers or lane not in set('123456'):
                raise ValueError('Duplicate/invalid legacy lane')
            racers[lane] = {key: boat.get(old) for key, old in mapping.items()}
        out[rid] = {**{k:v for k,v in row.items() if k not in ('boats', 'number')},
                    'race_number':row['number'], 'racers':racers}
    return out


def numeric(v, lo, hi):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        return None
    return v


def supplement(rid, row, provenance, official=None):
    """Join by race + lane + registration; never overwrite the official archive."""
    racers = row.get('racers') or {}
    if set(racers) != set('123456') or len({r.get('number') for r in racers.values()}) != 6:
        raise ValueError('Six unique registered racers required')
    for lane, r in racers.items():
        if r.get('entry_number') != int(lane) or not numeric(r.get('number'), 1000, 9999):
            raise ValueError('Invalid racer identity')
    by_lane = {str(b['lane']):b for b in (official or {}).get('boats', [])}
    conflicts, status_encoding_differences = [], []
    if official:
        if set(by_lane) != set('123456'):
            raise ValueError('Official baseline needs six lanes')
        if any(str(racers[k]['number']) != str(by_lane[k]['racer_id']) for k in racers):
            raise ValueError('Official/API racer mismatch; quarantine whole race')
        # K's result row can omit a withdrawn boat's motor. Its independently
        # matched official B program retains the assigned motor in that case.
        expected_motors = {k:by_lane[k].get('motor_number') or (by_lane[k].get('program') or {}).get('motor_number')
                           for k in racers}
        if any(expected_motors[k] is not None and racers[k].get('motor_number') is not None
               and racers[k]['motor_number'] != expected_motors[k] for k in racers):
            raise ValueError('Official/API motor mismatch; quarantine whole race')
        motor_verified = all(expected_motors[k] is not None and racers[k].get('motor_number') == expected_motors[k]
                             for k in racers)
    else:
        motor_verified = False
    preview, result, odds = row.get('preview') or {}, row.get('result') or {}, row.get('odds') or {}
    boats = []
    for lane, program in sorted(racers.items()):
        observed = (preview.get('racers') or {}).get(lane) or {}
        if observed.get('entry_number') not in (None, int(lane)):
            raise ValueError('Preview lane identity mismatch')
        actual = (result.get('racers') or {}).get(lane) or {}
        if actual.get('number') is not None and str(actual['number']) != str(program['number']):
            raise ValueError('Result racer identity mismatch')
        old = by_lane.get(lane, {})
        for field, value in [('finish',actual.get('place_number')), ('actual_st',actual.get('start_timing')),
                             ('course',actual.get('course_number')), ('exhibition_time',observed.get('exhibition_time'))]:
            expected = old.get(field)
            if expected is not None and value is not None and expected != value:
                item={'lane':int(lane), 'field':field, 'official':expected, 'api':value}
                if field == 'finish' and expected not in range(1,7) and value not in range(1,7):
                    # Preserve both non-finish encodings without claiming a
                    # contradictory normal finish or assuming equivalent causes.
                    status_encoding_differences.append(item)
                else:
                    conflicts.append(item)
        # Zero mean-ST is a rookie/empty placeholder, not an instantaneous start.
        avg = numeric(program.get('average_start_timing'), .001, 1)
        b = {'lane':int(lane), 'racer_id':str(program['number']), 'motor_number':program.get('motor_number'),
             'average_st':avg, 'exhibition_st':numeric(observed.get('start_timing'), -.5, 1),
             'exhibition_course':numeric(observed.get('course_number'), 1, 6),
             'tilt':numeric(observed.get('tilt_adjustment'), -1, 3),
             'parts':observed.get('parts'), 'propeller':observed.get('propeller'),
             'propeller_exchange':bool(observed.get('propeller')) if 'propeller' in observed
                 and numeric(observed.get('exhibition_time'), 5, 10) is not None else None,
             'program':program, 'preview':observed,
             'official_finish':old.get('finish'), 'official_actual_st':old.get('actual_st')}
        boats.append(b)
    normal = bool(official and official.get('normal_eligible') and motor_verified and not conflicts
                  and not status_encoding_differences)
    return {'race_id':rid, 'day':row['date'], 'venue_code':f"{row['stadium_number']:02}",
            'race_no':row['race_number'], 'closed_at':row.get('closed_at'), 'boats':boats,
            'preview_environment':{k:v for k,v in preview.items() if k != 'racers'},
            'preview_wind_direction_text':preview.get('wind_direction_number_source'),
            'refund_lanes':result.get('refunds'), 'historical_odds':odds.get('trifecta'),
            'api_result':result, 'official_result_verified':bool(official),
            'official_motor_identity_verified':motor_verified,
            'official_source_sha256':(official or {}).get('original_sha256'),
            'official_normal_eligible':normal, 'conflicts':conflicts, 'provenance':provenance,
            'status_encoding_differences':status_encoding_differences,
            'upstream_family':'BOATRACE_official_derived', 'independent_evidence_count':1,
            'usage':'retrospective_research_only', 'prospective_verified':False,
            'unresolved':['tide_observation','current_observation','motor_service_period',
                          'preinspection','video_attack_origin','prerace_receipt']}


def load_baseline(ref=BASELINE_REF, path=BASELINE_PATH):
    raw = subprocess.check_output(['git','show',ref+':'+path])
    rows = json.loads(gzip.decompress(raw))
    result = {r['race_id']:r for r in rows}
    if len(result) != len(rows):
        raise ValueError('Duplicate official baseline IDs')
    commit = subprocess.check_output(['git','rev-parse',ref], text=True).strip()
    return result, {'ref':ref, 'commit':commit, 'path':path, 'sha256':digest(raw), 'race_count':len(rows)}


def collect_day(client, day, baseline, retry_failed=False):
    sources = ['turnmark'] if day >= '2026-01-01' else ['legacy_programs','legacy_previews']
    evidence, documents = [], []
    for source in sources:
        meta, payload = client.read(source, day, retry_failed)
        evidence.append(meta)
        documents.append(payload)
    # A richer historical source is preferred. Only fetch the overlapping
    # source if the preferred download is unavailable, rather than duplicating
    # the entire archive.
    if sources == ['turnmark'] and documents[0] is None:
        meta, payload = client.read('openapi', day, retry_failed)
        evidence.append(meta)
        documents = [payload]
    errors, rows = [], {}
    try:
        if any(d is None for d in documents):
            raise ValueError('Required source unavailable; not evidence of no race')
        if len(sources) == 1:
            rows = modern(documents[0], day)
        else:
            rows = legacy(documents[0], day, 'programs')
            previews = legacy(documents[1], day, 'previews')
            for rid, r in rows.items():
                r['preview'] = previews.get(rid)
    except Exception as exc:
        errors.append({'stage':'day', 'error':str(exc)})
    joined = []
    for rid, row in rows.items():
        try:
            joined.append(supplement(rid, row, evidence, baseline.get(rid)))
        except Exception as exc:
            errors.append({'stage':'race', 'race_id':rid, 'error':str(exc)})
    expected = sorted(k for k,v in baseline.items() if v['date'] == day)
    accepted = {r['race_id'] for r in joined}
    record = {'day':day, 'observed_at':stamp(), 'sources':evidence,
              'api_races':len(rows), 'supplemented_races':len(joined),
              'baseline_races':len(expected), 'missing_baseline_ids':sorted(set(expected)-accepted),
              'extra_ids':sorted(accepted-set(expected)), 'errors':errors,
              'status':'review_needed' if errors or set(expected)-accepted else 'parsed', 'races':joined}
    atomic(client.root/'days'/(day+'.json.gz'), gzip.compress(encode(record), mtime=0))
    return record


def report(root, expected_days, baseline_meta):
    root = Path(root)
    counts = {'calendar_days':len(expected_days), 'downloaded_days':0, 'parsed_days':0,
              'supplemented_races':0, 'official_matched_races':0, 'conflict_races':0,
              'missing_baseline_races':0, 'boats':0, 'nonfinish_encoding_races':0}
    fields = {k:{'present':0, 'missing':0} for k in GAP_FIELDS}
    pending, errors, duplicates = [], [], {'official_result_copies_not_added_as_new_races':0}
    for day in expected_days:
        path = root/'days'/(day+'.json.gz')
        if not path.exists():
            pending.append(day)
            continue
        d = json.loads(gzip.decompress(path.read_bytes()))
        counts['downloaded_days'] += 1
        counts['parsed_days'] += d['status'] == 'parsed'
        counts['supplemented_races'] += len(d['races'])
        counts['missing_baseline_races'] += len(d['missing_baseline_ids'])
        errors.extend({'day':day, **e} for e in d['errors'])
        for row in d['races']:
            counts['official_matched_races'] += row['official_result_verified']
            counts['conflict_races'] += bool(row['conflicts'])
            counts['nonfinish_encoding_races'] += bool(row.get('status_encoding_differences'))
            duplicates['official_result_copies_not_added_as_new_races'] += row['official_result_verified']
            for b in row['boats']:
                counts['boats'] += 1
                for k in GAP_FIELDS:
                    value = b.get(k) if k in ('average_st','exhibition_st','exhibition_course','tilt','parts','propeller_exchange') else row.get(k)
                    fields[k]['present' if value is not None else 'missing'] += 1
    output = {'generated_at':stamp(), 'counts':counts, 'field_counts_by_boat':fields,
              'pending_days':pending, 'errors':errors, 'duplicate_handling':duplicates,
              'baseline':baseline_meta, 'all_data_complete':False,
              'source_independence':'Official/API/CSV mirrors share upstream; never count as AI agreement',
              'limitations':['Historical snapshots lack pre-deadline receipt; research only',
                 'API null propeller does not prove missing acquisition; may mean no exchange',
                 'Empty parts/refunds arrays are observed no-exchange/no-refund; null is unknown',
                 'Historical odds collection time is unknown; exclude from pre-deadline EV',
                 'Tide/current/video/motor-period/preinspection still require separate evidence']}
    save_json(root/'summary.json', output)
    if (root/'gaps/summary.json').exists():
        gap=json.loads((root/'gaps/summary.json').read_bytes())
        output['additional_official_gaps']={'path':'gaps/summary.json','counts':gap['counts'],
            'original_field_counts_are_base_api_only':True,'new_races_added':0}
        save_json(root/'summary.json',output)
    labels = {'calendar_days':'対象日数','downloaded_days':'取得・処理済み日数','parsed_days':'照合処理が通った日数',
              'supplemented_races':'追加情報を保存した出走表数','official_matched_races':'既存公式データとの一致レース数',
              'conflict_races':'公式値と相違のあるレース数','missing_baseline_races':'追加情報を結合できない既存レース数',
              'boats':'保存した艇データ数', 'average_st':'出走表の平均ST', 'exhibition_st':'展示ST（Fを負値で保存）',
              'nonfinish_encoding_races':'着順外コードの表記差（原因未同定・学習除外）',
              'exhibition_course':'展示進入','tilt':'チルト','parts':'部品交換情報（交換なしを含む）',
              'propeller_exchange':'ペラ交換の有無','refund_lanes':'返還明細（返還なしを含む）',
              'historical_odds':'過去3連単オッズ（取得時刻不明）', 'preview_wind_direction_text':'展示時の風向文字列',
              'tide_observation':'潮位実測・地点時刻の照合','current_observation':'潮流実測',
              'motor_service_period':'モーター使用期間の公式照合','preinspection':'前検原本',
              'video_attack_origin':'映像上の実攻め起点','prerace_receipt':'当時の締切前受領証'}
    lines = ['# データ追加・重複監査', '', '|項目|値|','|---|---:|']
    lines += [f'|{labels[k]}|{v}|' for k,v in counts.items()]
    lines += ['', '|項目（艇単位）|値あり|未取得・不明|','|---|---:|---:|']
    lines += [f"|{labels[k]}|{v['present']}|{v['missing']}|" for k,v in fields.items()]
    lines += ['', '取得済み結果は公式K/Bと同一IDに結合し、件数を水増ししない。',
              '歴史データの取得日は当時の取得日ではない。締切前の予想原本・前向き成績へ混ぜない。',
              'プロペラnullは交換なしの場合を含む。parts=[]は交換なし、nullは情報不明。',
              f'未取得日数: {len(pending)}。取得エラー・不一致はsummary.jsonで個別確認。']
    if 'additional_official_gaps' in output:
        lines += ['', '## 公式不足データの追加取得', '',
                  '上表は元のAPI補完の件数。潮位・モーター・前検の追加照合はGAPS_REPORT.mdを参照。',
                  'gaps/race_enrichment.json.gzを同一race_idへ結合し、元レースや本番入力を上書きしない。']
    model_path=root/'LIGHTGBM_DIAGNOSTIC.json'
    if model_path.exists():
        model=json.loads(model_path.read_bytes())
        lines += ['', '## LightGBMによる独立した事後研究', '', '|方式|最終期間R数|1着的中率|勝者log-loss|',
                  '|---|---:|---:|---:|']
        for name,values in model['models'].items():
            final=values['final']
            lines.append(f"|{name}|{final['races']}|{final['top1_hit_rate']:.2%}|{final['winner_log_loss']:.4f}|")
        lines += ['', '同じ暦日を分割せず学習60%・検証20%・最終20%に分離。',
                  '過去のAPI入力には当時の受領証がないため、前向き的中率や本番の改善実績ではない。',
                  '既存AIや固定買い目の比較ではなく、学習期の場別枠別頻度を基準にした1着診断。',
                  '回収率・EV・本番採用の判定は行わない。場別結果はLIGHTGBM_DIAGNOSTIC.jsonに保存。']
    atomic(root/'REPORT.md', ('\n'.join(lines)+'\n').encode())
    return output


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', required=True)
    p.add_argument('--start', default='2025-10-18')
    p.add_argument('--end', default='2026-10-17')
    p.add_argument('--workers', type=int, choices=(1,2,4), default=2)
    p.add_argument('--retry-failed', action='store_true')
    p.add_argument('--report-only', action='store_true')
    a = p.parse_args()
    expected = days(a.start,a.end)
    baseline, meta = load_baseline()
    root = Path(a.out).resolve()
    if root == Path.cwd().resolve() or 'data_sources_v1' not in root.parts:
        raise ValueError('Output must be an isolated data_sources_v1 directory')
    client = Client(root)
    if not a.report_only:
        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            for index, record in enumerate(pool.map(lambda d:collect_day(client,d,baseline,a.retry_failed),expected),1):
                print(json.dumps({'day':record['day'],'status':record['status'],
                                  'races':len(record['races']),'progress':f'{index}/{len(expected)}'}), flush=True)
                if index % 50 == 0:
                    report(root,expected,meta)
    result = report(root,expected,meta)
    print(json.dumps({'counts':result['counts'],'pending_days':len(result['pending_days']),
                      'errors':len(result['errors'])}), flush=True)


if __name__ == '__main__':
    main()
