"""Collect published races, then run the site's authenticated Discord notifier."""

import argparse
from datetime import date
import json
import os
import sys
import urllib.error
import urllib.request

SITE_URL = os.getenv(
    "SITE_URL", "https://boat-ai-partner.gpmy262mkw.chatgpt.site"
).strip().rstrip("/")

NO_RACES_MESSAGES = {
    "この日のレースデータはまだ公開されていません",
    "開催レースが見つかりませんでした",
}


class ApiError(RuntimeError):
    def __init__(self, path: str, status: int, payload: dict):
        self.path = path
        self.status = status
        self.payload = payload
        explanation = ""
        if 300 <= status < 400:
            explanation = " (別ページへの転送を検出しました。サイトの公開URL・公開設定を確認してください)"
        super().__init__(f"{path}: HTTP {status}{explanation}")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A login page is not an API response. Never forward the run token to it.
        return None


def post_json(path: str, token: str = "") -> dict:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Boat-AI-Navi/2.1",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{SITE_URL}{path}", data=b"{}", headers=headers, method="POST"
    )
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=60) as response:
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        try:
            payload = json.loads(error.read(65536).decode("utf-8", errors="replace"))
        except (ValueError, UnicodeError):
            payload = {}
        finally:
            error.close()
        raise ApiError(path, error.code, payload if isinstance(payload, dict) else {}) from None

    if content_type != "application/json" and not content_type.endswith("+json"):
        raise RuntimeError(f"{path}: JSONではない応答です。サイトの公開URL・公開設定を確認してください")
    try:
        payload = json.loads(body)
    except ValueError:
        raise RuntimeError(f"{path}: JSON応答が壊れています") from None
    if not isinstance(payload, dict):
        raise RuntimeError(f"{path}: API応答の形式が正しくありません")
    return payload


def is_unpublished_race_day(error: ApiError) -> bool:
    if error.path != "/api/races" or error.status != 404:
        return False
    if error.payload.get("error") not in NO_RACES_MESSAGES:
        return False
    value = error.payload.get("date")
    try:
        return isinstance(value, str) and date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def count(payload: dict, key: str, default=None) -> int:
    value = payload.get(key, default)
    if type(value) is not int or value < 0:
        raise RuntimeError(f"API応答の {key} が正しくありません")
    return value


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="レースデータの接続確認のみ。Discordには送信しません")
    args = parser.parse_args(argv)
    token = os.getenv("NOTIFICATION_RUN_TOKEN", "").strip()
    if not args.check and not token:
        print("NOTIFICATION_RUN_TOKEN is not configured.")
        return 2

    try:
        try:
            races = post_json("/api/races")
        except ApiError as error:
            if not is_unpublished_race_day(error):
                raise
            print(f"公開待ち／開催なし: {error.payload['date']}。通知は行わず、次回の自動実行で再確認します。")
            return 0

        if races.get("ok") is not True:
            raise RuntimeError("/api/races: レース更新の成功を確認できませんでした")
        total = count(races, "total")
        if args.check:
            print(f"接続確認OK: races={total}, venues={count(races, 'venues')}。Discord送信なし。")
            return 0

        # Do not automatically retry this POST: a lost response may already have sent messages.
        result = post_json("/api/notifications", token)
        eligible = count(result, "eligible")
        sent = count(result, "sent")
        skipped = count(result, "skipped")
        failed = count(result, "failed")
        analysis_failures = count(result, "analysisFailures", 0)
        print(
            "Boat AI notification run completed: "
            f"races={total}, eligible={eligible}, sent={sent}, "
            f"skipped={skipped}, failed={failed}, analysisFailures={analysis_failures}"
        )
        return 0 if result.get("ok") is True and failed == 0 and analysis_failures == 0 else 1
    except ApiError as error:
        print(f"API接続エラー: {error}")
    except (urllib.error.URLError, TimeoutError):
        print("通信エラー: 接続または応答を確認できませんでした。送信済みの可能性があるため自動再送はしません。")
    except Exception as error:
        # Do not print arbitrary server responses or exception text containing credentials.
        if type(error) is RuntimeError:
            print(f"Notification failed: {error}")
        else:
            print(f"Notification failed: {type(error).__name__}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
