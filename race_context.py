"""Verified meeting results used only as a small, date-scoped form feature."""
from __future__ import annotations
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
import json
import re
import html
import unicodedata

CONTEXT_DIR = Path('data/race_context')


def clean(raw):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', html.unescape(re.sub(r'<[^>]+>', ' ', raw)))).strip()


def parse_result(raw, day, jcd, rno):
    finish = []
    for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>', raw, re.S | re.I):
        cells = re.findall(r'<td\b[^>]*>(.*?)</td>', row, re.S | re.I)
        if len(cells) != 4 or not re.search(r'is-boatColor[1-6]', row):
            continue
        position, lane, racer = clean(cells[0]), clean(cells[1]), clean(cells[2])
        m = re.match(r'(\d{4})\s+(.+)', racer)
        if not m or lane not in '123456' or len(lane) != 1:
            continue
        finish.append({'lane': int(lane), 'racer_id': m[1], 'name': m[2].replace(' ', ''),
                       'finish': int(position) if position in list('123456') else None,
                       'status': 'finished' if position in list('123456') else position})
    starts = re.findall(r'table1_boatImage1Number[^>]*>\s*([1-6])\s*</span>.*?table1_boatImage1Time[^>]*>(.*?)</span>', raw, re.S)
    for course, (lane, st_raw) in enumerate(starts, 1):
        for item in finish:
            if item['lane'] == int(lane):
                st = clean(st_raw).split(' ')[0]
                item.update(course=course, st=float(st) if re.fullmatch(r'\.?\d+', st) else None)
    text = clean(raw)
    method = re.search(r'決まり手\s+(逃げ|差し|まくり差し|まくり|抜き|恵まれ)', text)
    payout = re.search(r'3連単\s+([1-6])\s*-\s*([1-6])\s*-\s*([1-6])\s+[¥￥]([\d,]+)', text)
    wind = re.search(r'風速\s+(\d+)m', text)
    wave = re.search(r'波高\s+(\d+)cm', text)
    if len(finish) != 6 or not payout or len({x['racer_id'] for x in finish}) != 6:
        raise ValueError(f'Incomplete result {day} {jcd} {rno}')
    return {'day': day, 'jcd': jcd, 'rno': rno, 'finish': finish,
            'trifecta': '-'.join(payout.group(i) for i in (1,2,3)), 'payout_per_100': int(payout[4].replace(',', '')),
            'method': method[1] if method else None, 'wind_m': int(wind[1]) if wind else None,
            'wave_cm': int(wave[1]) if wave else None,
            'source_url': f'https://www.boatrace.jp/owpc/pc/race/raceresult?hd={day}&jcd={jcd}&rno={rno}'}


def previous_form(day, jcd, boats):
    previous = (datetime.strptime(day, '%Y%m%d') - timedelta(days=1)).strftime('%Y%m%d')
    path = CONTEXT_DIR / f'{previous}_{jcd}.json'
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('day') != previous or data.get('jcd') != jcd:
        return {}
    grouped = defaultdict(list)
    for race in data.get('races', []):
        if race.get('day') == previous and race.get('jcd') == jcd:
            for row in race.get('finish', []):
                grouped[str(row.get('racer_id'))].append(row)
    result = {}
    for boat in boats:
        observations = grouped.get(str(boat.get('racer_id')), [])
        normal = [x for x in observations if x.get('status') == 'finished' and isinstance(x.get('finish'), int) and 1 <= x['finish'] <= 6]
        # Six neutral pseudo-observations keep one day's outcomes a weak signal.
        quality = (3 + sum((6 - x['finish']) / 5 for x in normal)) / (6 + len(normal))
        if observations:
            result[boat['lane']] = {'score_delta': round(.02 * (quality - .5), 6),
                'finishes': [x['finish'] if x.get('status') == 'finished' else x.get('status') for x in observations],
                'samples': len(normal), 'source_day': previous}
    return result
