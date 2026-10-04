"""Acknowledged Discord sender preserving per-channel notification policy."""
from __future__ import annotations
import json
import os
import urllib.parse
import urllib.request
from discord_notification_policy import message_payload


class DeliveryError(RuntimeError):
    pass


def post_confirmed(webhook_url: str, content: str, *, username=None, notify_everyone=False) -> str:
    url = (webhook_url or '').strip()
    if not url:
        raise DeliveryError('webhook is not configured')
    parts = urllib.parse.urlsplit(url)
    query = dict(urllib.parse.parse_qsl(parts.query))
    query['wait'] = 'true'
    url = urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))
    payload = message_payload(content, notify_everyone=notify_everyone)
    if username:
        payload['username'] = username
    req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={'Content-Type': 'application/json', 'User-Agent': 'boat-ai-delivery-v2'}, method='POST')
    with urllib.request.urlopen(req, timeout=20) as response:
        body = json.load(response)
    if not isinstance(body, dict) or not str(body.get('id', '')).isdigit():
        raise DeliveryError('Discord acknowledgement has no message id')
    return str(body['id'])


def webhook(name: str) -> str:
    value = os.getenv(name, '').strip()
    if not value:
        raise DeliveryError(f'{name} is not configured')
    return value
