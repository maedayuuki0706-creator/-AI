"""Opt-in transport bridge for an already-built legacy prediction."""
from datetime import datetime
import os
from zoneinfo import ZoneInfo

from delivery_v2.discord_sender import post_confirmed
from delivery_v2.guard import deliver_once
from delivery_v2.store import default_store
from delivery_v2 import receipts

ERRORS = {}


def stalled(result):
    if result.get('status') != 'sending':
        return True
    from datetime import timezone
    claimed = datetime.fromisoformat(result['claimed_at'])
    return (datetime.now(timezone.utc)-claimed).total_seconds() >= 90


def enabled(stream):
    return stream in {s.strip() for s in os.getenv('DISCORD_DELIVERY_V2_STREAMS', '').split(',')}


def send_prediction(stream, record, content, sender, *, store=None):
    store = store or default_store()
    close = datetime.strptime(record['day'] + ' ' + record['deadline'], '%Y%m%d %H:%M').replace(tzinfo=ZoneInfo('Asia/Tokyo'))
    args = (stream, record['day'], record['jcd'], record['rno'])
    key = receipts.identity(*args, record.get('phase') or 'final')
    try:
        result = deliver_once(*args, content, sender, record.get('phase') or 'final', store=store, record=record, expires_at=close)
        if result['status'] not in {'sent', 'already_sent'}:
            ERRORS[key] = result['status']
            if result['status'] in {'failed','uncertain','sending'} and stalled(result):
                notify_failure(stream, record, result, store)
            raise RuntimeError(f'Discord delivery remains {result["status"]}')
        ERRORS.pop(key, None)
        return result
    except Exception:
        ERRORS.setdefault(key, 'storage_or_delivery_error')
        raise


def adopt_legacy(stream, record, legacy, *, store=None):
    """Import proof, never invent an acknowledgement or replay old deliveries."""
    store = store or default_store()
    key = receipts.identity(stream, record['day'], record['jcd'], record['rno'], record.get('phase') or 'final')
    current, sha = store.read(key)
    if current is not None:
        return current
    message_id = str(legacy.get('message_id', ''))
    result = {'key': key, 'stream': stream, 'day': record['day'], 'jcd': record['jcd'],
              'rno': record['rno'], 'phase': record.get('phase') or 'final', 'record': record,
              'status': 'sent' if message_id.isdigit() else 'legacy_unverified',
              'sent_at': legacy.get('delivered_at') or legacy.get('sent_at'), 'source': 'legacy_receipt'}
    if message_id.isdigit():
        result['message_id'] = message_id
    from delivery_v2.store import Conflict
    try:
        store.write(key, result, sha)
    except Conflict:
        result, _ = store.read(key)
    return result


def notify_failure(stream, record, result, store):
    url = os.getenv('DISCORD_DELIVERY_ALERT_WEBHOOK_URL', '').strip() or os.getenv('DISCORD_REPORT_WEBHOOK_URL', '').strip()
    if not url:
        return
    detail = '締切を過ぎたため予想は送信しません。' if result['status']=='missed' else '送信状態を確認できるまで自動再送を保留しています。'
    content = (f'⚠️ 配信システムの確認が必要です\n{stream}｜{record["day"]} '
               f'{record.get("venue",record["jcd"])} {record["rno"]}R\n'
               f'状態: {result["status"]}／試行: {result.get("attempt",0)}回\n'
               + detail)
    try:
        deliver_once('ops_'+stream, record['day'], record['jcd'], record['rno'], content,
            lambda text: post_confirmed(url, text, username='配信監視'), phase='alert', store=store,
            record={'delivery_key': result['key'], 'delivery_status': result['status']})
    except Exception as exc:
        print(f'::error::Delivery incident notification failed ({type(exc).__name__})', flush=True)
