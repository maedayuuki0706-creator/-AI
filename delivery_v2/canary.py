"""One silent transport probe, followed by a fresh-store deduplication check."""
from datetime import datetime
import os
from zoneinfo import ZoneInfo
from delivery_v2.discord_sender import post_confirmed, webhook
from delivery_v2.guard import deliver_once
from delivery_v2.store import GitHubStore


def main():
    day = datetime.now(ZoneInfo('Asia/Tokyo')).strftime('%Y%m%d')
    phase = os.getenv('DISCORD_DELIVERY_V2_CANARY_PHASE', 'probe')
    content = '🔧 Discord配信基盤V2の接続確認です。予想とは別の動作確認メッセージです。'
    def sender(text):
        return post_confirmed(webhook('PT3_DISCORD_WEBHOOK_URL'), text, username='配信システム接続確認')
    first = deliver_once('canary',day,'01',1,content,sender,phase=phase,store=GitHubStore())
    if first['status'] not in {'sent','already_sent'}:
        raise RuntimeError(f'Canary not confirmed: {first["status"]}')
    def forbidden(_):
        raise AssertionError('Duplicate Discord POST attempted')
    second = deliver_once('canary',day,'01',1,content,forbidden,phase=phase,store=GitHubStore())
    if second['status'] != 'already_sent' or first['message_id'] != second['message_id']:
        raise RuntimeError('Canary receipt/deduplication mismatch')
    print(f'V2 E2E verified message_id={second["message_id"]}; fresh store prevented second POST')


if __name__ == '__main__': main()
