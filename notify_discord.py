import json

import os

import sys

import urllib.error

import urllib.request

SITE_URL = os.getenv(

    "SITE_URL",

    "https://boat-ai-partner.gpmy262mkw.chatgpt.site",

).rstrip("/")

def post_json(path: str, token: str = "") -> dict:

    headers = {

        "Content-Type": "application/json",

        "User-Agent": "Boat-AI-Navi/2.0",

    }

    if token:

        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(

        f"{SITE_URL}{path}",

        data=b"{}",

        headers=headers,

        method="POST",

    )

    with urllib.request.urlopen(request, timeout=60) as response:

        body = response.read().decode("utf-8", errors="replace")

        if response.status < 200 or response.status >= 300:

            raise RuntimeError(f"HTTP {response.status}: {body[:300]}")

        return json.loads(body)

def main() -> int:

    token = os.getenv("NOTIFICATION_RUN_TOKEN", "").strip()

    if not token:

        print("NOTIFICATION_RUN_TOKEN is not configured.")

        return 2

    try:

        races = post_json("/api/races")

        result = post_json("/api/notifications", token)

        print(

            "Boat AI notification run completed: "

            f"races={races.get('total', 0)}, "

            f"eligible={result.get('eligible', 0)}, "

            f"sent={result.get('sent', 0)}, "

            f"skipped={result.get('skipped', 0)}, "

            f"failed={result.get('failed', 0)}"

        )

        return 0 if result.get("ok", False) else 1

    except urllib.error.HTTPError as error:

        body = error.read().decode("utf-8", errors="replace")[:300]

        print(f"HTTP error: {error.code} {body}")

        return 1

    except Exception as error:

        print(f"Notification failed: {type(error).__name__}: {error}")

        return 1

if __name__ == "__main__":

    sys.exit(main())
