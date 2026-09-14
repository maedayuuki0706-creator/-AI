"""Settle disclosed pre-deadline virtual plans with official yen payouts.

One race uses its latest pre-close delivery; updates replace, never add stakes.
No stake is inferred for old messages without an explicit virtual allocation.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import time

import direct_discord_notify as base
from race_context import clean
from discord_formation import unique_picks
from race_notices import read_notices

REPORT_DIR = Path('data/daily_reports')
RESULT_DIR = Path('data/official_results')
CARD_DIR = Path('data/race_cards')
SENT_PATH = Path('data/report_deliveries.jsonl')
UNIT_YEN = 100


def read_jsonl(path):
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding='utf-8').splitlines():
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
        except ValueError:
            continue
    return rows


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    temporary.replace(path)


def append_jsonl(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(data, ensure_ascii=False, sort_keys=True) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def race_key(row):
    return f"{str(row['jcd']).zfill(2)}:{int(row['rno'])}"


def delivery_time(row):
    try:
        sent = datetime.fromisoformat(row['sent_at'])
        if sent.tzinfo is None:
            return None
        sent = sent.astimezone(base.JST)
        close = datetime.strptime(row['day'] + ' ' + row['deadline'], '%Y%m%d %H:%M').replace(tzinfo=base.JST)
        return sent if sent.strftime('%Y%m%d') == row['day'] and sent < close else None
    except (KeyError, TypeError, ValueError):
        return None


def latest_predictions(rows, day):
    selected, excluded = {}, []
    withdrawals = {race_key(r) for r in read_notices() if r.get('day') == day
                   and r.get('status') == 'withdrawn' and delivery_time(r) is not None}
    for row in rows:
        if row.get('day') != day:
            continue
        sent = delivery_time(row)
        if sent is None or race_key(row) in withdrawals:
            excluded.append(row)
            continue
        key = race_key(row)
        old = selected.get(key)
        if old is None or (sent, row.get('phase') == 'final') > (delivery_time(old), old.get('phase') == 'final'):
            selected[key] = row
    return selected, excluded


def parse_payout(raw):
    """Read the trifecta market only; unknown/suspended results stay pending."""
    text = clean(raw)
    market = next((body for body in re.findall(r'<tbody\b[^>]*>(.*?)</tbody>', raw, re.S | re.I)
                   if re.search(r'<td\b[^>]*>\s*3連単\s*</td>', body, re.S)), '')
    market_text = clean(market)
    payouts = {}
    for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>', market, re.S | re.I):
        match = re.search(r'([1-6])\s*[-－]\s*([1-6])\s*[-－]\s*([1-6])\s+[¥￥]\s*([\d,]+)', clean(row))
        if match:
            combo = '-'.join(match.group(i) for i in (1, 2, 3))
            if len(set(combo.split('-'))) == 3:
                payouts[combo] = int(match[4].replace(',', ''))
    refund_lanes = set()
    for table in re.findall(r'<table\b[^>]*>(.*?)</table>', raw, re.S | re.I):
        if re.search(r'<th\b[^>]*>\s*返還\s*</th>', table):
            refund_lanes.update(int(x) for x in re.findall(r'numberSet1_number[^>]*>\s*([1-6])\s*</span>', table))
    # Some stored fixtures omit the refund panel, but keep the official F/L rows.
    for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>', raw, re.S | re.I):
        cells = re.findall(r'<td\b[^>]*>(.*?)</td>', row, re.S | re.I)
        if len(cells) == 4 and re.search(r'is-boatColor[1-6]', row):
            status, lane = clean(cells[0]), clean(cells[1])
            if status in {'F', 'L', '欠', 'K0', 'K1'} and re.fullmatch('[1-6]', lane):
                refund_lanes.add(int(lane))
    void = bool(re.search(r'不成立|全返還|中止', market_text)
                or re.search(r'(?:この)?レースは中止(?:となりました|です)', text)
                or re.search(r'<(?:p|div|td)\b[^>]*>\s*(?:レース中止|不成立)\s*</', raw))
    special = re.search(r'特払い\s*[¥￥]\s*([\d,]+)', market_text)
    status = 'void' if void else 'special' if special else 'settled' if payouts else 'pending'
    if '返還艇あり' in text and not refund_lanes and status == 'settled':
        status = 'pending'  # A refund must not silently become a losing ticket.
    return {'status': status, 'payouts': payouts, 'refund_lanes': sorted(refund_lanes),
            'special_per_100': int(special[1].replace(',', '')) if special else None}


def disclosed_picks(row):
    return unique_picks((row.get('main') or []) + (row.get('cover') or []) + (row.get('outsiders') or []))


def virtual_plan(row):
    if 'virtual_bets' not in row or 'virtual_total_units' not in row:
        return None
    stakes = defaultdict(int)
    allowed = set(disclosed_picks(row))
    for bet in row['virtual_bets']:
        combo, units = bet.get('combination'), bet.get('units')
        if combo not in allowed or type(units) is not int or units <= 0:
            return None
        stakes[combo] += units
    if sum(stakes.values()) != row['virtual_total_units'] or row.get('virtual_unit_yen', UNIT_YEN) != UNIT_YEN:
        return None
    return dict(stakes)


def settle(row, result):
    plan = virtual_plan(row)
    out = {'jcd': str(row['jcd']).zfill(2), 'rno': int(row['rno']), 'venue': row.get('venue'),
           'phase': row.get('phase'), 'sent_at': row.get('sent_at'), 'status': result['status'],
           'picks': disclosed_picks(row), 'plan_recorded': plan is not None,
           'bet_points': len(plan or {}), 'units': sum((plan or {}).values()),
           'stake_yen': sum((plan or {}).values()) * UNIT_YEN,
           'return_yen': 0, 'refund_yen': 0, 'virtual_hit': False, 'hit_eligible': False,
           'prediction_hit': bool(set(disclosed_picks(row)) & set(result.get('payouts', {}))),
           'official': result}
    out.update(main=row.get('main') or [], cover=row.get('cover') or [], outsiders=row.get('outsiders') or [],
               grade=row.get('grade'), deadline=row.get('deadline'))
    if plan is None or result['status'] == 'pending':
        return out
    for combo, units in plan.items():
        refund = result['status'] == 'void' or bool(set(map(int, combo.split('-'))) & set(result['refund_lanes']))
        if refund:
            out['refund_yen'] += units * UNIT_YEN
            out['return_yen'] += units * UNIT_YEN
        elif result['status'] == 'special':
            out['return_yen'] += units * result['special_per_100']
        else:
            out['hit_eligible'] = True
            payout = result['payouts'].get(combo, 0)
            out['return_yen'] += units * payout
            out['virtual_hit'] |= payout > 0
    return out


def totals(rows):
    resolved = [r for r in rows if r['status'] != 'pending']
    prediction = [r for r in resolved if r['status'] == 'settled']
    betting = [r for r in rows if r['stake_yen'] > 0]
    settled_bets = [r for r in resolved if r['stake_yen'] > 0]
    denominator = sum(r['hit_eligible'] for r in settled_bets)
    hits = sum(r['virtual_hit'] for r in settled_bets)
    stake = sum(r['stake_yen'] for r in settled_bets)
    returned = sum(r['return_yen'] for r in settled_bets)
    return {'predicted_races': len(rows), 'resolved_races': len(resolved),
            'pending_races': len(rows) - len(resolved), 'prediction_samples': len(prediction),
            'prediction_hits': sum(r['prediction_hit'] for r in prediction),
            'bet_races': len(betting), 'bet_points': sum(r['bet_points'] for r in betting),
            'bet_units': sum(r['units'] for r in betting), 'total_stake_yen': sum(r['stake_yen'] for r in betting),
            'settled_bet_races': len(settled_bets), 'settled_stake_yen': stake, 'return_yen': returned,
            'refund_yen': sum(r['refund_yen'] for r in settled_bets), 'profit_yen': returned - stake,
            'virtual_hits': hits, 'virtual_hit_samples': denominator,
            'hit_rate': hits / denominator * 100 if denominator else None,
            'roi': returned / stake * 100 if stake else None,
            'unrecorded_plans': sum(not r['plan_recorded'] for r in rows),
            'pass_races': sum(r['plan_recorded'] and not r['stake_yen'] for r in rows)}


def build_report(day, predictions, results, card):
    chosen, excluded = latest_predictions(predictions, day)
    rows, uniform_rows = [], []
    section_rows = defaultdict(list)
    for key, row in sorted(chosen.items()):
        result = results.get(key, {'status': 'pending', 'payouts': {}, 'refund_lanes': []})
        actual = settle(row, result)
        def flat(picks):
            return settle({**row, 'main': picks, 'cover': [], 'outsiders': [],
                           'virtual_bets': [{'combination': pick, 'units': 1} for pick in picks],
                           'virtual_total_units': len(picks)}, result)
        uniform = flat(disclosed_picks(row))
        uniform_rows.append(uniform)
        actual['uniform'] = {k: uniform[k] for k in ('stake_yen', 'return_yen', 'refund_yen', 'hit_eligible', 'virtual_hit')}
        actual['hit_sections'] = []
        seen = set()
        for section in ('main', 'cover', 'outsiders'):
            picks = [p for p in unique_picks(row.get(section) or []) if p not in seen]
            seen.update(picks)
            if picks:
                section_rows[section].append(flat(picks))
            if set(picks) & set(result.get('payouts', {})):
                actual['hit_sections'].append(section)
        rows.append(actual)
    expected = card.get('races', {})
    missing = sorted(set(expected) - set(chosen))
    groups = defaultdict(list)
    for row in rows:
        groups[row['jcd']].append(row)
    venue_stats = {key: totals(value) for key, value in sorted(groups.items())}
    for key in venue_stats:
        venue_stats[key]['uniform'] = totals([r for r in uniform_rows if r['jcd'] == key])
    comparisons = {}
    for dimension in ('phase', 'grade', 'points'):
        segments = defaultdict(list)
        for actual, uniform in zip(rows, uniform_rows):
            value = str(len(actual['picks'])) if dimension == 'points' else str(actual.get(dimension) or '未記録')
            segments[value].append(uniform)
        comparisons[dimension] = {key: totals(value) for key, value in segments.items()}
    return {'day': day, 'unit_yen': UNIT_YEN, 'selection_rule': 'latest_pre_deadline_per_race',
            'coverage_verified': card.get('complete', False), 'expected_races': len(expected),
            'missing_predictions': missing, 'excluded_deliveries': len(excluded),
            'excluded_races': sorted({race_key(r) for r in excluded if 'jcd' in r and 'rno' in r}),
            'totals': totals(rows), 'uniform_totals': totals(uniform_rows), 'venues': venue_stats,
            'section_totals': {key: totals(value) for key, value in section_rows.items()}, 'comparisons': comparisons,
            'races': rows}


def percent(value):
    return '—' if value is None else f'{value:.1f}%'


def report_messages(report):
    from daily_report_format import report_payloads, payload_text
    return [payload_text(payload) for payload in report_payloads(report)]


def send_report(report):
    from daily_report_format import report_payloads
    from prediction_recap import post_confirmed, report_destination_key
    destination = report_destination_key()
    sent = {(r.get('digest'), r.get('destination', 'predictions')) for r in read_jsonl(SENT_PATH)}
    count = 0
    for payload in report_payloads(report):
        digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
        key = (digest, destination)
        if key in sent:
            continue
        message = post_confirmed(payload)
        venue = payload['embeds'][0]['title'].split('｜')[0]
        append_jsonl(SENT_PATH, {'day': report['day'], 'digest': digest,
                     'message_id': message['id'], 'venue': venue, 'format': 'venue-daily-v2', 'destination': destination,
                     'sent_at': datetime.now(base.JST).isoformat()})
        sent.add(key)
        count += 1
        print(f"Daily report confirmed {report['day']} {venue}", flush=True)
        time.sleep(1)
    return count


def collect_card(day):
    path = CARD_DIR / f'{day}.json'
    card = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'day': day, 'races': {}}
    try:
        venues = base.discover_venues(day)
    except Exception:
        return {**card, 'complete': False}
    complete = bool(venues)
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = {pool.submit(base.deadlines, day, jcd): jcd for jcd in venues}
        for future in as_completed(jobs):
            jcd = jobs[future]
            try:
                deadlines = future.result()
            except Exception:
                deadlines = []
            complete &= len(deadlines) == 12
            for rno in range(1, 13):
                key = f'{jcd}:{rno}'
                card['races'][key] = {'jcd': jcd, 'rno': rno, 'deadline': deadlines[rno - 1] if len(deadlines) >= rno else card['races'].get(key, {}).get('deadline')}
    card.update(complete=complete, checked_at=datetime.now(base.JST).isoformat())
    write_json(path, card)
    return card


def collect_results(day, chosen):
    path = RESULT_DIR / f'{day}.json'
    results = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    def get(row):
        url = base.official_url('raceresult', day, str(row['jcd']).zfill(2), int(row['rno']))
        result = parse_payout(base.fetch(url))
        return {**result, 'source_url': url, 'checked_at': datetime.now(base.JST).isoformat()}
    with ThreadPoolExecutor(max_workers=4) as pool:
        # Refresh official results on each report run, including corrections.
        now = datetime.now(base.JST)
        jobs = {pool.submit(get, row): key for key, row in chosen.items()
                if datetime.strptime(day + ' ' + row['deadline'], '%Y%m%d %H:%M').replace(tzinfo=base.JST) <= now}
        for future in as_completed(jobs):
            key = jobs[future]
            try:
                result = future.result()
            except Exception as exc:
                print(f'Official result pending {key}: {type(exc).__name__}')
                continue
            if result['status'] != 'pending' or key not in results:
                results[key] = result
    write_json(path, results)
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--day')
    parser.add_argument('--send', action='store_true')
    parser.add_argument('--saved-results', action='store_true', help='Reformat already collected official results without another fetch')
    args = parser.parse_args()
    now = datetime.now(base.JST)
    day = args.day or (now - timedelta(days=1) if now.hour < 6 else now).strftime('%Y%m%d')
    datetime.strptime(day, '%Y%m%d')
    base.fetch.cache_clear()
    predictions = read_jsonl(base.LOG_PATH)
    chosen, _ = latest_predictions(predictions, day)
    if args.saved_results:
        card = json.loads((CARD_DIR / f'{day}.json').read_text(encoding='utf-8'))
        results = json.loads((RESULT_DIR / f'{day}.json').read_text(encoding='utf-8'))
    else:
        card = collect_card(day)
        results = collect_results(day, chosen)
    report = build_report(day, predictions, results, card)
    write_json(REPORT_DIR / f'{day}.json', report)
    (REPORT_DIR / f'{day}.md').write_text('\n\n'.join(report_messages(report)) + '\n', encoding='utf-8')
    sent = send_report(report) if args.send else 0
    print(f"daily report {day}: predictions={len(chosen)} pending={report['totals']['pending_races']} sent_messages={sent}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
