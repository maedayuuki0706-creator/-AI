from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

X_POST_URL = "https://api.x.com/2/tweets"
ENV_KEYS = (
    "X_CONSUMER_KEY",
    "X_CONSUMER_SECRET",
    "X_ACCESS_TOKEN",
    "X_ACCESS_TOKEN_SECRET",
)


def _pct(value: str) -> str:
    return urllib.parse.quote(str(value), safe="~-._")


def _credentials() -> tuple[str, str, str, str]:
    values = tuple(os.getenv(key, "").strip() for key in ENV_KEYS)
    if not all(values):
        missing = [key for key, value in zip(ENV_KEYS, values) if not value]
        raise RuntimeError("missing X credentials: " + ", ".join(missing))
    return values


def credentials_configured() -> bool:
    return all(os.getenv(key, "").strip() for key in ENV_KEYS)


def _oauth_header(method: str, url: str) -> str:
    consumer_key, consumer_secret, access_token, access_secret = _credentials()
    oauth = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": uuid.uuid4().hex,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": access_token,
        "oauth_version": "1.0",
    }

    parsed = urllib.parse.urlsplit(url)
    query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    signing_pairs = query_pairs + list(oauth.items())
    normalized = "&".join(
        f"{_pct(k)}={_pct(v)}"
        for k, v in sorted(signing_pairs, key=lambda item: (_pct(item[0]), _pct(item[1])))
    )
    base_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    signature_base = "&".join((_pct(method.upper()), _pct(base_url), _pct(normalized)))
    signing_key = f"{_pct(consumer_secret)}&{_pct(access_secret)}".encode("utf-8")
    digest = hmac.new(signing_key, signature_base.encode("utf-8"), hashlib.sha1).digest()
    oauth["oauth_signature"] = base64.b64encode(digest).decode("ascii")

    return "OAuth " + ", ".join(
        f'{_pct(k)}="{_pct(v)}"' for k, v in sorted(oauth.items())
    )


def post_text(text: str) -> str:
    text = str(text or "").strip()
    if not text:
        raise ValueError("X post text is empty")

    body = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        X_POST_URL,
        data=body,
        headers={
            "Authorization": _oauth_header("POST", X_POST_URL),
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Boat-AI-Navi/x-auto-post-v1",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
            if response.status not in (200, 201):
                raise RuntimeError(f"X HTTP {response.status}: {payload}")
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = ""
        raise RuntimeError(f"X HTTP {exc.code}: {detail[:500]}") from exc

    data = payload.get("data") or {}
    post_id = str(data.get("id") or "").strip()
    if not post_id:
        raise RuntimeError(f"X response missing post id: {payload}")
    return post_id
