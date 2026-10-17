"""Once-per-hour bounded capture of the two upcoming venues' official preinspection.

No motor adjustment or prediction coefficients. Race-day identity and motors
must match before an archived preinspection can be referenced by a race input.
"""
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
import re

from research.capture_v1.parsers import clean
from research.scenario_v2.collector import save_immutable
from research.scenario_v2.engine import aware
from .engine import VENUES, JST
from .log_contract import read

SOURCES = {
    '23': {'url': 'https://www.boatrace-karatsu.jp/modules/raceinfo/?page=index_timerank',
           'calendar_url': 'https://www.boatrace-karatsu.jp/modules/raceinfo/',
           'title_contains': '全日本王者決定戦', 'last_day': '20261023'},
    '06': {'url': 'https://www.boatrace-hamanako.jp/modules/raceinfo/?page=index_timerank',
           'calendar_url': 'https://www.boatrace-hamanako.jp/modules/cal/',
           'title_contains': 'SUZUKI', 'last_day': '20261026'},
}


def parse(raw, code):
    profile = SOURCES[code]
    start = datetime.strptime(VENUES[code]['first_day'], '%Y%m%d')
    # These venue pages omit a year. Bound capture to the actual preinspection
    # window and match both the displayed month/day and independently checked title.
    header = raw[raw.find('com-racetitle_group'):raw.find('com-racetitle_group') + 6000]
    month = re.search(r'schedule-area__month[^>]*>\s*(\d+)/', header)
    day = re.search(r'item-day[^>]*>\s*(\d+)', header)
    if not month or not day or (int(month[1]), int(day[1])) != (start.month, start.day):
        raise ValueError('Preinspection series date unverified; no prior-meeting substitution')
    if profile['title_contains'] not in clean(header):
        raise ValueError('Preinspection series title mismatch')
    rows = []
    for raw_row in re.findall(r'<tr\b[^>]*>(.*?)</tr>', raw, re.S | re.I):
        cells = [clean(x) for x in re.findall(r'<td\b[^>]*>(.*?)</td>', raw_row, re.S | re.I)]
        if len(cells) != 10 or not re.fullmatch(r'\d{4}', cells[1]):
            continue
        number = re.search(r'toban=(\d{4})', raw_row)
        if not number or number[1] != cells[1]:
            raise ValueError('Preinspection racer link/row identity mismatch')
        time = float(cells[9])
        if not 5 < time < 10:
            raise ValueError('Invalid observed preinspection time')
        rows.append({'racer_id': cells[1], 'name': cells[2].replace(' ', ''), 'class': cells[3],
                     'motor_number': int(cells[4]), 'motor_top2_rate': float(cells[5].removesuffix('%')),
                     'motor_venue_grade': cells[6], 'boat_number': int(cells[7]),
                     'boat_top2_rate': float(cells[8].removesuffix('%')), 'preinspection_time': time})
    if len(rows) < 6 or len({x['racer_id'] for x in rows}) != len(rows):
        raise ValueError('Preinspection table unavailable or incomplete')
    return rows


def capture(root, *, official, now):
    root = Path(root)
    output = []
    for code, source in SOURCES.items():
        day = VENUES[code]['first_day']
        first = datetime.strptime(day, '%Y%m%d').replace(tzinfo=JST)
        if not first.date() - timedelta(days=1) <= now.date() <= first.date():
            continue
        path = root / 'phase1/preinspection' / day / (code + '.json')
        if path.is_file():
            continue
        attempt = root / 'phase1/preinspection_attempts' / day / (code + '_' + now.strftime('%Y%m%d%H') + '.json')
        if attempt.exists():
            continue
        try:
            raw = official.fetch(source['url'])
            rows = parse(raw, code)
            envelope = official.envelope(source['url'])
            record = {'jcd': code, 'first_day': day, 'last_day': source['last_day'],
                      'observed_at': envelope['observed_at'], 'source_url': source['url'],
                      'calendar_url': source['calendar_url'], 'displayed_start_month_day_verified': True,
                      'year_not_printed_on_source_page': True, 'capture_date_bounds_verified': True,
                      'status': 'verified_current_series_observation', 'rows': rows,
                      'raw_html': raw, 'sha256': sha256(raw.encode()).hexdigest(),
                      'used_for_prediction_adjustment': False}
            save_immutable(path, record)
            output.append({'jcd': code, 'status': record['status'], 'racers': len(rows)})
        except Exception as exc:
            event = {'jcd': code, 'first_day': day, 'observed_at': now.isoformat(),
                     'status': 'unavailable_or_unverified', 'type': type(exc).__name__, 'reason': str(exc)[:200]}
            save_immutable(attempt, event)
            output.append(event)
    return output


def reference(root, code, day, boats, captured_at):
    profile = SOURCES.get(code)
    if not profile or not VENUES[code]['first_day'] <= day <= profile['last_day']:
        return {'status': 'not_available_for_series'}
    path = Path(root) / 'phase1/preinspection' / VENUES[code]['first_day'] / (code + '.json')
    data = read(path)
    if not data or aware(data['observed_at']) > aware(captured_at):
        return {'status': 'no_verified_preinspection_before_capture'}
    indexed = {row['racer_id']: row for row in data['rows']}
    matched = []
    for boat in boats:
        observation = indexed.get(str(boat['racer_id']))
        if not observation or observation['motor_number'] != boat.get('motor_number'):
            return {'status': 'entrant_or_motor_mismatch_no_substitution'}
        matched.append(observation)
    return {'status': 'six_racer_motor_identities_match', 'first_day': data['first_day'],
            'source_url': data['source_url'], 'source_sha256': data['sha256'],
            'observed_at': data['observed_at'], 'rows': matched, 'descriptive_only': True}
