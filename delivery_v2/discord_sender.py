"""Discord Delivery V2 foundation.

A delivery-only layer. Prediction generation remains in the existing modules.
This module intentionally does not commit runtime state to main.
"""
from __future__ import annotations
import json
import os
import urllib.parse
import urllib.request


class DeliveryError(RuntimeError):
    pass


def post_confirmed(webhook_url: str, content: str, *, username: str | None = None) -> str:
    """Post once and require Discord to return a message id."""
    url = (webhook_url or "").strip()
    if not url:
        raise DeliveryError("webhook is not configured")
    parts = urllib.parse.urlsplit(url)
    query = dict(urllib.parse.parse_qsl(parts.query))
    query["wait"] = "true"
    url = urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))
    payload = {"content": content}
    if username:
        payload["username"] = username
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "boat-ai-delivery-v2"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        body = json.load(response)
    message_id = str(body.get("id", ""))
    if not message_id.isdigit():
        raise DeliveryError("Discord acknowledgement has no message id")
    return message_id


def webhook(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise DeliveryError(f"{name} is not configured")
    return value
