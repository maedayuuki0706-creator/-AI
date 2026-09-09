import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))

def fetch_prediction(url: str) -> str:
    if not url:
        return ""

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Boat-AI-Navi/1.0"}
    )

    with urllib.request.urlopen(req, timeout=20) as res:
        body = res.read().decode("utf-8", errors="replace").strip()
        content_type = res.headers.get("Content-Type", "")

        if "application/json" in content_type:
            try:
                data = json.loads(body)
                return json.dumps(data, ensure_ascii=False, indent=2)[:1500]
            except json.JSONDecodeError:
                pass

        return body[:1500]

def post_discord(webhook_url: str, content: str) -> None:
    payload = json.dumps(
        {"content": content},
        ensure_ascii=False
    ).encode("utf-8")

    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Boat-AI-Navi/1.0"
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=20) as res:
        if res.status not in (200, 204):
            raise RuntimeError(f"Discord returned HTTP {res.status}")

def main() -> int:
    webhook = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    project_id = os.getenv(
        "PROJECT_ID",
        "appgprj_6a98533edf2481919b33aeebf6c41c6a"
    ).strip()
    prediction_url = os.getenv("PREDICTION_URL", "").strip()

    if not webhook:
        print("DISCORD_WEBHOOK_URL is not configured.")
        return 2

    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")

    try:
        prediction = fetch_prediction(prediction_url)
    except Exception as e:
        prediction = f"予想データ取得エラー: {type(e).__name__}: {e}"

    if prediction:
        message = (
            "🚤 競艇AIナビ 自動通知\n"
            f"時刻: {now}\n"
            f"Project: {project_id}\n\n"
            f"{prediction}"
        )
    else:
        message = (
            "🚤 競艇AIナビ 自動通知テスト\n"
            f"時刻: {now}\n"
            f"Project: {project_id}\n"
            "Render Cron Job は正常に起動しています。"
        )

    try:
        post_discord(webhook, message)
        print("Discord notification sent successfully.")
        return 0
    except urllib.error.HTTPError as e:
        print(f"Discord HTTP error: {e.code} {e.reason}")
        return 1
    except Exception as e:
        print(f"Notification failed: {type(e).__name__}: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
