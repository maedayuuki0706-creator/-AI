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
    for row in rows:
        if row.get('day') != day:
            continue
        sent = delivery_time(row)
        if sent is None:
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
    rows = [settle(row, results.get(key, {'status': 'pending', 'payouts': {}, 'refund_lanes': []}))
            for key, row in sorted(chosen.items())]
    expected = card.get('races', {})
    missing = sorted(set(expected) - set(chosen))
    groups = defaultdict(list)
    for row in rows:
        groups[row['jcd']].append(row)
    return {'day': day, 'unit_yen': UNIT_YEN, 'selection_rule': 'latest_pre_deadline_per_race',
            'coverage_verified': card.get('complete', False), 'expected_races': len(expected),
            'missing_predictions': missing, 'excluded_deliveries': len(excluded),
            'excluded_races': sorted({race_key(r) for r in excluded if 'jcd' in r and 'rno' in r}),
            'totals': totals(rows), 'venues': {key: totals(value) for key, value in sorted(groups.items())},
            'races': rows}


def percent(value):
    return '—' if value is None else f'{value:.1f}%'


def report_messages(report):
    day, t = report['day'], report['totals']
    label = '暫定' if t['pending_races'] or not report['coverage_verified'] else '確定'
    prediction_rate = t['prediction_hits'] / t['prediction_samples'] * 100 if t['prediction_samples'] else None
    lines = [f"📊 **競艇AIナビ｜{day[:4]}/{day[4:6]}/{day[6:]} 日次まとめ（{label}）**",
             f"締切前の予想 {t['predicted_races']}R / 開催 {report['expected_races']}R（開催確認{'済' if report['coverage_verified'] else '未完了'}）",
             f"結果確認 {t['resolved_races']}R / 結果待ち {t['pending_races']}R / 予想未記録 {len(report['missing_predictions'])}R",
             f"**仮想投票：{t['bet_races']}R・{t['bet_points']}点・{t['bet_units']}口 / {t['total_stake_yen']:,}円**",
             f"確定分 {t['settled_bet_races']}R：投票 {t['settled_stake_yen']:,}円 → 回収 {t['return_yen']:,}円（返還 {t['refund_yen']:,}円含む）",
             f"**損益 {t['profit_yen']:+,}円 / 回収率 {percent(t['roi'])}**",
             f"仮想投票の的中率：{t['virtual_hits']}/{t['virtual_hit_samples']}R = {percent(t['hit_rate'])}",
             f"予想全点の的中率：{t['prediction_hits']}/{t['prediction_samples']}R = {percent(prediction_rate)}",
             f"見送り {t['pass_races']}R / 配分未記録 {t['unrecorded_plans']}R",
             '1口100円のシミュレーション。各Rは締切前の最新配信だけを採用し、更新分は差替え。',
             '回収率＝確定分の公式払戻・返還÷確定分投票額。結果待ちは率に含めず、全返還・特払いは的中率から除外。']
    if report['excluded_deliveries']:
        lines.append(f"締切後・時刻不明の配信 {report['excluded_deliveries']}件は実績から除外。")
    messages = ['\\n'.join(lines)]
    grouped = defaultdict(list)
    for race in report['races']:
        grouped[race['jcd']].append(race)
    for jcd, stats in sorted(report['venues'].items()):
        venue = base.VENUES.get(jcd, jcd)
        card_lines = [f"📍 **{venue}｜予想・結果まとめ**（{day[4:6]}/{day[6:]}・{label}）",
                      f"予想 {stats['predicted_races']}R / 仮想 {stats['bet_points']}点・{stats['bet_units']}口（{stats['bet_units'] * 100:,}円）",
                      f"確定回収 {stats['return_yen']:,}円 / 損益 {stats['profit_yen']:+,}円 / 的中率 {percent(stats['hit_rate'])} / 回収率 {percent(stats['roi'])}", '']
        for race in sorted(grouped.get(jcd, []), key=lambda x: x['rno']):
            status = {'pending': '結果待ち', 'void': '返還', 'special': '特払い', 'settled': '確定'}.get(race['status'], race['status'])
            hit = '🎯的中' if race['virtual_hit'] else ('✅予想内' if race['prediction_hit'] else '—')
            picks = '・'.join(race['picks'][:3])
            if len(race['picks']) > 3:
                picks += f" 他{len(race['picks']) - 3}点"
            card_lines.append(f"{race['rno']}R｜{status}｜{hit}｜{picks or '買い目なし'}｜投{race['stake_yen']:,}円→回{race['return_yen']:,}円")
        messages.append('\\n'.join(card_lines))
    if report['missing_predictions']:
        missing = defaultdict(list)
        for key in report['missing_predictions']:
            jcd, rno = key.split(':')
            missing[jcd].append(int(rno))
        messages.append('⚠️ **予想未記録（集計対象外）**\\n' + ' / '.join(f"{base.VENUES.get(jcd, jcd)} {','.join(map(str, sorted(races)))}R" for jcd, races in sorted(missing.items())))
    messages[-1] += '\\n公式結果：' + base.official_url('index', day)

    return messages


def send_report(report):
    sent = {r.get('digest') for r in read_jsonl(SENT_PATH)}
    count = 0
    for message in report_messages(report):
        digest = hashlib.sha256(message.encode('utf-8')).hexdigest()
        if digest in sent:
            continue
        base.send_discord(message)
        append_jsonl(SENT_PATH, {'day': report['day'], 'digest': digest, 'sent_at': datetime.now(base.JST).isoformat()})
        sent.add(digest)
        count += 1
        time.sleep(.65)
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
    args = parser.parse_args()
    now = datetime.now(base.JST)
    day = args.day or (now - timedelta(days=1) if now.hour < 6 else now).strftime('%Y%m%d')
    datetime.strptime(day, '%Y%m%d')
    base.fetch.cache_clear()
    predictions = read_jsonl(base.LOG_PATH)
    chosen, _ = latest_predictions(predictions, day)
    card = collect_card(day)
    report = build_report(day, predictions, collect_results(day, chosen), card)
    write_json(REPORT_DIR / f'{day}.json', report)
    (REPORT_DIR / f'{day}.md').write_text('\n\n'.join(report_messages(report)) + '\n', encoding='utf-8')
    sent = send_report(report) if args.send else 0
    print(f"daily report {day}: predictions={len(chosen)} pending={report['totals']['pending_races']} sent_messages={sent}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
