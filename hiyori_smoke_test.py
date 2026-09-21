"""Confirm a real post to the dedicated Hiyori channel, without sending tips."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

JST = ZoneInfo('Asia/Tokyo')
RECEIPTS = Path('data/hiyori_smoke_tests')


def webhook():
    url = os.getenv('HIYORI_DISCORD_WEBHOOK_URL', '').strip()
    if not url:
        raise RuntimeError('HIYORI_DISCORD_WEBHOOK_URL is not configured')
    parts = urllib.parse.urlsplit(url)
    if (parts.scheme != 'https' or parts.netloc not in {'discord.com', 'discordapp.com'}
            or not re.fullmatch(r'/api(?:/v\d+)?/webhooks/\d+/[^/]+/?', parts.path)):
        raise RuntimeError('HIYORI_DISCORD_WEBHOOK_URL has an invalid format')
    return parts


def request_json(url, payload=None, *, opener=None):
    request = urllib.request.Request(
        url, data=None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers={'User-Agent': 'Boat-AI-Hiyori/1.0', 'Content-Type': 'application/json'},
        method='GET' if payload is None else 'POST')
    try:
        with (opener or urllib.request.urlopen)(request, timeout=20) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'Discord HTTP {exc.code}') from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError('Discord request failed; delivery not confirmed') from None


def send(request_id, *, opener=None, now=None):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', request_id or ''):
        raise ValueError('A unique test request ID is required')
    parts = webhook()
    query = dict(urllib.parse.parse_qsl(parts.query))
    if query.get('thread_id'):
        raise RuntimeError('Use a dedicated Hiyori text-channel webhook for this test')
    # Hash only the public webhook ID, never persist its token.
    public_id = parts.path.rstrip('/').split('/')[-2]
    destination = hashlib.sha256(public_id.encode()).hexdigest()[:20]
    receipt_path = RECEIPTS / f'{request_id}.json'
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        if receipt.get('destination') != destination:
            raise RuntimeError('The destination changed; use a new test request ID')
        if not str(receipt.get('message_id', '')).isdigit():
            raise RuntimeError('Stored acknowledgement is invalid')
        print('Hiyori test already confirmed: ' + json.dumps(receipt), flush=True)
        return receipt
    info = request_json(urllib.parse.urlunsplit(parts), opener=opener)
    channel_id = str(info.get('channel_id', ''))
    if not channel_id.isdigit():
        raise RuntimeError('Hiyori webhook returned no channel ID')
    now = (now or datetime.now(JST)).astimezone(JST)
    payload = {
        'content': ('🧪 **日和AI｜専用チャンネル接続テスト**\n'
                    f'送信時刻：{now:%Y/%m/%d %H:%M:%S}（日本時間）\n'
                    '日和AI専用の送信先へ、実際に投稿する接続テストです。\n'
                    '※これは予想ではありません。的中・回収率の集計には含めません。\n'
                    f'テスト番号：{request_id}'),
        'allowed_mentions': {'parse': []}, 'flags': 4096,
    }
    query['wait'] = 'true'
    target = urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))
    message = request_json(target, payload, opener=opener)
    message_id = str(message.get('id', ''))
    if not message_id.isdigit() or str(message.get('channel_id')) != channel_id:
        raise RuntimeError('Discord did not acknowledge the intended Hiyori channel')
    # Acknowledge only the actual POST response; tests and HTTP 204 are insufficient.
    receipt = {'kind': 'hiyori_connection_test', 'request_id': request_id,
               'destination': destination, 'channel_id': channel_id,
               'message_id': message_id, 'sent_at': datetime.now(JST).isoformat()}
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    with receipt_path.open('w', encoding='utf-8') as handle:
        handle.write(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
        handle.flush()
        os.fsync(handle.fileno())
    print('Hiyori Discord post confirmed: ' + json.dumps(receipt), flush=True)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request-id', required=True)
    args = parser.parse_args()
    send(args.request_id)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Never print a webhook URL/token through urllib exception messages.
        print(f'Hiyori test failed: {type(exc).__name__}', flush=True)
        if isinstance(exc, (RuntimeError, ValueError)):
            print(str(exc), flush=True)
        raise SystemExit(1) from None
