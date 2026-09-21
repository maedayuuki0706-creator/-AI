"""Experimental Biyori-enriched inputs; the production baseline is never mutated."""
from __future__ import annotations

from copy import deepcopy
from math import isfinite

from prediction_engine import analyze_race
from racer_profiles import COURSE_PRIORS

VERSION = 'hiyori-inputs-v1-unvalidated'


def number(value, lo, hi):
    try:
        out = float(value)
        return out if isfinite(out) and lo <= out <= hi else None
    except (TypeError, ValueError):
        return None


def analyze(official, source, day, jcd, rno):
    boats = deepcopy(official['inputs'])
    indexed = {str(row['player_no']): row for row in source['rows']}
    if len(boats) != 6 or set(indexed) != {str(b['racer_id']) for b in boats}:
        raise ValueError('Hiyori racers do not match the official entry list')
    features = []
    previews = {str(p.get('player_no')): p for p in source.get('preview', [])
                if str(p.get('hiduke')) == day and int(p.get('place_no', 0)) == int(jcd)
                and int(p.get('race_no', 0)) == int(rno)}
    for boat in boats:
        row = indexed[str(boat['racer_id'])]
        lane = int(boat['lane'])
        if int(row.get('course', 0)) != lane:
            raise ValueError('Hiyori lane does not match the official racer')
        course = int(boat.get('predicted_course') or lane)
        count = number(row.get(f'course{course}_shinnyu'), 0, 10000) or 0
        rates = [number(row.get(f'course{course}_{p}_ave'), 0, 1) for p in (1, 2, 3)]
        feature = {'lane': lane, 'course': course, 'course_samples': count,
                   'course_win_rate': rates[0], 'course_top2_rate': rates[1],
                   'course_top3_rate': rates[2], 'used': []}
        if count > 0 and all(rate is not None for rate in rates) and rates[0] <= rates[1] <= rates[2]:
            for name, index, prior_name in [('course_win_rate', 0, 'win'), ('course_top2_rate', 1, 'top2')]:
                prior = number(boat.get(name), 0, 100)
                if prior is None:
                    prior = COURSE_PRIORS[course][prior_name]
                boat[name] = (count * rates[index] * 100 + 12 * prior) / (count + 12)
            feature['used'].append('course_rates')
        course_st = number(row.get(f'start{course}_ave'), 0.01, 0.6)
        feature['course_st'] = course_st
        if count >= 5 and course_st is not None:
            original_st = number(boat.get('avg_st'), 0, 0.6)
            boat['avg_st'] = course_st if original_st is None else .7 * original_st + .3 * course_st
            feature['used'].append('course_st')
        recent = next((m for m in source.get('motor_last10', [])
                       if str(m.get('motor')) == str(boat.get('motor_number'))
                       and int(m.get('place_no', 0)) == int(jcd)), {})
        ranks = []
        for index in range(1, 11):
            suffix = f'{index:02d}'
            date = str(recent.get('hiduke_' + suffix) or '')
            race = int(recent.get('race_no_' + suffix) or 0)
            rank = number(recent.get('rank_' + suffix), 1, 6)
            if rank is not None and (date < day or date == day and race < int(rno)) and len(date) == 8:
                ranks.append(rank)
        feature['motor_last10_ranks'] = ranks
        if len(ranks) >= 3:
            recent_top2 = sum(rank <= 2 for rank in ranks) / len(ranks)
            boat['motor_grade'] = (len(ranks) * recent_top2 + 6 * .5) / (len(ranks) + 6)
            feature['used'].append('motor_last10')
        feature['zenken_time'] = number(row.get('zenken_time'), 5, 10)
        if str(row.get('race_date')) == '1' and feature['zenken_time'] is not None:
            feature['used'].append('first_day_zenken')
        feature['methods'] = {name: row.get(name) for name in
            [f'course{course}_sashi', f'course{course}_makuri', f'course{course}_makurisashi', 'course1_nigeritsu']}
        feature['tilt'] = boat.get('tilt')
        feature['preview'] = previews.get(str(boat['racer_id']), {})
        features.append(feature)
    # Only compare like-for-like measured times; a missing/zero timing is unknown.
    for raw_key, grade_key in [('shukai', 'lap_grade'), ('mawariashi', 'turn_grade'), ('chokusen', 'straight_grade')]:
        timings = {f['lane']: number(f['preview'].get(raw_key), 1, 10000) for f in features}
        valid = [v for v in timings.values() if v is not None]
        if len(valid) == 6 and max(valid) > min(valid):
            for boat, feature in zip(boats, features):
                boat[grade_key] = .3 + .4 * (max(valid) - timings[boat['lane']]) / (max(valid) - min(valid))
                feature['used'].append(raw_key)
    first_day_times = [f['zenken_time'] for f in features if 'first_day_zenken' in f['used']]
    if len(first_day_times) == 6:
        average = sum(first_day_times) / 6
        for boat, feature in zip(boats, features):
            boat['motor_grade'] = min(1, max(0, (boat.get('motor_grade', .5)) + max(-.05, min(.05, (average - feature['zenken_time']) * .2))))
    odds = {row['combination']: row.get('odds') for row in official['trifecta'] if row.get('odds') is not None}
    result = analyze_race({'race': {'venue': official['venue'], 'wind_speed': official['preview'].get('wind_speed')},
                           'boats': boats, 'trifecta_odds': odds})
    heads = {lane: sum(r['probability'] for r in result['trifecta'] if r['combination'].startswith(f'{lane}-')) for lane in range(1, 7)}
    ranking = sorted(heads, key=heads.get, reverse=True)
    top, gap = heads[ranking[0]], heads[ranking[0]] - heads[ranking[1]]
    result.update(model_version=VERSION, inputs=boats, features=features, heads=heads,
                  preview=deepcopy(official['preview']), jcd=str(jcd).zfill(2),
                  grade='A' if top >= .45 and gap >= .2 else 'B' if top >= .30 and gap >= .08 else 'C',
                  source_url=source['source_url'], balanced_head_mode=official.get('balanced_head_mode', False))
    if not any(f['used'] for f in features):
        raise ValueError('No usable Hiyori feature was obtained')
    return result
