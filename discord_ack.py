"""One Discord POST, requiring an acknowledged message ID. No blind retries."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request


def post(webhook_url, payload, *, timeout=20):
    parts = urllib.parse.urlsplit(webhook_url)
    query = dict(urllib.parse.parse_qsl(parts.query))
    query['wait'] = 'true'
    url = urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))
    request = urllib.request.Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'User-Agent': 'boat-ai-discord-ack'},
        method='POST',
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        message = json.load(response)
    if not isinstance(message, dict) or not str(message.get('id', '')).isdigit():
        raise RuntimeError('Discord acknowledgement has no message ID')
    return str(message['id'])
