"""Post cutoff-based venue tallies from the same settled journal as Sokuhou-kun."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import json
import os
from pathlib import Path
import re
import urllib.parse
import urllib.request

import direct_discord_notify as base
from discord_notification_policy import SUPPRESS_NOTIFICATIONS
from prediction_recap import post_confirmed, report_destination_key

SCHEDULE = Path('interim_report_schedule.json')
JOURNAL = Path('data/hit_alert_deliveries.jsonl')
PREDICTIONS = Path('data/prediction_log.jsonl')
OPPORTUNITIES = Path('data/opportunity_alert_deliveries.jsonl')
DELIVERIES = Path('data/interim_report_deliveries.jsonl')
SNAPSHOTS = Path('data/interim_reports')
STREAMS = {'normal': '🔵 メイン', 'mid_odds': '🟡 中穴', 'longshot': '🔴 穴'}


def read_rows(path):
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding='utf-8').splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def timestamp(value):
    try:
        value = datetime.fromisoformat(value)
        return value.astimezone(base.JST) if value.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def identity(row, stream):
    try:
        jcd, rno = str(row['jcd']).zfill(2), int(row['rno'])
        if jcd in base.VENUES and 1 <= rno <= 12 and stream in STREAMS:
            return stream, jcd, rno
    except (KeyError, TypeError, ValueError):
        pass
    return None


def tally(as_of, journal, predictions=(), opportunities=()):
    """Never count a later result, an unsent forecast, or a duplicate race twice."""
    if as_of.tzinfo is None:
        raise ValueError('A timezone-aware cutoff is required')
    as_of = as_of.astimezone(base.JST)
    day = as_of.strftime('%Y%m%d')
    settled, eligible, venues = {}, set(), set()
    for row in journal:
        seen_at = timestamp(row.get('sent_at'))
        key = identity(row, row.get('stream') or 'normal')
        if (row.get('day') != day or key is None or seen_at is None
                or seen_at.strftime('%Y%m%d') != day or seen_at > as_of
                or row.get('status') not in {'sent', 'miss'}):
            continue
        previous = settled.get(key)
        if previous is None or seen_at < timestamp(previous['sent_at']):
            settled[key] = row
        venues.add(key[1])

    for rows, default_stream in ((predictions, 'normal'), (opportunities, None)):
        for row in rows:
            key = identity(row, default_stream or row.get('stream'))
            sent_at = timestamp(row.get('sent_at'))
            try:
                close = datetime.strptime(day + ' ' + row['deadline'], '%Y%m%d %H:%M').replace(tzinfo=base.JST)
            except (KeyError, ValueError, TypeError):
                continue
            if (row.get('day') != day or key is None or sent_at is None
                    or sent_at.strftime('%Y%m%d') != day or sent_at > as_of or sent_at >= close):
                continue
            picks = (row.get('main') or row.get('cover') or row.get('outsiders') or row.get('all_picks')) if default_stream else row.get('picks')
            if not picks:
                continue
            venues.add(key[1])
            if close <= as_of:
                eligible.add(key)

    counts = {jcd: {stream: {'hits': 0, 'judged': 0, 'pending': 0, 'man': 0} for stream in STREAMS} for jcd in sorted(venues)}
    for (stream, jcd, _), row in settled.items():
        count = counts[jcd][stream]
        count['judged'] += 1
        if row['status'] == 'sent':
            count['hits'] += 1
            if int(row.get('payout_per_100') or 0) >= 10000:
                count['man'] += 1
    for stream, jcd, rno in eligible - set(settled):
        counts[jcd][stream]['pending'] += 1
    return counts


def result_text(count):
    if count['judged']:
        text = f"{count['hits']}/{count['judged']}R（{count['hits'] / count['judged'] * 100:.1f}%）"
    else:
        text = '—（判定済み0R）'
    if count['pending']:
        text += f"｜未集計{count['pending']}R"
    return text


def build_snapshot(as_of, journal=None, predictions=None, opportunities=None):
    as_of = as_of.astimezone(base.JST)
    counts = tally(as_of, read_rows(JOURNAL) if journal is None else journal,
                   read_rows(PREDICTIONS) if predictions is None else predictions,
                   read_rows(OPPORTUNITIES) if opportunities is None else opportunities)
    totals = {stream: {key: sum(v[stream][key] for v in counts.values()) for key in ('hits', 'judged', 'pending', 'man')} for stream in STREAMS}
    description = ['**速報くん、ここまでの成績を持ってきたぞー！📣**', '', '**全場合計**']
    description += [f'{label}：{result_text(totals[stream])}' for stream, label in STREAMS.items()]
    if not counts:
        description.append('\nこの時刻までの配信・判定記録はまだありません。')
    embed = {
        'title': f'📊 速報くん途中成績｜{as_of:%m/%d %H:%M}時点',
        'description': '\n'.join(description),
        'color': 0xFFB000,
        'fields': [{'name': base.VENUES[jcd], 'value': '\n'.join(f'{label}：{result_text(v[stream])}' for stream, label in STREAMS.items()), 'inline': False} for jcd, v in counts.items()],
        'footer': {'text': 'JST｜速報くんの時刻内の的中・不的中記録を集計。的中数/判定済み数。未配信・結果待ち・未集計は分母外。0件は0%にしません。'},
    }
    return {'day': as_of.strftime('%Y%m%d'), 'hour': as_of.hour, 'as_of': as_of.isoformat(),
            'venues': counts, 'totals': totals,
            'payload': {'embeds': [embed], 'allowed_mentions': {'parse': []}, 'flags': SUPPRESS_NOTIFICATIONS}}


def require_report_channel():
    url = os.getenv('DISCORD_REPORT_WEBHOOK_URL', '').strip()
    if not url:
        raise RuntimeError('Dedicated report channel is not configured')
    if url == os.getenv('DISCORD_WEBHOOK_URL', '').strip():
        raise RuntimeError('Report channel must differ from predictions')
    return url


def verify_channel():
    url = require_report_channel()
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != 'https' or parsed.netloc not in {'discord.com', 'discordapp.com', 'ptb.discord.com', 'canary.discord.com'}
            or not re.fullmatch(r'/api(?:/v\d+)?/webhooks/\d+/[^/]+/?', parsed.path)):
        raise RuntimeError('Report webhook URL is invalid')
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': base.UA}), timeout=20) as response:
        channel = str(json.load(response).get('channel_id', ''))
    if not channel.isdigit():
        raise RuntimeError('Report webhook returned no channel')
    print('Dedicated report webhook verified (read-only)', flush=True)


def send_slot(as_of, *, sender=None):
    require_report_channel()
    destination = report_destination_key()
    key = f"sokuhou:{as_of:%Y%m%d}:{as_of.hour:02d}"
    if any(row.get('request_id') == key and row.get('destination') == destination for row in read_rows(DELIVERIES)):
        return 0
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOTS / f'{as_of:%Y%m%d}_{as_of.hour:02d}.json'
    if path.exists():
        snapshot = json.loads(path.read_text(encoding='utf-8'))
    else:
        snapshot = build_snapshot(as_of)
        path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    message = (sender or post_confirmed)(snapshot['payload'])
    if not str(message.get('id', '')).isdigit():
        raise RuntimeError('Discord acknowledgement has no message ID')
    DELIVERIES.parent.mkdir(parents=True, exist_ok=True)
    with DELIVERIES.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps({'day': snapshot['day'], 'as_of': snapshot['as_of'], 'hour': as_of.hour,
                                 'request_id': key, 'destination': destination, 'message_id': message['id'],
                                 'sent_at': datetime.now(base.JST).isoformat()}, ensure_ascii=False) + '\n')
        handle.flush()
        os.fsync(handle.fileno())
    print(f'Interim report acknowledged: {key}', flush=True)
    return 1


def send_due(now=None, *, sender=None):
    now = (now or datetime.now(base.JST)).astimezone(base.JST)
    schedule = json.loads(SCHEDULE.read_text(encoding='utf-8'))
    if not schedule['enabled'] or now.strftime('%Y%m%d') < schedule['start_day']:
        return 0
    sent = 0
    for hour in schedule['hours']:
        cutoff = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if cutoff <= now:
            sent += send_slot(cutoff, sender=sender)
    return sent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-channel', action='store_true')
    parser.add_argument('--request', type=Path)
    args = parser.parse_args()
    if args.verify_channel:
        verify_channel()
        return
    if args.request:
        request = json.loads(args.request.read_text(encoding='utf-8'))
        now = datetime.now(base.JST)
        schedule = json.loads(SCHEDULE.read_text(encoding='utf-8'))
        if request.get('day') != now.strftime('%Y%m%d'):
            print('Skip stale interim report request')
            return
        hour = request.get('hour')
        if not schedule['enabled'] or request['day'] < schedule['start_day'] or hour not in schedule['hours']:
            raise ValueError('Report slot is not enabled')
        cutoff = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if cutoff > now:
            raise ValueError('Report cutoff has not been reached')
        send_slot(cutoff)
    else:
        send_due()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        raise SystemExit(f'Interim report failed: {type(exc).__name__}') from None
