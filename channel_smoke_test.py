"""One-shot Discord routing smoke test for dedicated Boat AI channels."""
from __future__ import annotations

import os

import direct_discord_notify as base


def send_to(env_name: str, content: str) -> None:
    url = os.getenv(env_name, "").strip()
    if not url:
        raise RuntimeError(f"{env_name} is missing")
    original = os.environ.get("DISCORD_WEBHOOK_URL")
    os.environ["DISCORD_WEBHOOK_URL"] = url
    try:
        base.send_discord(content)
    finally:
        if original is None:
            os.environ.pop("DISCORD_WEBHOOK_URL", None)
        else:
            os.environ["DISCORD_WEBHOOK_URL"] = original


def main() -> None:
    send_to(
        "DISCORD_SELECTED_WEBHOOK_URL",
        "🔥 **厳選予想チャンネル｜接続テスト**\n✅ 専用チャンネルへの送信テスト成功確認用です。\n※これは予想ではありません。",
    )
    print("selected channel smoke test sent", flush=True)
    send_to(
        "DISCORD_HIT_WEBHOOK_URL",
        "🎯 **的中速報チャンネル｜接続テスト**\n✅ 専用チャンネルへの送信テスト成功確認用です。\n※これは的中報告ではありません。",
    )
    print("hit channel smoke test sent", flush=True)


if __name__ == "__main__":
    main()
