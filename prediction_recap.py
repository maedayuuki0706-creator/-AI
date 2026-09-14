"""Reconstruct disclosed predictions and post one acknowledged recap per venue."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request

import direct_discord_notify as base
from daily_report import delivery_time, latest_predictions
from discord_formation import compress_picks, unique_picks
from race_notices import read_notices, record_notice

DELIVERY_PATH = Path('data/prediction_recap_deliveries.jsonl')
OUTPUT_DIR = Path('data/prediction_recaps')
LABELS = {'main': '本線', 'cover': '抑え', 'outsiders': '穴'}


def read_rows(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def utf16_len(text):
    return len(text.encode('utf-16-le')) // 2


def race_field(rno, row, notice=None):
    if row is None:
        status = (notice or {}).get('status')
        label = {'withdrawn': '欠場', 'waiting': '予想の配信記録なし（データ待ち通知あり）',
                 'unavailable': '予想の配信記録なし（データ未確認）',
                 'pass': '見送り推奨'}.get(status, '締切前の予想配信記録なし')
        return {'name': f'{rno}レース', 'value': label + '\n━━━━━━━━━━━━', 'inline': False}
    sections, seen = [], set()
    for key, label in LABELS.items():
        picks = [p for p in unique_picks(row.get(key) or []) if p not in seen]
        seen.update(picks)
        if picks:
            forms = ' ／ '.join(item['text'] for item in compress_picks(picks))
            sections.append(f'**{label}（{len(picks)}点）**\n{forms}')
    extra = [p for p in unique_picks(row.get('all_picks') or []) if p not in seen]
    if extra:
        seen.update(extra)
        sections.append('**その他の配信買い目**\n' + ' ／ '.join(extra))
    if not seen:
        raise ValueError('Logged prediction has no disclosed combinations')
    sent = datetime.fromisoformat(row['sent_at']).astimezone(base.JST)
    phase = '直前更新' if row.get('phase') == 'final' else '暫定予想'
    sections.append(f'{phase}・{sent:%H:%M}送信記録')
    if row.get('virtual_status') == 'pass':
        sections.append('見送り推奨（仮想0口）')
    sections.append('━━━━━━━━━━━━')
    return {'name': f'{rno}レース｜合計{len(seen)}点', 'value': '\n'.join(sections), 'inline': False}


def build_recaps(day, rows, card, notices):
    datetime.strptime(day, '%Y%m%d')
    latest, excluded = latest_predictions(rows, day)
    statuses = {}
    for row in notices:
        if row.get('day') == day and delivery_time(row) is not None:
            key = f"{str(row['jcd']).zfill(2)}:{int(row['rno'])}"
            if key not in statuses or row['sent_at'] > statuses[key]['sent_at']:
                statuses[key] = row
    venues = {key.split(':')[0] for key in latest} | {key.split(':')[0] for key in card.get('races', {})}
    recaps = []
    for jcd in sorted(venues):
        venue = base.VENUES[jcd]
        fields = [race_field(rno, latest.get(f'{jcd}:{rno}'), statuses.get(f'{jcd}:{rno}')) for rno in range(1, 13)]
        count = sum(f'{jcd}:{rno}' in latest for rno in range(1, 13))
        embed = {'title': f'{venue}｜{day[:4]}/{day[4:6]}/{day[6:8]} 配信予想まとめ',
                 'description': f'予想記録 {count}/12レース。締切前の最新配信を掲載。\n本線・抑え・穴は当時の区分。フォーメーションは重複を除いた点数です。',
                 'color': 0x176B87, 'fields': fields,
                 'footer': {'text': '送信ログから再構成した振り返り用の一覧です。'}}
        total = sum(utf16_len(embed[k]) for k in ('title', 'description')) + utf16_len(embed['footer']['text'])
        total += sum(utf16_len(f['name']) + utf16_len(f['value']) for f in fields)
        if total > 6000 or any(utf16_len(f['value']) > 1024 for f in fields):
            raise ValueError('Venue recap exceeds Discord embed limit')
        payload = {'embeds': [embed], 'allowed_mentions': {'parse': []}}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        recaps.append({'day': day, 'jcd': jcd, 'venue': venue, 'predicted_races': count,
                       'payload': payload, 'digest': digest, 'characters': total})
    return recaps, excluded


def save_recaps(day, recaps):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / f'{day}.json').write_text(json.dumps(recaps, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    lines = [f'# {day[:4]}/{day[4:6]}/{day[6:8]} 配信予想まとめ', '',
             '各レースの締切前に送った最新の予想を掲載。配信記録がないレースは補作していません。', '']
    for recap in recaps:
        embed = recap['payload']['embeds'][0]
        lines += ['## ' + embed['title'], '', embed['description'], '']
        for field in embed['fields']:
            lines += ['### ' + field['name'], '', field['value'], '']
    (OUTPUT_DIR / f'{day}.md').write_text('\n'.join(lines), encoding='utf-8')


def report_webhook_url():
    return (os.getenv('DISCORD_REPORT_WEBHOOK_URL', '').strip()
            or os.getenv('DISCORD_WEBHOOK_URL', '').strip())


def report_destination_key():
    """Keep old delivery journals valid and distinguish a new report target.

    The journal contains only a digest of the public webhook ID and thread,
    never the URL or its token. Rotating a token does not cause repeat posts.
    """
    url = report_webhook_url()
    previous = os.getenv('DISCORD_WEBHOOK_URL', '').strip()
    if not os.getenv('DISCORD_REPORT_WEBHOOK_URL', '').strip() or url == previous:
        return 'predictions'
    parsed = urllib.parse.urlsplit(url)
    match = re.search(r'/webhooks/([^/]+)/', parsed.path)
    identity = [parsed.hostname, match[1] if match else parsed.path,
                dict(urllib.parse.parse_qsl(parsed.query)).get('thread_id')]
    return 'reports:' + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20]


def post_confirmed(payload):
    url = report_webhook_url()
    if not url:
        raise RuntimeError('Discord connection is not configured')
    parts = urllib.parse.urlsplit(url)
    query = dict(urllib.parse.parse_qsl(parts.query))
    query['wait'] = 'true'
    target = urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))
    request = urllib.request.Request(target, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                                    headers={'Content-Type': 'application/json', 'User-Agent': base.UA}, method='POST')
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                message = json.loads(response.read())
            if not str(message.get('id', '')).isdigit():
                raise RuntimeError('Discord acknowledgement has no message ID')
            return message
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 2:
                try:
                    delay = float(json.loads(exc.read()).get('retry_after', 1))
                except (ValueError, TypeError):
                    delay = 1
                if 0 <= delay <= 30:
                    time.sleep(delay + .25)
                    continue
            raise RuntimeError(f'Discord HTTP {exc.code}') from None
    raise RuntimeError('Discord rate limit did not recover')


def send_recaps(recaps, *, sender=post_confirmed, pause=time.sleep):
    destination = report_destination_key()
    delivered = {(r.get('day'), r.get('jcd'), r.get('digest'), r.get('destination', 'predictions'))
                 for r in read_rows(DELIVERY_PATH)}
    sent = 0
    for recap in recaps:
        key = (recap['day'], recap['jcd'], recap['digest'], destination)
        if key in delivered:
            continue
        message = sender(recap['payload'])
        record_notice({'day': recap['day'], 'jcd': recap['jcd'], 'venue': recap['venue'],
                       'digest': recap['digest'], 'message_id': message['id'], 'destination': destination,
                       'predicted_races': recap['predicted_races'], 'message_count': 1,
                       'confirmed_at': datetime.now(base.JST).isoformat()}, path=DELIVERY_PATH)
        delivered.add(key)
        sent += 1
        print(f"Recap confirmed {recap['jcd']} {recap['venue']} races={recap['predicted_races']}/12", flush=True)
        pause(1)
    print(f'Recap complete venues={len(recaps)} new_messages={sent}', flush=True)
    return 0


def main(day):
    card_path = Path('data/race_cards') / f'{day}.json'
    card = json.loads(card_path.read_text(encoding='utf-8')) if card_path.exists() else {}
    recaps, _ = build_recaps(day, read_rows(base.LOG_PATH), card, read_notices())
    if not recaps:
        raise RuntimeError('No logged predictions or race card for this date')
    save_recaps(day, recaps)
    return send_recaps(recaps)
